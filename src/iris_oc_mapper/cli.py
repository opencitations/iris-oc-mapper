import datetime
import logging
from pathlib import Path

import typer
from rich.logging import RichHandler
from rich.progress import Progress, SpinnerColumn, TextColumn

from iris_oc_mapper.configs import IRISOCMapperConfig, load_config
from iris_oc_mapper.converter import IRISConverter
from iris_oc_mapper.datasets.iris import (
    IRISDataset,
    IRISDatasetError,
    create_no_pid_dataset,
)
from iris_oc_mapper.datasets.oc_index import OCIndexDataset, create_in_index_dataset
from iris_oc_mapper.datasets.oc_meta import (
    OCMetaDataset,
    create_in_meta_dataset,
    create_not_in_meta_dataset,
)
from iris_oc_mapper.reporting.generator import generate_html_report
from iris_oc_mapper.utils import TRACE_LEVEL

logger = logging.getLogger(__name__)

app = typer.Typer(help="IRIS <-> OpenCitations Mapping CLI", no_args_is_help=True)


def _version_callback(value: bool) -> None:
    if not value:
        return
    try:
        from iris_oc_mapper import __version__ as _pkg_version
        typer.echo(_pkg_version)
    except Exception:
        typer.echo("unknown")
    raise typer.Exit()


@app.callback(invoke_without_command=True)
def _app_callback(
    version: bool = typer.Option(
        None,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show the application version and exit.",
    )
):
    return


class TyperLogHandler(logging.Handler):
    """Custom logging handler to route logs through Typer's echo."""

    def emit(self, record: logging.LogRecord) -> None:
        msg = getattr(record, "cli_msg", self.format(record))

        try:
            if record.levelno >= logging.ERROR:
                typer.secho(msg, fg="red", err=True)
            elif record.levelno >= logging.WARNING:
                typer.secho(msg, fg="yellow")
            elif record.levelno >= logging.INFO:
                typer.echo(msg)
            else:
                typer.secho(msg, fg="blue")
        except Exception:
            self.handleError(record)


def setup_log_handler(debug: bool = False, trace: bool = False) -> logging.Logger:
    handler: RichHandler | TyperLogHandler

    if debug or trace:
        handler = RichHandler(
            rich_tracebacks=True,
            markup=True,
            show_time=True,
            show_path=False,
            log_time_format="[%X]",
        )
    else:
        handler = TyperLogHandler()

    handler.setFormatter(logging.Formatter("%(message)s"))

    if trace:
        level = TRACE_LEVEL
    elif debug:
        level = logging.DEBUG
    else:
        level = logging.INFO

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    return logging.getLogger(__name__)


def validate_format(value: str) -> str:
    """Validate output format option."""
    lowered = value.lower()
    if lowered in {"csv", "parquet"}:
        return lowered
    raise typer.BadParameter("Format must be 'csv' or 'parquet'.")


def get_datasets_to_save(save_datasets_option: str | None) -> set | None:
    """Parse the save_datasets option into a set of dataset names."""
    options = {"in_meta", "no_pid", "not_in_meta", "in_index"}
    if save_datasets_option is None:
        return None
    if save_datasets_option.lower().strip() in {"", "all"}:
        return options
    selected = {ds.strip() for ds in save_datasets_option.split(",") if ds.strip()}
    invalid = selected - options
    if invalid:
        raise typer.BadParameter(f"Invalid output dataset names: {', '.join(invalid)}")
    return selected


def read_config(config_file: Path | None) -> IRISOCMapperConfig:
    """Load configuration or return default."""
    if config_file is None:
        typer.echo(" ⚙️  Configuration:         Default")
        return IRISOCMapperConfig()
    typer.echo(f" ⚙️  Configuration:         {config_file}")
    return IRISOCMapperConfig.from_yaml(config_file)


