import logging
from pathlib import Path

import polars as pl

from iris_oc_mapper.configs import load_config
from iris_oc_mapper.datasets import IrisOCMapperDataset
from iris_oc_mapper.datasets.oc_index.processor import OCIndexProcessor
from iris_oc_mapper.datasets.oc_index.reader import OCIndexReader

logger = logging.getLogger(__name__)


class OCIndexDataset:
    """Interface for interacting with OC Index dumps.

    Provides methods for loading, filtering, and processing OC Index repository data
    from either ZIP archives or directory structures.

    Args:
        oc_index_path (str | Path): Path to the OC Index dataset, either a ZIP file or a directory containing the OC Index CSV files.
        config (dict | None, optional): Optional configuration dictionary. If None, defaults will be used.
    """

    def __init__(self, oc_index_path: str | Path, config: dict | None = None):
        self.path = Path(oc_index_path)
        self.config = config if config else load_config("oc_index")

        self.reader = OCIndexReader(self)
        self.processor = OCIndexProcessor(self)


class IRISInOCIndexDataset(IrisOCMapperDataset):
    """
    Dataset containing OC Index records that involve OMIDs from the *Iris in OC Meta* dataset.
    """

    def __init__(
        self,
        data: pl.DataFrame | None = None,
        path: str | None = None,
        source: str | None = None,
        cutoff_year: int | None = None,
    ):
        self.name = "IRIS in OC Index"
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
