import datetime
import logging
from pathlib import Path

import polars as pl
from jinja2 import Environment, FileSystemLoader

from iris_oc_mapper import __version__ as VERSION
from iris_oc_mapper.datasets.iris.dataset import IRISDataset
from iris_oc_mapper.datasets.oc_meta.dataset import IRISInOCMetaDataset
from iris_oc_mapper.reporting.plots import (
    generate_coverage_plot,
    generate_iris_sankey,
    generate_temporal_distribution,
)
from iris_oc_mapper.reporting.utils import df_to_html, get_implausible_years

logger = logging.getLogger(__name__)


def get_iris_stats(iris_dataset: IRISDataset) -> dict:
    """Collect statistics from the IRIS dataset in a dictionary."""
    logger.debug("Collecting IRIS stats...")
    iris_record_count = iris_dataset.df.height
    iris_no_pids = iris_dataset.get_no_pid().height
    iris_with_pids = iris_record_count - iris_no_pids

    invalid_identifier_rows = iris_dataset.reader.reporting_stats.get("invalid_identifier_rows", {})

    processor_stats = iris_dataset.processor.reporting_stats
    found_dois = processor_stats.get("found_dois", 0)
    found_pmids = processor_stats.get("found_pmids", 0)
    found_isbns = processor_stats.get("found_isbns", 0)

    invalid_dois = processor_stats.get("invalid_dois", 0)
    invalid_pmids = processor_stats.get("invalid_pmids", 0)
    invalid_isbns = processor_stats.get("invalid_isbns", 0)

    misassigned_dois = processor_stats.get("misassigned_dois", 0)
    misassigned_pmids = processor_stats.get("misassigned_pmids", 0)
    misassigned_isbns = processor_stats.get("misassigned_isbns", 0)

    valid_dois = processor_stats.get("valid_dois", 0)
    valid_pmids = processor_stats.get("valid_pmids", 0)
    valid_isbns = processor_stats.get("valid_isbns", 0)

    valid_pids = processor_stats.get("valid_pids", 0)

    return {
        "invalid_identifier_rows": invalid_identifier_rows,
        "record_count": iris_record_count,
        "without_pids": iris_no_pids,
        "without_pids_percentage": round((iris_no_pids / iris_record_count) * 100, 2) if iris_record_count > 0 else 0,
        "with_pids": iris_with_pids,
        "found_dois": found_dois,
        "found_pmids": found_pmids,
        "found_isbns": found_isbns,
        "found_pids": found_dois + found_pmids + found_isbns,
        "invalid_dois": invalid_dois,
        "invalid_pmids": invalid_pmids,
        "invalid_isbns": invalid_isbns,
        "misassigned_dois": misassigned_dois,
        "misassigned_pmids": misassigned_pmids,
        "misassigned_isbns": misassigned_isbns,
        "valid_dois": valid_dois,
        "valid_pmids": valid_pmids,
        "valid_isbns": valid_isbns,
        "valid_pids": valid_pids,
    }


def get_in_meta_stats(in_meta_dataset: IRISInOCMetaDataset) -> dict:
    """Collect statistics from the IRIS in Meta dataset in a dictionary."""
    logger.debug("Collecting IRIS in Meta stats...")
    return {
        "record_count": in_meta_dataset.df.height,
        "types_table": None,
        "source": getattr(in_meta_dataset, "source", "N/A"),
        "cutoff_year": getattr(in_meta_dataset, "cutoff_year", None),
    }


def in_meta_types_coverage(in_meta: IRISInOCMetaDataset, iris: IRISDataset) -> str:
    """Generate a coverage table of IRIS types found in the IRIS in Meta dataset.
    Args:
        in_meta (IRISInOCMetaDataset): The *IRIS in OC Meta* dataset instance.
        iris (IRISDataset): The IRIS dataset instance.

    Returns:
        str: The coverage table as an HTML string.
    """
    logger.debug("Generating IRIS in Meta types coverage table...")
    pid_validation_column = iris.config.get("type_validation_column", "MIUR_TYPE_CODE")
    if pid_validation_column == "MIUR_TYPE_CODE":
        type_dict = iris.config.get("miur_types", {})
    else:
        type_dict = iris.get_type_dict()

    iris_type_count = in_meta.df.group_by("iris_type").len().sort("len", descending=True)
    iris_pids_type_count = (
        iris.get_persistent_identifiers(silent=True)
        .group_by(pid_validation_column)
        .len()
        .sort("len", descending=True)
        .with_columns(pl.col(pid_validation_column).replace_strict(type_dict))
    )
    table = (
        iris_pids_type_count.join(
            iris_type_count,
            left_on=pid_validation_column,
            right_on="iris_type",
            how="left",
        )
        .with_columns(pl.col("len_right").fill_null(strategy="zero"))
        .with_columns(((pl.col("len_right") * 100 / pl.col("len")).round(2)).alias("Coverage"))
        .rename(
            {
                "len": "from IRIS",
                "len_right": "Found in Meta",
                pid_validation_column: "IRIS Type",
            }
        )
        .sort("from IRIS", descending=True)
        .with_columns(pl.col("Coverage").cast(pl.String) + "%")
    )

    return df_to_html(table)