@app.command()
def map(
    iris_path: Path = typer.Option(..., "--iris", "-i", exists=True, readable=True, help="Path to IRIS dataset."),
    meta_path: Path | None = typer.Option(
        None, "--meta", "-m", exists=True, readable=True, help="Path to OC Meta dataset."
    ),
    index_path: Path | None = typer.Option(
        None, "--index", "-x", exists=True, readable=True, help="Path to OC Index dataset."
    ),
    skip_index: bool = typer.Option(False, "--skip-index", "-si", help="Skip OC Index mapping."),
    output_dir: Path = typer.Option(Path("results/"), "--output", "-o", file_okay=False, help="Output directory."),
    output_format: str = typer.Option(
        "csv",
        "--format",
        "-f",
        help="Output datasets format: csv (default) or parquet.",
        callback=validate_format,
    ),
    datasets_to_save: str = typer.Option(
        None,
        "--save-datasets",
        "-s",
        help=(
            "Save output datasets to disk. "
            'Use an empty string ("") to save all datasets, or specify a comma-separated list: '
            "in_meta,no_pid,not_in_meta,in_index"
        ),
        callback=get_datasets_to_save,
    ),
    generate_report: bool = typer.Option(True, "--generate-report", "-r", help="Generate a mapping report."),
    cutoff_year: int | None = typer.Option(None, "--cutoff", "-c", help="Cutoff year for publications (inclusive)."),
    batch_size: int | None = typer.Option(
        None, "--batch-size", "-b", help="Number of OC Meta files to process per batch."
    ),
    max_workers: int | None = typer.Option(
        None,
        "--max-workers",
        "-w",
        help="Maximum number of worker threads for OC Index processing.",
    ),
    config_file: Path | None = typer.Option(
        None,
        "--config",
        "-cf",
        exists=True,
        readable=True,
        help="Path to an optional YAML configuration file.",
    ),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable detailed logging."),
    trace: bool = typer.Option(False, "--trace", "-t", help="Enable trace logging."),
):
    """
    Search for IRIS records within OC Meta/Index.
    """
    logger = setup_log_handler(debug=debug, trace=trace)

    # -----------------------------------------------------------------------
    # Validate parameters and echo starting info
    # -----------------------------------------------------------------------
    if not skip_index and index_path is None:
        raise typer.BadParameter(" OC Index path must be provided unless --skip-index is set.")

    start_time = datetime.datetime.now()

    typer.echo()
    typer.secho(" Starting IRIS <-> OpenCitations Mapping", fg=typer.colors.BRIGHT_MAGENTA, bold=True)
    typer.echo(" ──────────────────────────────────────")
    typer.echo(f" 📦 IRIS dataset:          {iris_path.absolute() if iris_path else 'N/A'}")
    typer.echo(f" 📦 OC Meta dump:          {meta_path.absolute() if meta_path else 'N/A'}")
    typer.echo(f" 📦 OC Index dump:         {index_path.absolute() if index_path else 'N/A'}")
    typer.echo(f" 📂 Output directory:      {output_dir.absolute()}")
    typer.echo(f" 📄 Output format:         {output_format.upper()}")

    if cutoff_year:
        typer.echo(f" ⏳ Cutoff year:           {cutoff_year}")

    cfg = read_config(config_file)

    typer.echo(f" 💾 Datasets to save:      {', '.join(datasets_to_save) if datasets_to_save else 'None'}")

    batch_size = batch_size if batch_size else cfg.oc_meta.batch_size
    typer.echo(f" ⚡ Batch size:            {batch_size}")

    max_workers = max_workers if max_workers else cfg.oc_index.max_workers
    typer.echo(f" ⚡ Max workers:           {max_workers}")

    typer.echo(" ──────────────────────────────────────")
    typer.echo()

    if datasets_to_save in (None, set()):
        if not typer.confirm(" ⚠️  No output datasets will be saved. Continue?", default=False):
            typer.echo(" Mapping cancelled.")
            raise typer.Exit(code=0)

    in_meta_dir = output_dir / "iris_in_oc_meta"
    if in_meta_dir.exists():
        if not typer.confirm(
            f" ⚠️  '{in_meta_dir}' already exists. Are you sure you want to overwrite it?", default=False
        ):
            typer.echo(" Mapping cancelled.")
            raise typer.Exit(code=0)

    try:
        # -----------------------------------------------------------------------
        # 1. Load IRIS
        # -----------------------------------------------------------------------
        try:
            iris_dataset = IRISDataset(iris_path, config=cfg.iris.model_dump())
        except Exception as e:
            typer.secho(f" ❌ Failed to load IRIS dataset: {e}", fg=typer.colors.RED, bold=True)
            logger.exception("IRIS dataset loading failed")
            raise typer.Exit(code=2)

        # -----------------------------------------------------------------------
        # #. Create "iris no pid" dataset
        # -----------------------------------------------------------------------
        iris_no_pid_dataset = create_no_pid_dataset(iris_dataset)

        # -----------------------------------------------------------------------
        # 2. Load OC Meta
        # -----------------------------------------------------------------------
        if not meta_path:
            raise IRISDatasetError("OC Meta path must be provided when mapping is requested.")

        try:
            oc_meta_dataset = OCMetaDataset(meta_path, config=cfg.oc_meta.model_dump())
        except Exception as e:
            typer.secho(f"❌ Failed to load OC Meta dataset: {e}", fg=typer.colors.RED, bold=True)
            logger.exception("OC Meta dataset loading failed")
            raise typer.Exit(code=2)

        # -----------------------------------------------------------------------
        # 3. Create "iris in meta" dataset
        # -----------------------------------------------------------------------
        iris_in_meta_dataset = create_in_meta_dataset(
            oc_meta_dataset=oc_meta_dataset,
            iris_dataset=iris_dataset,
            cutoff_year=cutoff_year,
        )

        # -----------------------------------------------------------------------
        # 4. Load OC Index
        # -----------------------------------------------------------------------
        if index_path and not skip_index:
            try:
                oc_index_dataset = OCIndexDataset(index_path, config=cfg.oc_index.model_dump())
            except Exception as e:
                typer.secho(f"❌ Failed to load OC Meta dataset: {e}", fg=typer.colors.RED, bold=True)
                logger.exception("OC Meta dataset loading failed")
                raise typer.Exit(code=2)

            # -----------------------------------------------------------------------
            # 5. Create "iris in index" dataset
            # -----------------------------------------------------------------------
            iris_in_index_dataset = create_in_index_dataset(
                oc_index_dataset=oc_index_dataset,
                iris_in_meta_dataset=iris_in_meta_dataset,
                cutoff_year=cutoff_year,
            )
        else:
            iris_in_index_dataset = None
            typer.echo(" ⏭️  Skipping OC Index mapping.")

        # -----------------------------------------------------------------------
        # 6. Fix OC Meta's own duplicates in "iris in meta" dataset
        # -----------------------------------------------------------------------
        iris_in_meta_dataset.fix_oc_meta_duplicates()

        # -----------------------------------------------------------------------
        # 7. Create "iris not in meta" dataset
        # -----------------------------------------------------------------------
        iris_not_in_meta_dataset = create_not_in_meta_dataset(
            iris_dataset=iris_dataset,
            iris_in_meta_dataset=iris_in_meta_dataset,
            output_format=output_format,
        )

        # -----------------------------------------------------------------------
        # 8. Save datasets
        # -----------------------------------------------------------------------
        if datasets_to_save:
            if "in_meta" in datasets_to_save:
                iris_in_meta_dataset.save(output_dir, output_format=output_format)
                iris_in_meta_dataset.save_metadata(output_dir)
                typer.echo(f' ✅ "IRIS in OC Meta" saved to {output_dir}/iris_in_oc_meta')

            if "in_index" in datasets_to_save and iris_in_index_dataset is not None:
                iris_in_index_dataset.save(output_dir, output_format=output_format)
                iris_in_index_dataset.save_metadata(output_dir)
                typer.echo(f' ✅ "IRIS in OC Index" saved to {output_dir}/iris_in_oc_index')

            if "no_pid" in datasets_to_save:
                iris_no_pid_dataset.save(output_dir, output_format=output_format)
                iris_no_pid_dataset.save_metadata(output_dir)
                typer.echo(f' ✅ "IRIS no PID" saved to {output_dir}/iris_no_pid')

            if "not_in_meta" in datasets_to_save:
                iris_not_in_meta_dataset.save(output_dir, output_format=output_format)
                iris_not_in_meta_dataset.save_metadata(output_dir)
                typer.echo(f' ✅ "IRIS not in OC Meta" saved to {output_dir}/iris_not_in_oc_meta')

        # -----------------------------------------------------------------------
        # 9. Generate mapping report
        # -----------------------------------------------------------------------
        if generate_report:
            datasets = {
                "iris": iris_dataset,
                "iris_no_pid": iris_no_pid_dataset,
                "in_meta": iris_in_meta_dataset,
                "not_in_meta": iris_not_in_meta_dataset,
                "in_index": iris_in_index_dataset,
            }

            report_output_path = output_dir / "mapping_report.html"
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=True,
            ) as progress:
                progress.add_task(description="📝 Generating mapping report...", total=None)
                generate_html_report(report_output_path, datasets)

            # -----------------------------------------------------------------------
            # Echo mapping summary
            # -----------------------------------------------------------------------
            typer.echo()
            typer.echo(" ─────────────────────────────")
            typer.secho(" Summary", fg=typer.colors.MAGENTA, bold=True)
            typer.echo(" ─────────────────────────────")
            try:
                matched_iris_records = iris_in_meta_dataset.df.height
                end_time = datetime.datetime.now()
                execution_time = str(end_time - start_time).split(".")[0]
                typer.echo(f" Matched IRIS records:      {matched_iris_records}")
                typer.echo(f" Execution time:            {execution_time}")
                typer.echo(f" Output written to:         {output_dir}")
                typer.echo(" ─────────────────────────────")
                typer.echo()

            except Exception as e:
                typer.secho(f" ⚠️  Could not generate summary: {e}", fg=typer.colors.YELLOW)

    except typer.Exit:
        raise
    except IRISDatasetError as e:
        typer.secho(f" ❌ Dataset error: {e}", fg=typer.colors.RED, bold=True)
        raise typer.Exit(code=2)
    except KeyboardInterrupt:
        typer.secho(" ❌ Interrupt received, stopping processing.", fg=typer.colors.RED, bold=True)
        raise typer.Exit(code=130)
    except Exception as e:
        typer.secho(f" ❌ Unexpected error: {e}", fg=typer.colors.RED, bold=True)
        logger.exception("Unhandled exception")
        raise typer.Exit(code=1)


