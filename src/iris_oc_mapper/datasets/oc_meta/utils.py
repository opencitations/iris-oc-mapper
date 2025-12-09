import logging
from pathlib import Path

import polars as pl

from iris_oc_mapper.datasets.iris.dataset import IRISDataset

from .dataset import IRISInOCMetaDataset, IRISNotInMetaDataset, OCMetaDataset

logger = logging.getLogger(__name__)


def load_oc_meta_dataset(path: str | Path) -> OCMetaDataset:
    """Load an OC Meta data dump.

    Args:
        path (str | Path): Path to the OC Meta dataset, either a ZIP file or a directory containing the OC Meta CSV files.

    Returns:
        OCMetaDataset: Initialized dataset instance.
    """

    return OCMetaDataset(path)


def flatten_matches(df: pl.DataFrame) -> pl.DataFrame:
    """Flatten *Iris in OC Meta* matches' DataFrame.

    This expands the DataFrame containing the matches by pivoting on PID type,
    crating separate columns for each identifier type (DOI, PMID, ISBN) which get populated
    if a match contains that PID type.

    Args:
        df (pl.DataFrame): DataFrame containing OC Meta matches.

    Returns:
        pl.DataFrame: Flattened DataFrame with separate columns for each identifier type.
    """
    # TODO: add way to check if all pids columns get extracted before doing direct operations on them (line 58)
    df_pivoted = df.with_columns(pl.col("pid").str.extract(r"^(doi|pmid|isbn|omid)").alias("pid_type")).pivot(
        on="pid_type",
        index=df.columns,
        values="pid",
        aggregate_function=pl.element().str.join(" "),
    )

    for col in ["doi", "pmid", "isbn"]:
        if col not in df_pivoted.columns:
            df_pivoted = df_pivoted.with_columns(pl.lit(None).alias(col))

    flattened = (
        df_pivoted.group_by(["iris_id", "omid"], maintain_order=True)
        .agg(
            [
                pl.first("title"),
                pl.first("type"),
                pl.first("pub_date"),
                pl.first("iris_type"),
                pl.col(["doi", "pmid", "isbn"]).str.join(" "),
            ]
        )
        .with_columns(
            pl.col("doi").str.strip_chars().replace("", None),
            pl.col("pmid").str.strip_chars().replace("", None),
            pl.col("isbn").str.strip_chars().replace("", None),
        )
    )

    logger.debug(f"Flattened OC Meta matches from {df.height} to {flattened.height} items.")

    return flattened


def create_in_meta_dataset(
    oc_meta_dataset: OCMetaDataset,
    iris_dataset: IRISDataset,
    cutoff_year: int | None,
) -> IRISInOCMetaDataset:
    """Create the *IRIS in OC Meta* dataset.

    First searches for the OC Meta dump for records with PIDs matching those in the IRIS dataset.
    Then flattens the matches to handle matches with multiple PID types per record.
    Finally, applies an optional cutoff year to filter records published on or before that year.

    Args:
        oc_meta_dataset (OCMetaDataset): The OC Meta dataset instance.
        iris_dataset (IRISDataset): The IRIS dataset instance.
        cutoff_year (int | None): Optional cutoff year to filter records.

    Returns:
        IRISInOCMetaDataset: The *IRIS in OC Meta* dataset instance.
    """

    # for PMIDs, keep only the first match found in the string
    pid_list = iris_dataset.get_persistent_identifiers(
        dois_kwargs={"unique_per_record": True, "first_per_record": False},
        pmids_kwargs={"unique_per_record": True, "first_per_record": True},
        isbns_kwargs={"unique_per_record": True, "first_per_record": False},
    )

    try:
        # search the PIDs in OC Meta
        matches = oc_meta_dataset.search(pid_list)
    except KeyboardInterrupt:
        raise

    # replace type codes with full type names
    type_validation_column = iris_dataset.config.get("type_validation_column", "OWNING_COLLECTION")
    if type_validation_column == "MIUR_TYPE_CODE":
        type_dict = iris_dataset.config.get("miur_types", {})
    else:
        type_dict = iris_dataset.get_type_dict()
    matches = (
        matches.with_columns(pl.col(type_validation_column).replace_strict(type_dict).alias("iris_type"))
        .rename({"ITEM_ID": "iris_id"})
        .drop(["id", type_validation_column])
    )

    oc_meta_dataset.processor.reporting_stats["duplicate_pids"] = matches.filter(pl.col("pid").is_duplicated()).height

    # flatten (expand) matches to handle multiple PID types per record. This results in one column per PID type.
    flattened_matches = (
        flatten_matches(matches)
        .select(
            [
                "iris_id",
                "omid",
                "title",
                "pub_date",
                "type",
                "iris_type",
                "doi",
                "pmid",
                "isbn",
            ]
        )
        .sort("omid")
    )

    # if provided, filter matches to retain only those published on or before cutoff_year
    if cutoff_year is not None and iris_dataset is not None:
        logger.info(
            f"Applying cutoff year: {cutoff_year}",
            extra={"cli_msg": f" ⏳ Applying cutoff year: {cutoff_year}..."},
        )
        flattened_matches = (
            flattened_matches.join(
                iris_dataset.get_publication_years(),
                left_on="iris_id",
                right_on="ITEM_ID",
                how="left",
            )
            .with_columns(
                pl.when(pl.col("pub_date").is_null())
                .then(pl.col("iris_pub_year"))
                .otherwise(pl.col("pub_date"))
                .alias("pub_date"),
            )
            .with_columns(
                pl.col("pub_date").str.extract(r"(\d{4})", 1).cast(pl.Int32, strict=False).alias("pub_year"),
            )
            .drop("iris_pub_year")
            .filter(pl.col("pub_year") <= cutoff_year)
            .drop("pub_year")
        )
        logger.debug(f"Filtered matches to {flattened_matches.height} rows after applying cutoff year.")

    return IRISInOCMetaDataset(
        data=flattened_matches,
        source=oc_meta_dataset.path.name,
        cutoff_year=cutoff_year,
    )


def create_not_in_meta_dataset(
    iris_dataset: IRISDataset,
    iris_in_meta_dataset: IRISInOCMetaDataset,
    output_format: str | None = None,
) -> IRISNotInMetaDataset:
    """Create IRIS not in OC Meta dataset.

    Anti-joins the IRIS dataset with the *IRIS in OC Meta* dataset to find records
    that were not matched in OC Meta.

    Args:
        iris_dataset (IRISDataset): The IRIS dataset instance.
        iris_in_meta_dataset (IRISInOCMetaDataset): The *IRIS in OC Meta* dataset instance.

    """
    not_in_meta_df = iris_dataset.df.join(iris_in_meta_dataset.df, left_on="ITEM_ID", right_on="iris_id", how="anti")

    return IRISNotInMetaDataset(data=not_in_meta_df, source=iris_dataset.source)
