import logging
from pathlib import Path

import polars as pl

from iris_oc_mapper.datasets.oc_meta.dataset import IRISInOCMetaDataset

from .dataset import IRISInOCIndexDataset, OCIndexDataset

logger = logging.getLogger(__name__)


def load_oc_index_dataset(path: str | Path) -> OCIndexDataset:
    """Load an OC Index data dump.

    Args:
        path (str | Path): Path to the OC Index dataset, either a ZIP file or a directory containing the OC Index CSV files.

    Returns:
        Initialized OCIndexDataset instance
    """

    return OCIndexDataset(path)


def create_in_index_dataset(
    oc_index_dataset: OCIndexDataset,
    iris_in_meta_dataset: IRISInOCMetaDataset,
    cutoff_year: int | None = None,
) -> IRISInOCIndexDataset:
    """Create the *IRIS in OC Index* dataset.

    Args:
        oc_index_dataset (OCIndexDataset): The OC Index dataset instance.
        iris_in_meta_dataset (IRISInOCMetaDataset): The *IRIS in OC Meta* dataset instance.
        cutoff_year (int | None): Optional cutoff year to filter records.

    Returns:
        IRISInOCIndexDataset: The *IRIS in OC Index* dataset instance.
    """
    # get the list of OMIDs from the IRIS in OC Meta dataset
    omids_list = iris_in_meta_dataset.get_omids_list()

    # search for OC Index records matching the OMIDs list
    matches = oc_index_dataset.processor.search_by_omid(omids_list)

    if matches is not None and not matches.is_empty():
        # Apply cutoff year if provided
        if cutoff_year is not None:
            logger.info(
                f"Applying cutoff year: {cutoff_year}",
                extra={"cli_msg": f" ⏳ Applying cutoff year: {cutoff_year}..."},
            )
            matches = (
                matches.filter(~pl.col("creation").is_null())
                .with_columns(
                    pl.col("creation").str.extract(r"(\d{4})", 1).cast(pl.Int32, strict=False).alias("citing_year")
                )
                .filter(pl.col("citing_year") <= cutoff_year)
            ).drop("citing_year")
            logger.debug(f"Filtered matches to {matches.height} rows after applying cutoff year.")

    return IRISInOCIndexDataset(data=matches, source=oc_index_dataset.path.name, cutoff_year=cutoff_year)