@app.command()
def convert(
    path: Path = typer.Option(
        ..., "-p", "--path", help="The path of the folder that contains the original IRIS dump files"
    ),
    destination: Path = typer.Option(
        ..., "-o", "--destination", help="The path of the destination folder where to store the converted CSV files"
    ),
    types: bool = typer.Option(
        False,
        "-t",
        "--types",
        help="To specify in case the IRIS input files includes the file 'ITEM_TYPE' that must be considered in the process",
    ),
    separator: str = typer.Option(
        ",",
        "-s",
        "--separator",
        help="The separator to use to split columns in case the original IRIS dump is provided in CSV-like formats",
    ),
    encoding: str = typer.Option(
        "utf-8", "-e", "--encoding", help="The encode to use to process the original IRIS dump files"
    ),
    file_format: str = typer.Option(
        "csv", "-f", "--format", help="The format (i.e. the extension) used to store the original IRIS dump files"
    ),
    miur_map_file: Path | None = typer.Option(
        None,
        "-m",
        "--miur-map",
        exists=True,
        readable=True,
        help="Path to MIUR type mapping file.",
    ),
    debug: bool = typer.Option(False, "--debug", help="Enable detailed logging."),
):
    """
    Convert IRIS dumps downloaded in the original format via SQL queries into CSV files that are more manageable to process and handle.
    """
    setup_log_handler(debug=debug)

    cfg = load_config("iris")

    ic = IRISConverter(
        folder_path=path,
        separator=separator,
        encoding=encoding,
        extension=file_format,
        destination_path=destination,
        use_item_types=types,
        miur_map_file=miur_map_file,
        config=cfg,
    )
    try:
        ic.convertData()
    except Exception as e:
        typer.secho(f"❌ Conversion failed: {e}", fg=typer.colors.RED, bold=True, err=True)
        raise typer.Exit(2)
    typer.echo(f"✅ Conversion completed! Output saved to: {destination}")


if __name__ == "__main__":
    app()
