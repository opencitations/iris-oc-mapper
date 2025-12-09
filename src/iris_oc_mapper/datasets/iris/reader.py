import logging
from zipfile import ZipFile

import pandera.polars as pa
import polars as pl
from pandera.typing.polars import Series

from iris_oc_mapper.datasets.iris.exceptions import IRISDatasetError

logger = logging.getLogger(__name__)


class IRISIdentifierSchema(pa.DataFrameModel):
    ITEM_ID: Series[int] | None = pa.Field(unique=True, nullable=False, coerce=True)

    class Config:
        strict = False


class IRISReader:
    """
    Reader for IRIS data dumps.

    Handles loading core CSVs (MASTER and IDENTIFIER),
    validating schema, and joining with optional metadata tables.
    """

    def __init__(self, dataset):
        self.iris_path = dataset.path
        self.config = dataset.config
        self.reporting_stats = {}
        self._validate_dataset()

    def _validate_dataset(self):
        """Check dataset path and required files exist (MASTER + IDENTIFIER)."""
        if not self.iris_path.exists():
            raise FileNotFoundError(
                f"Folder or file '{self.iris_path}' does not exist.Please provide a valid path to an IRIS dataset."
            )

        required_files = [
            "ODS_L1_IR_ITEM_MASTER_ALL.csv",
            "ODS_L1_IR_ITEM_IDENTIFIER.csv",
        ]

        if self.iris_path.suffix == ".zip":
            with ZipFile(self.iris_path) as z:
                available_files = z.namelist()
        else:
            available_files = [f.name for f in self.iris_path.glob("*.csv")]

        missing = [f for f in required_files if f not in available_files]
        if missing:
            raise IRISDatasetError(f"Missing required files: {missing}")

        logger.debug(f"Loading IRIS dataset from: {self.iris_path}")

    def _read_csv(
        self,
        filename: str,
        columns: list[str] | str | None = None,
        dtypes: dict[str, pl.DataType] | None = None,
        **args,
    ) -> pl.DataFrame:
        """
        Internal CSV loader (works with plain dirs or ZIP archives).

        Args:
            filename: CSV file name.
            columns: Subset of columns to load (or "all" for full load).
            dtypes: Schema overrides for specific columns.
            ignore_errors: Whether to skip malformed rows.
        """
        if isinstance(columns, list):
            columns = ["ITEM_ID"] + columns
        elif columns.lower() == "all":  # type: ignore
            columns = None

        if self.iris_path.suffix == ".zip":
            with ZipFile(self.iris_path) as z, z.open(str(filename)) as f:
                return pl.read_csv(f, columns=columns, schema_overrides=dtypes, **args)
        else:
            return pl.read_csv(
                self.iris_path / filename,
                columns=columns,
                schema_overrides=dtypes,
                **args,
            )

    def _validate_identifier_schema(self, df: pl.DataFrame, filename: str) -> pl.DataFrame:
        """Validate ITEM_ID column in given DataFrame."""
        try:
            IRISIdentifierSchema.validate(df, lazy=True)
        except pa.errors.SchemaErrors as err:
            row_failures = err.failure_cases.filter(pl.col("index").is_not_null()).with_columns(
                pl.lit(filename).alias("source_file")
            )
            df = df.with_row_index().filter(~pl.col("index").is_in(err.failure_cases["index"].to_list())).drop("index")
            self.reporting_stats.setdefault("invalid_identifier_rows", []).extend(row_failures.to_dicts())
            logger.warning(
                f"Skipped {len(row_failures)} rows with invalid ITEM_ID from {filename}.",
                extra={
                    "cli_msg": f" ⚠️  Skipped {len(row_failures)} rows with invalid ITEM_ID from {filename}. Check the final report for details."
                },
            )
        return df.with_columns(pl.col("ITEM_ID").cast(pl.Int64))

    def read_master(self) -> pl.DataFrame:
        """Load the IRIS `ODS_L1_IR_ITEM_MASTER_ALL.csv` table, checking for invalid ITEM_IDs \
            and adding a `MIUR_TYPE_CODE` column containing the MIUR type codes."""
        filename = "ODS_L1_IR_ITEM_MASTER_ALL.csv"
        df = self._read_csv(
            filename,
            columns=self.config.get("core_columns", {}).get(filename),
        )

        df = self._validate_identifier_schema(df, filename)

        miur_dict = {v: k for k, v in self.config.get("miur_types", {}).items()}
        try:
            # TODO: convert to lowercase first??
            df = df.with_columns(
                pl.col("MIUR_TYPE_NAME").replace_strict(miur_dict, default=None).alias("MIUR_TYPE_CODE")
            )
        except pl.exceptions.ColumnNotFoundError:
            logger.error(f"MIUR_TYPE_NAME column not found in {filename}, cannot map MIUR types.")

        logger.debug(f"Loaded {filename} with {len(df)} rows after validation.")
        return df

    def read_identifier(self) -> pl.DataFrame:
        filename = "ODS_L1_IR_ITEM_IDENTIFIER.csv"

        df = self._read_csv(
            filename,
            columns=self.config.get("core_columns", {}).get(filename),
            infer_schema=False,
        )

        df = self._validate_identifier_schema(df, filename)

        logger.debug(f"Loaded {filename} with {len(df)} rows after validation.")
        return df

    def read_core(self) -> pl.DataFrame:
        """Return MASTER + IDENTIFIER joined on ITEM_ID."""
        df_master = self.read_master()
        df_identifier = self.read_identifier()
        df = df_master.join(df_identifier, on="ITEM_ID", how="inner")
        logger.debug(f"MASTER+ID merged IRIS dataset contains {len(df)} rows.")
        return df

    def get_metadata_df(self) -> pl.DataFrame | None:
        """
        Load optional metadata tables.
        """
        metadata_df = None
        metadata_columns = self.config.get("metadata_columns", {})
        for filename, cols in metadata_columns.items():
            try:
                df_extra = self._read_csv(filename, columns=cols, infer_schema=False)
                metadata_df = df_extra if metadata_df is None else metadata_df.join(df_extra, on="ITEM_ID", how="left")
            except (FileNotFoundError, KeyError):
                logger.warning(f"Metadata file {filename} not found in IRIS dataset, skipping.")
                continue

        if metadata_df:
            return metadata_df.with_columns(pl.col("ITEM_ID").cast(pl.Int64))
        else:
            return None
