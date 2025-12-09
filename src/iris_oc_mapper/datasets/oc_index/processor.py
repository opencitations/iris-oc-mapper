import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterator, List, Optional
from zipfile import BadZipFile, ZipFile

import polars as pl
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pcsv
import pyarrow.parquet as pq
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


class OCIndexProcessor:
    """Processes OC Index dataset."""

    def __init__(self, dataset):
        self.reader = dataset.reader
        self.config = dataset.config
        self.schema_overrides = {
            "id": pa.string(),
            "citing": pa.string(),
            "cited": pa.string(),
            "creation": pa.string(),
        }

    def _stream_csv_from_zip(self, zip_path: Path, omids_array: pa.Array) -> Iterator[pa.RecordBatch]:
        """
        Stream CSV files from a single ZIP archive, yielding batches of rows that match given OMIDs.
        """
        try:
            with ZipFile(zip_path, "r") as zf:
                csv_files = [name for name in zf.namelist() if name.endswith(".csv")]

                for csv_filename in csv_files:
                    csv_start_time = time.time()
                    try:
                        with zf.open(csv_filename, "r") as csv_file:
                            reader = pcsv.open_csv(
                                csv_file,
                                read_options=pcsv.ReadOptions(block_size=64 << 20),
                                parse_options=pcsv.ParseOptions(delimiter=",", quote_char='"'),
                                convert_options=pcsv.ConvertOptions(
                                    column_types=self.schema_overrides,
                                    include_columns=["id", "citing", "cited", "creation"],
                                ),
                            )

                            for batch in reader:
                                cited_mask = pc.is_in(batch["cited"], omids_array)
                                citing_mask = pc.is_in(batch["citing"], omids_array)
                                mask = pc.or_(cited_mask, citing_mask)
                                idx = pc.indices_nonzero(mask)
                                if len(idx) == 0:
                                    continue

                                batch = batch.append_column("is_citing_iris", citing_mask)
                                batch = batch.append_column("is_cited_iris", cited_mask)

                                batch_matches = batch.take(idx)
                                logger.trace(f"Processed batch from {csv_filename}")
                                yield batch_matches

                            logger.trace(
                                f"Processed {csv_filename} ({zf.getinfo(csv_filename).file_size / (1024 * 1024):.2f} MB) in {zip_path.name} in {time.time() - csv_start_time:.2f}s"
                            )

                    except KeyboardInterrupt:
                        raise
                    except Exception as e:
                        logger.warning(f"Error processing {csv_filename} in {zip_path.name}: {e}")

        except BadZipFile:
            logger.error(f"Bad zip file: {zip_path.name}")
        except Exception as e:
            logger.error(f"Critical error in {zip_path.name}: {e}")

    def _save_processed_archive_to_parquet(self, zip_path, omids_array, output_dir):
        """Process a single OC Index ZIP archive and save table containing matching records to Parquet file."""
        match_count = 0
        writer = None

        for batch in self._stream_csv_from_zip(zip_path, omids_array):
            if writer is None:
                output_file = output_dir / f"{zip_path.stem}.parquet"
                writer = pq.ParquetWriter(str(output_file), batch.schema)

            writer.write_table(pa.Table.from_batches([batch]))
            match_count += batch.num_rows

        if writer:
            writer.close()

        return zip_path.name, match_count

    def _merge_parquet_files(self, parquet_files: List[Path]) -> pl.LazyFrame:
        """Merge multiple Parquet files into a single LazyFrame.

        Args:
            parquet_files (List[Path]): List of paths to Parquet files.

        Returns:
            pl.LazyFrame: Merged LazyFrame containing data from all Parquet files.
        """
        if not parquet_files:
            return pl.LazyFrame()

        lazy_dfs = [pl.scan_parquet(str(f / "*.parquet")) for f in parquet_files]
        combined = pl.concat(lazy_dfs, how="vertical_relaxed")

        return combined

    def search_by_omid(
        self,
        omids_list: List[str],
    ) -> Optional[pl.DataFrame]:
        """Iterate over OC Index dataset archives to find records matching given OMIDs.

        Args:
            omids_list: List of OMIDs to search

        Returns:
            pl.DataFrame: DataFrame containing matching records from OC Index
        """
        omids_set = set(omids_list)
        logger.info(
            f"Searching OC Index for {len(omids_set)} unique OMIDs...",
            extra={"cli_msg": f" 🔍 Searching OC Index for {len(omids_set)} unique OMIDs..."},
        )
        archives = self.reader.get_csv_archives()
        omids_array = pa.array(omids_set, type=pa.string())

        with tempfile.TemporaryDirectory(delete=True) as temp_dir:
            logger.debug(f"Created temporary directory at {temp_dir} for processing OC Index archives")
            temp_path = Path(temp_dir)
            results = []
            parquet_files = []

            with ThreadPoolExecutor(max_workers=self.config.get("max_workers", 4)) as executor:
                try:
                    futures = {}

                    for archive in archives:
                        output_dir = temp_path / f"_{archive.stem}"
                        output_dir.mkdir(parents=True, exist_ok=True)
                        future = executor.submit(
                            self._save_processed_archive_to_parquet,
                            archive,
                            omids_array,
                            output_dir,
                        )
                        futures[future] = output_dir

                    with Progress(
                        TextColumn("[bold blue]{task.description}"),
                        BarColumn(),
                        MofNCompleteColumn(),
                        TimeElapsedColumn(),
                        TimeRemainingColumn(),
                    ) as progress:
                        task_id = progress.add_task(
                            " [bold magenta]Processing OC Index archives[/bold magenta]", total=len(archives)
                        )

                        for future in as_completed(futures):
                            try:
                                archive_name, match_count = future.result()
                                results.append((archive_name, match_count))

                                if match_count > 0:
                                    parquet_files.append(futures[future])

                                progress.update(task_id, advance=1)

                            except Exception as e:
                                logger.error(f"Error processing archive: {e}")
                except KeyboardInterrupt:
                    logger.warning("Cancelling tasks...")
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise

            total_matches = sum(r[1] for r in results if r[1] > 0)
            if total_matches == 0:
                logger.info(
                    "No matching records found", extra={"cli_msg": " ❌ No matching records found in OC Index."}
                )
                return pl.DataFrame()

            logger.debug(f"Found {total_matches} matches across {len(parquet_files)} archives")

            lazy_result = self._merge_parquet_files(parquet_files)
            logger.info("Deduplicating Index matches...", extra={"cli_msg": " ♻️  Deduplicating Index matches..."})
            # DEDUPLICATE matches by 'id' column
            unique_matches = lazy_result.unique(subset=["id"])
            logger.debug(
                f"Search in OC Index finished: {unique_matches.select(pl.len()).collect().item()} unique matches"
            )

            unique_matches.sink_parquet(temp_path / "oc_index_matches.parquet")

            final_df = pl.scan_parquet(temp_path / "oc_index_matches.parquet").collect()
            logger.debug(f"Final DF size: {final_df.estimated_size()}")

            return final_df

        return None
