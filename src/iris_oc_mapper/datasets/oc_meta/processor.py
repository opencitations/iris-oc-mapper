import gzip
import queue
import tarfile
import tempfile
import threading
import time
from pathlib import Path
from typing import Generator

import polars as pl
from isal import igzip
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from iris_oc_mapper.utils import get_logger

logger = get_logger(__name__)


gzip.GzipFile = igzip.GzipFile  # type: ignore


class OCMetaProcessor:
    """Processes OC Meta dataset."""

    def __init__(self, dataset):
        self.config = dataset.config
        self.reader = dataset.reader
        self.reporting_stats = {}

    def _scan_csv(self, file) -> pl.LazyFrame | None:
        try:
            df = pl.scan_csv(
                file,
                schema_overrides={"pub_date": pl.String},
            ).select(["id", "title", "type", "pub_date"])
            return df
        except Exception as e:
            logger.error(f"Error reading CSV file: {e}")
            return None

    def iter_batches(
        self, archive: tarfile.TarFile, members: Generator, batch_size: int
    ) -> Generator[pl.LazyFrame, None, None]:
        """
        Yield concatenated LazyFrames in batches.
        """
        batch_time = time.time()
        batch_dfs = []

        for member in members:
            with archive.extractfile(member) as f:  # type: ignore
                df = self._scan_csv(f)
                if df is not None:
                    batch_dfs.append(df)

            if len(batch_dfs) >= batch_size:
                logger.trace(f"Producer prepared batch with {batch_size} files in {time.time() - batch_time:.2f}s")
                yield pl.concat(batch_dfs, how="vertical")
                batch_dfs.clear()
                batch_time = time.time()

        if batch_dfs:
            logger.trace(
                f"Producer prepared final batch with {len(batch_dfs)} files in {time.time() - batch_time:.2f}s"
            )
            yield pl.concat(batch_dfs, how="vertical")

    def process_df(self, df: pl.LazyFrame, ids_lf: pl.LazyFrame) -> pl.LazyFrame:
        """Filter LazyFrame to records with matching IDs."""
        logger.trace("Processing dataframe...")

        matches = (
            df.select(["id", "title", "type", "pub_date"])
            .with_columns(
                (pl.col("id").str.extract(r"(omid:[^\s]+)")).alias("omid"),
                (
                    pl.col("id")
                    .str.extract_all(r"((?:doi|pmid|isbn):[^\s\"]+)")
                    .list.eval(pl.element().drop_nulls())
                    .alias("pid")
                ),
            )
            .explode("pid")
            .drop_nulls("pid")
            .join(ids_lf, left_on="pid", right_on="PID", how="inner")
        )

        return matches

    def run_search(
        self,
        archive,
        members: Generator[tarfile.TarInfo, None, None],
        ids: pl.LazyFrame,
        queue_size: int = 3,
        batch_size: int = 100,
    ) -> pl.DataFrame:
        q: queue.Queue = queue.Queue(maxsize=queue_size)
        stop_token = object()
        stop_event = threading.Event()

        logger.debug("OC Meta search started")
        n_files = int(self.config.get("n_files", 38601))
        n_batches = (n_files + batch_size - 1) // batch_size

        total_start = time.time()

        def producer():
            start = time.time()
            for batch_df in self.iter_batches(archive, members, batch_size=batch_size):
                if stop_event.is_set():
                    break

                while not stop_event.is_set():
                    try:
                        q.put(batch_df, timeout=0.5)
                        logger.trace(f"Producer put batch into queue... queue size: {q.qsize()}")
                        break
                    except queue.Full:
                        continue
            q.put(stop_token)
            logger.trace(f"Producer finished in {time.time() - start:.2f}s")

        def consumer(progress, task_id, temp_dir: Path):
            try:
                batch_idx = 0
                while not stop_event.is_set():
                    try:
                        time_wait_start = time.time()
                        batch_df = q.get(timeout=0.5)
                        wait_time = time.time() - time_wait_start
                    except queue.Empty:
                        continue

                    if batch_df is stop_token:
                        logger.trace("Consumer received stop token, exiting.")
                        q.task_done()
                        break

                    try:
                        logger.trace(f"Consumer picked batch {batch_idx} from queue after waiting {wait_time:.2f}s")
                        processing_start = time.time()
                        logger.trace(f"Processing df {batch_idx}...")
                        res = self.process_df(batch_df, ids)
                        logger.trace(f"Filtering df {batch_idx} took {time.time() - processing_start:.2f}s ")

                        if res is not None:
                            time_to_save = time.time()
                            temp_path = temp_dir / f"batch_{batch_idx}.parquet"
                            res.sink_parquet(
                                temp_path,
                                compression="lz4",
                                maintain_order=False,
                                statistics=False,
                            )
                            logger.trace(
                                f"Saved batch {batch_idx} to {temp_dir.name} / {temp_path.name}. saving took {time.time() - time_to_save:.2f}s"
                            )
                        batch_idx += 1
                        q.task_done()
                        progress.update(task_id, advance=1, rate=f"{time.time() - processing_start:.2f} s/batch")
                        logger.trace(f"Processed df {batch_idx} in {time.time() - processing_start:.2f}s ")
                    except Exception as e:
                        logger.error(f"Error processing df {batch_idx}: {e}")
                        stop_event.set()
                        break
            except KeyboardInterrupt:
                stop_event.set()

        with tempfile.TemporaryDirectory(delete=True) as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            logger.debug(f"Created temporary directory at {temp_dir} for processing OC Meta CSV files")

            with Progress(
                TextColumn("[bold blue]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                TextColumn("[green]{task.fields[rate]}"),
            ) as progress:
                task_id = progress.add_task(
                    " [bold magenta]Processing OC Meta CSV files[/bold magenta]", total=n_batches, rate="0.00 s/file"
                )

                t_prod = threading.Thread(target=producer, name="ProducerThread", daemon=True)
                t_cons = threading.Thread(
                    target=consumer, args=(progress, task_id, temp_dir), name="ConsumerThread", daemon=True
                )

                t_prod.start()
                t_cons.start()

                try:
                    while t_prod.is_alive() or t_cons.is_alive():
                        time.sleep(0.2)
                except KeyboardInterrupt:
                    stop_event.set()
                    raise
                finally:
                    for t in (t_prod, t_cons):
                        try:
                            t.join(timeout=2)
                        except KeyboardInterrupt:
                            raise

            logger.debug(f"All batches processed in {time.time() - total_start:.2f}s")

            return pl.scan_parquet(Path(temp_dir) / "*.parquet").collect()

    def search_for_ids(self, ids: pl.LazyFrame) -> pl.DataFrame:
        """
        Search for records by ID.

        Args:
            ids (list[str]): List of IDs to search for.
            year_cutoff (int | None): Optional year cutoff to filter results.
        """

        logger.info(
            f"Searching OC Meta for {ids.select(pl.len()).collect().item()} PIDs...",
            extra={"cli_msg": f" 🔍 Searching OC Meta for {ids.select(pl.len()).collect().item()} PIDs..."},
        )
        batch_size = int(self.config.get("batch_size", 100))
        n_files = int(self.config.get("n_files", 38601))
        logger.debug(
            f"Using batch size of {batch_size}. expected ~{n_files}/{batch_size} = {n_files / batch_size} batches."
        )

        with tarfile.open(self.reader.oc_meta_path, "r:gz") as archive:
            members = self.reader.iter_members(archive)
            try:
                matches = self.run_search(archive, members, ids, queue_size=3, batch_size=batch_size)
            except KeyboardInterrupt:
                raise

        return matches
