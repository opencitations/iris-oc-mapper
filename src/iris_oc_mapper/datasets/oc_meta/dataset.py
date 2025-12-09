import logging
from pathlib import Path

import polars as pl

from iris_oc_mapper.configs import load_config
from iris_oc_mapper.datasets import IrisOCMapperDataset
from iris_oc_mapper.datasets.oc_meta.processor import OCMetaProcessor
from iris_oc_mapper.datasets.oc_meta.reader import OCMetaReader

logger = logging.getLogger(__name__)


class OCMetaDataset:
    """Interface for interacting with OC Meta dumps.

    Provides methods for loading, filtering, and processing OC Meta repository data
    from either ZIP archives or directory structures.

    Args:
        oc_meta_path (str | Path): Path to the OC Meta dataset, either a ZIP file or a directory containing the OC Meta CSV files.
        config (dict | None, optional): Optional configuration dictionary. If None, defaults will be used.
    """

    def __init__(self, oc_meta_path: str | Path, config: dict | None = None):
        self.path = Path(oc_meta_path)
        self.config = config if config else load_config("oc_meta")

        self.reader = OCMetaReader(self)
        self.processor = OCMetaProcessor(self)

    def search(self, ids_df: pl.DataFrame) -> pl.DataFrame:
        """
        Map IRIS records into OC Meta using persistent identifiers.

        Args:
            ids_df (pl.DataFrame): DataFrame of PIDs to find within the OC Meta datadump.

        Returns:
            matches: A DataFrame of OC Meta records matching the provided PIDs.
        """
        try:
            matches = self.processor.search_for_ids(ids_df.lazy())
        except KeyboardInterrupt:
            raise

        return matches


class IRISInOCMetaDataset(IrisOCMapperDataset):
    """
    Dataset containing IRIS records that have a matching DOI, PMID or ISBN in the OC Meta dataset.
    """

    def __init__(
        self,
        data: pl.DataFrame | None = None,
        path: Path | str | None = None,
        source: str | None = None,
        cutoff_year: int | None = None,
    ):
        self.name = "IRIS in OC Meta"
        self.source = source
        self.path = Path(path) if path else None
        self.cutoff_year = cutoff_year

        if data is not None:
            self.df = data
        elif self.path is not None:
            self.df = self._load_df_from_path(self.path)
            self.source = self._load_metadata().get("source", "unknown")
            self.cutoff_year = self._load_metadata().get("cutoff_year", None)
        else:
            raise ValueError("Either 'data' or 'path' must be provided.")

    def get_omids_list(self) -> list[str]:
        """Return the list of OMIDs from the IRISInOCMeta dataset."""
        omids_list = self.df.get_column("omid").to_list()

        return omids_list

    def fix_oc_meta_duplicates(self) -> pl.DataFrame:
        """Fix duplicates coming from the OC Meta data.

        Returns:
            pl.DataFrame: Original IRISInOCMetaDataset with duplicate errors corrected.
        """

        logger.info("Fixing OC Meta duplicates...", extra={"cli_msg": " 🛠️  Fixing OC Meta duplicates..."})

        self.df = (
            self.df.sort(["iris_id", "pub_date"], descending=[False, True]).group_by(["iris_id"]).agg(pl.all().first())
        )

        return self.df


class IRISNotInMetaDataset(IrisOCMapperDataset):
    """Dataset containing IRIS records whose PIDs were not found in OC Meta."""

    def __init__(self, data, source):
        self.name = "IRIS Not In Meta"
        self.df = data
        self.source = source