def generate_types_coverage(dataset: IRISDataset | IRISInOCMetaDataset | None, pid_type_column: str) -> str | None:
    """Generate a coverage table of IRIS types found in the given dataset.

    Args:
        dataset (IRISDataset | IRISInOCMetaDataset | None): The dataset instance
        pid_type_column (str): The column name representing the PID type.

    Returns:
        str | None: The coverage table as an HTML string, or None if the dataset is empty.
    """
    logger.debug(f"Generating {getattr(dataset, 'name', 'N/A')} types coverage table...")
    if dataset is None or dataset.df.height == 0:
        return None

    table = (
        dataset.df.group_by(pid_type_column)
        .len()
        .sort("len", descending=True)
        .rename({pid_type_column: "IRIS Type", "len": "Count"})
    )
    return df_to_html(table)


def get_in_index_stats(in_index_dataset) -> dict:
    logger.debug("Collecting IRIS in Index stats...")
    if in_index_dataset is None:
        return {
            "record_count": 0,
        }

    index_stats = {
        "source": getattr(in_index_dataset, "source", "N/A"),
        "record_count": in_index_dataset.df.height,
        "cited_count": in_index_dataset.df["is_cited_iris"].sum(),
        "citing_count": in_index_dataset.df["is_citing_iris"].sum(),
        "both_iris_citations": (in_index_dataset.df["is_cited_iris"] & in_index_dataset.df["is_citing_iris"]).sum(),
    }

    return index_stats


def get_stats(datasets) -> dict:
    """Collect statistics from the datasets in a dictionary."""
    iris = datasets.get("iris")
    in_meta = datasets.get("in_meta")
    in_index = datasets.get("in_index")
    iris_no_pid = datasets.get("iris_no_pid")
    not_in_meta = datasets.get("not_in_meta")

    iris_stats = get_iris_stats(iris) if iris else {}

    type_validation_column = iris.config.get("type_validation_column", "MIUR_TYPE_CODE")
    pid_type_column = {
        "MIUR_TYPE_CODE": "MIUR_TYPE_NAME",
        "OWNING_COLLECTION": "OWNING_COLLECTION_DES",
    }.get(type_validation_column, "MIUR_TYPE_NAME")

    if pid_type_column == "MIUR_TYPE_NAME":
        miur_type_dict = iris.config.get("miur_types")
        valid_isbn_types = "; ".join(
            [
                miur_type_dict[miur_type]
                for miur_type in iris.config.get("pid_type_validation").get("isbn").get("valid_types")
            ]
        )
    elif pid_type_column == "OWNING_COLLECTION_DES":
        iris_type_dict = iris.get_type_dict()
        valid_isbn_types = "; ".join(
            [
                iris_type_dict[iris_type]
                for iris_type in iris.config.get("pid_type_validation").get("isbn").get("valid_types")
            ]
        )
    else:
        valid_isbn_types = "N/A"

    return {
        "in_meta": {
            **get_in_meta_stats(in_meta),
            "coverage": round((in_meta.df.height / iris.df.height) * 100, 2),
            "coverage_plot": generate_coverage_plot(in_meta, iris, iris_no_pid) if iris and in_meta else None,
            "types_coverage": in_meta_types_coverage(in_meta, iris),
        },
        "iris": {
            **iris_stats,
            "source": getattr(iris, "source", "N/A"),
            "valid_isbn_types": valid_isbn_types,
            "sankey_plot": generate_iris_sankey(iris_stats) if iris else None,
            "temporal_distribution": generate_temporal_distribution(iris.read_csv_master()) if iris else None,
            "implausible_years": get_implausible_years(iris.read_csv_master()) if iris else None,
        },
        "iris_no_pid": {
            "record_count": iris_no_pid.df.height if iris_no_pid else 0,
            "types_coverage": generate_types_coverage(iris_no_pid, pid_type_column),
        },
        "not_in_meta": {
            "record_count": not_in_meta.df.height if not_in_meta else 0,
            "types_coverage": generate_types_coverage(not_in_meta, pid_type_column),
        },
        "in_index": get_in_index_stats(in_index),
    }


def generate_html_report(output_path: Path, datasets: dict, **kwargs) -> Path:
    """Generate an HTML report of the mapping.

    Args:
        output_path (Path): Path where to save the HTML report.
        datasets (dict): Dictionary containing the datasets generated during the mapping process.
    """
    try:
        env = Environment(loader=FileSystemLoader(str(Path(__file__).parent / "templates")))
        env.filters["comma"] = lambda x: f"{x:,}" if isinstance(x, (int, float)) else x
        template = env.get_template("mapping_report.html.j2")
    except Exception as e:
        logger.error(f"Error loading Report template: {e}")
        raise RuntimeError(f"Error loading Report template: {e}")

    context = get_stats(datasets)
    context.update(
        {
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "version": VERSION,
        }
    )
    context.update(kwargs)

    logger.debug("Rendering HTML report...")
    html_content = template.render(**context)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")

    logger.info(
        f"HTML report successfully written to {output_path}.", extra={"cli_msg": f" 📝 Report saved to {output_path}"}
    )

    return output_path
