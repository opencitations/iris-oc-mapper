import logging
from pathlib import Path

import polars as pl

from iris_oc_mapper.configs import load_config
from iris_oc_mapper.datasets import IrisOCMapperDataset
from iris_oc_mapper.datasets.iris.exceptions import IRISDatasetError
from iris_oc_mapper.datasets.iris.processor import IRISProcessor
from iris_oc_mapper.datasets.iris.reader import IRISReader

logger = logging.getLogger(__name__)


class IRISDataset:
    """Interface for interacting with IRIS repository data.

    Provides methods to load, filter, and process records from
    IRIS data dumps (either as ZIP archives or extracted directories containing the IRIS CSV files).

    Args:
        path (str | Path): Path to the IRIS dataset, either a ZIP file or a directory containing the IRIS CSV files.
        config (dict | None, optional): Optional configuration dictionary. If None, defaults will be used.
    """

    def __init__(
        self,
        path: str | Path,
        config: dict | None = None,
    ):
        try:
            self.path = Path(path)
            if not self.path.exists():
                raise IRISDatasetError(f"IRIS path does not exist: {self.path}")
            self.source = self.path.name
            self.config = config if config else load_config("iris")
            self.reader = IRISReader(self)
            self.df = self.reader.read_core()
            self.processor = IRISProcessor(self)

        except Exception as e:
            raise IRISDatasetError(f"Failed to initialize IRISDataset: {e}") from e

    def read_csv_master(self) -> pl.DataFrame:
        """Return the IRIS `ODS_L1_IR_ITEM_MASTER_ALL.csv` file as a DataFrame."""
        return self.reader.read_master()

    def read_csv_identifier(self) -> pl.DataFrame:
        """Return the IRIS `ODS_L1_IR_ITEM_IDENTIFIER.csv` file as a DataFrame."""
        return self.reader.read_identifier()

    def read_core(self) -> pl.DataFrame:
        """Return the core IRIS DataFrame (MASTER + IDENTIFIER joined)."""
        return self.reader.read_core()

    def read_metadata(self) -> pl.DataFrame:
        """
        Return IRIS core records enriched with additional metadata.

        Joins the base dataset with metadata tables on ``ITEM_ID``.
        """
        df_extra = self.reader.get_metadata_df()
        if df_extra:  # type: ignore
            return self.df.join(df_extra, on="ITEM_ID", how="left")
        raise IRISDatasetError("No metadata tables found in the IRIS dataset.")

    def get_no_pid(self) -> pl.DataFrame:
        """
        Return a DataFrame containing rows from the IRIS dataset that do not have any DOI, PMID or ISBN persistent identifiers.
        """
        no_pid_df = self.df.filter(
            pl.col("IDE_DOI").is_null() & pl.col("IDE_ISBN").is_null() & pl.col("IDE_PMID").is_null()
        )
        return no_pid_df

    def get_publication_years(self) -> pl.DataFrame:
        """Return a DataFrame with ``ITEM_ID`` and ``PUBLICATION_YEAR`` columns."""
        return self.processor.get_publication_years()

    def get_dois(
        self,
        raw: bool = False,
        unique_per_record: bool = True,
        first_per_record: bool = False,
        invalid_only: bool = False,
        valid_types: set | None = None,
        type_validation_column: str = "OWNING_COLLECTION",
    ) -> pl.DataFrame:
        """
        Return records with valid DOIs.

        Args:
            raw (bool, default=False): Whether to return raw DOIs without processing and validating them.
            invalid_only (bool, default=False): If True, return only records with invalid DOIs
            valid_types (set | None, default=None): Optional set of valid OWNING_COLLECTION types for filtering.
            type_validation_column (str, default="OWNING_COLLECTION"): Column to use for type validation.

        Columns:
            Dataframe with columns:
            - ITEM_ID (i64): Unique record identifier.
            - {type_validation_column} (i64): Type of record.
            - DOI (str): Persistent identifier (DOI).
        """
        doi_pattern = r"(10\.\d{4,}\/[^,\s;]*)"

        return self.processor.extract_pids(
            "IDE_DOI",
            "doi",
            raw=raw,
            pattern=doi_pattern,
            unique_per_record=unique_per_record,
            first_per_record=first_per_record,
            invalid_only=invalid_only,
            type_validation_column=type_validation_column,
            valid_types=valid_types,
        )

    def get_pmids(
        self,
        raw: bool = False,
        unique_per_record: bool = True,
        first_per_record: bool = False,
        invalid_only: bool = False,
        valid_types: set | None = None,
        type_validation_column: str = "OWNING_COLLECTION",
    ) -> pl.DataFrame:
        """
        Return records with valid PMIDs.

        Args:
            raw (bool, default=False): Whether to return raw PMIDs without processing and validating them.
            invalid_only (bool, default=False): If True, return only records with invalid PMIDs
            valid_types (set | None, default=None): Optional set of valid OWNING_COLLECTION types for filtering.
            type_validation_column (str, default="OWNING_COLLECTION"): Column to use for type validation.

        Columns:
            Dataframe with columns:
            - ITEM_ID (i64): Unique record identifier.
            - {type_validation_column} (i64): Type of record.
            - PMID (str): Persistent identifier (PMID).
        """
        pmid_pattern = r"^(?:PMID:?\s*)?(0*[1-9][0-9]{0,8})[^\d]?$"

        return self.processor.extract_pids(
            "IDE_PMID",
            "pmid",
            raw=raw,
            pattern=pmid_pattern,
            unique_per_record=unique_per_record,
            first_per_record=first_per_record,
            invalid_only=invalid_only,
            type_validation_column=type_validation_column,
            valid_types=valid_types,
        )

    def get_isbns(
        self,
        raw: bool = False,
        unique_per_record: bool = True,
        first_per_record: bool = False,
        invalid_only: bool = False,
        type_validation_column: str = "OWNING_COLLECTION",
        valid_types: set | None = None,
    ) -> pl.DataFrame:
        """
        Return records with valid ISBNs.

        Args:
            raw (bool, default=False): Whether to return raw ISBNs without processing and validating them.
            unique_per_record (bool, default=True): Whether to remove duplicate identifiers from the same record.
            first_per_record: (bool, default=False): Keep only one ISBN per record.
            invalid_only (bool, default=False): If True, return only records with invalid ISBNs
            type_validation_column (str, default="OWNING_COLLECTION"): Column to use for type validation.
            valid_types (set | None, default=None): Optional set of valid OWNING_COLLECTION types for filtering.

        Columns:
            Dataframe with columns:
            - ITEM_ID (i64): Unique record identifier.
            - {type_validation_column} (i64): Type of record.
            - ISBN (str): Persistent identifier (ISBN).
        """
        isbn_pattern = r"(?:ISBN[-]*(?:1[03])?[ ]*(?:: )?)?(([0-9Xx][-. ]*){13}|([0-9Xx][-. ]*){10})"

        return self.processor.extract_pids(
            "IDE_ISBN",
            "isbn",
            raw=raw,
            unique_per_record=unique_per_record,
            pattern=isbn_pattern,
            first_per_record=first_per_record,
            invalid_only=invalid_only,
            type_validation_column=type_validation_column,
            valid_types=valid_types,
        )

    def get_persistent_identifiers(
        self,
        raw: bool = False,
        unique_per_record: bool = True,
        first_per_record: bool = False,
        type_validation_column: str | None = None,
        valid_isbns_types: set | None = None,
        valid_dois_types: set | None = None,
        valid_pmids_types: set | None = None,
        silent: bool = False,
        *,
        dois_kwargs: dict | None = None,
        pmids_kwargs: dict | None = None,
        isbns_kwargs: dict | None = None,
    ) -> pl.DataFrame:
        """
        Return a DataFrame containing the persistent identifiers (DOI, PMID, ISBN) extracted from the IRIS dataset.

        Args:
            raw (bool, default=False): Whether to return raw identifiers without processing and validating them.
            unique_per_record (bool, default=True): Whether to remove duplicate identifiers from the same record.
            first_per_record (bool, default=False): Keep only the first PID found per ITEM_ID.
            type_validation_column (str | None, default=None): Column to use for type validation. If None, defaults to config.
            valid_isbns_types (set | None, default=None): Optional set of valid TYPE codes for ISBNs.
            valid_dois_types (set | None, default=None): Optional set of valid TYPE codes for DOIs.
            valid_pmids_types (set | None, default=None): Optional set of valid TYPE codes for PMIDs.
            silent (bool, default=False): If True, suppress info logging.
            dois_kwargs (dict | None, default=None): Override keyword arguments for DOI extraction.
            pmids_kwargs (dict | None, default=None): Override keyword arguments for PMID extraction.
            isbns_kwargs (dict | None, default=None): Override keyword arguments for ISBN extraction.

        Returns:
            pl.DataFrame: A DataFrame with the extracted persistent identifiers, where each row represents a PID.
        """

        if type_validation_column is None:
            type_validation_column = self.config.get("type_validation_column", "OWNING_COLLECTION")

        if valid_isbns_types is None:
            valid_isbns_types = set(self.config.get("pid_type_validation", {}).get("isbn", {}).get("valid_types", []))

        base_args = dict(
            raw=raw,
            unique_per_record=unique_per_record,
            first_per_record=first_per_record,
            type_validation_column=type_validation_column,
        )

        dois_args = {**base_args, "valid_types": valid_dois_types, **(dois_kwargs or {})}

        pmids_args = {**base_args, "valid_types": valid_pmids_types, **(pmids_kwargs or {})}

        isbns_args = {**base_args, "valid_types": valid_isbns_types, **(isbns_kwargs or {})}

        pids = pl.concat(
            [
                self.get_dois(**dois_args).rename({"DOI": "PID"}),
                self.get_pmids(**pmids_args).rename({"PMID": "PID"}),
                self.get_isbns(**isbns_args).rename({"ISBN": "PID"}),
            ]
        )

        if not silent:
            logger.info(
                f"Final PID list contains {pids.height} PIDs.",
                extra={"cli_msg": f" 📊 Extracted {pids.height} PIDs from valid records in IRIS."},
            )

        self.processor.reporting_stats["valid_pids"] = pids.height

        return pids

    def get_type_dict(self) -> dict:
        """
        Return a mapping from ``OWNING_COLLECTION`` codes to descriptions.
        """
        return dict(
            self.df[["OWNING_COLLECTION", "OWNING_COLLECTION_DES"]]
            .drop_nulls("OWNING_COLLECTION")
            .unique("OWNING_COLLECTION")
            .sort("OWNING_COLLECTION")
            .iter_rows()
        )


class IRISNoPIDDataset(IrisOCMapperDataset):
    """
    Dataset containing IRIS records without any DOI, PMID or ISBN persistent identifiers.
    """

    def __init__(self, data, source):
        self.name = "IRIS No PID"
        self.source = source
        self.df = data
