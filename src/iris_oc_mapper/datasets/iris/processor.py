import logging

import polars as pl

logger = logging.getLogger(__name__)


class IRISProcessor:
    """Handles data processing and identifier extraction for IRIS dataset."""

    def __init__(self, dataset):
        self.df = dataset.df
        self.config = dataset.config
        self.reader = dataset.reader
        self.reporting_stats = {}

    def extract_pids(
        self,
        column: str,
        prefix: str,
        raw: bool = False,
        pattern: str | None = None,
        unique_per_record: bool = True,
        first_per_record: bool = False,
        invalid_only: bool = False,
        type_validation_column: str = "OWNING_COLLECTION",
        valid_types: set | None = None,
    ) -> pl.DataFrame:
        """
        Extract and validate PIDs from a specific IRIS column.

        Args:
        column: Column name in self.df (e.g., 'IDE_DOI', 'IDE_PMID', 'IDE_ISBN').
        prefix: PID prefix for output (e.g., 'doi', 'pmid', 'isbn').
        raw: Whether to normalize and validate PIDs using the provided pattern.
        pattern: Optional regex pattern for validation/extraction.
        unique_per_record: Remove duplicate identifiers from the same record if True.
        first_per_record: Keep only the first PID found per ITEM_ID if True.
        invalid_only: If True, return only records with invalid PIDs.
        type_validation_column: Column to use for validation.
        valid_types: Optional set of valid OWNING_COLLECTION types for filtering.


        Returns:
        pl.DataFrame with columns: ITEM_ID, type_validation_column, PID
        """

        df_pid = self.df.select(["ITEM_ID", column, type_validation_column]).drop_nulls(column)

        if raw:
            # return raw PIDs without processing
            return df_pid.rename({column: column.replace("IDE_", "")})

        if pattern:
            # apply pattern validation/extraction
            if first_per_record:
                # get first match only
                logger.debug(f"Extracting first valid {prefix.upper()} per ITEM_ID using pattern.")
                df_pid = df_pid.with_columns(
                    (pl.col(column).str.strip_chars().str.extract(pattern).str.to_lowercase()).alias(f"extracted_{column}")
                )
            else:
                # get all matches in the string
                # + format them in prefix:pid format
                logger.debug(f"Extracting all valid {prefix.upper()}s per ITEM_ID using pattern.")
                df_pid = df_pid.with_columns(
                    pl.col(column).str.strip_chars().str.extract_all(pattern).alias(f"extracted_{column}")
                ).explode(f"extracted_{column}")

            if column == "IDE_ISBN":
                # normalize ISBNs by removing hyphens, dots, and spaces
                # + format them in prefix:pid format
                df_pid = df_pid.with_columns(pl.col(f"extracted_{column}").str.replace_all(r"[-. ]", ""))
            if column == "IDE_PMID":
                # remove leading zeros from PMIDs
                df_pid = df_pid.with_columns(
                    pl.col(f"extracted_{column}").str.strip_chars_start("0").alias(f"extracted_{column}")
                )

            df_pid = df_pid.with_columns(
                (prefix + ":" + pl.col(f"extracted_{column}").str.strip_chars().str.to_lowercase()).alias(
                    f"{column}_valid"
                )
            )
        else:
            logger.debug(f"Not applying any pattern validation for {prefix.upper()}.")
            df_pid = df_pid.with_columns((prefix + ":" + pl.col(column)).alias(f"{column}_valid"))

        self.reporting_stats[f"found_{prefix}s"] = df_pid.height

        invalid = df_pid.filter(pl.col(f"{column}_valid").is_null())
        self.reporting_stats[f"invalid_{prefix}s"] = invalid.height
        if invalid_only:
            logger.debug(f"Returning only invalid {prefix.upper()}s.")
            return df_pid.filter(pl.col(f"{column}_valid").is_null()).drop(f"{column}_valid")

        # keep only valid PIDs (so not null after validation)
        valid = (
            df_pid.filter(pl.col(f"{column}_valid").is_not_null())
            .drop(column)
            .rename({f"{column}_valid": prefix.upper()})
        )

        logger.debug(f"Found {df_pid.height - valid.height} invalid {prefix.upper()}s from IRIS dataset.")

        if unique_per_record:
            # remove pids that appear multiple times in the same IRIS record
            len_before = valid.height
            valid = valid.group_by(["ITEM_ID", type_validation_column, prefix.upper()]).agg(pl.all().first())
            if len_before - valid.height > 0:
                logger.debug(
                    f"Found {len_before - valid.height} duplicate {prefix.upper()}s appearing multiple times in the same IRIS record."
                )

        if valid_types:
            # remove pids with invalid types
            len_before = valid.height
            valid = valid.filter(pl.col(type_validation_column).is_in(valid_types))
            logger.debug(f"Found {len_before - valid.height} {prefix.upper()}s with misassigned types.")
            self.reporting_stats[f"misassigned_{prefix.lower()}s"] = len_before - valid.height

        self.reporting_stats[f"valid_{prefix}s"] = valid.height
        return valid.select(["ITEM_ID", type_validation_column, prefix.upper()])

    def get_publication_years(self) -> pl.DataFrame:
        """
        Returns a DataFrame with ITEM_ID and PUBLICATION_YEAR columns.
        """
        return self.df.select(
            pl.col("ITEM_ID"),
            pl.col("DATE_ISSUED_YEAR").cast(pl.Int32, strict=False).alias("iris_pub_year"),
        )
