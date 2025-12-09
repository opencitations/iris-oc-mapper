import json
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from iris_oc_mapper import __version__


class IrisOCMapperDataset:
    """
    Base dataset class for IRIS <-> OpenCitations mapping datasets.
    """

    name: str
    source: str | None
    format: str | None
    df: pl.DataFrame
    path: Path | str | None

    @staticmethod
    def _load_df_from_path(path: Path) -> pl.DataFrame:
        """Load a Polars DataFrame from a CSV or Parquet file or directory."""
        if not path.exists():
            raise ValueError(f"Provided path does not exist: {path}")

        schema = {"creation": pl.String}

        if path.is_file():
            if path.suffix == ".parquet":
                return pl.read_parquet(path, schema=schema)
            elif path.suffix == ".csv":
                return pl.read_csv(path, schema_overrides=schema)
        elif path.is_dir():
            parquet_files = list(path.glob("*.parquet"))
            if parquet_files:
                return pl.read_parquet(path / "*.parquet", schema=schema)
            csv_files = list(path.glob("*.csv"))
            if csv_files:
                return pl.read_csv(path / "*.csv", schema_overrides=schema)
        raise ValueError(f"No supported data files found at: {path}")

    def _load_metadata(self) -> dict:
        """Load dataset metadata from metadata.json if available."""
        if self.path is None:
            return {}
        metadata_file = self.path / "metadata.json"  # type: ignore
        if not metadata_file.exists():
            return {}

        return json.loads(metadata_file.read_text(encoding="utf-8"))

    def save(
        self,
        output_dir: Path,
        output_format: str | None = "csv",
    ) -> None:
        """Save dataset to specified directory in given format (parquet or csv).

        Args:
            output_dir (Path): Directory where to save the dataset.
            output_format (str | None, optional): Output format, either 'parquet' or
                'csv'. Defaults to 'csv'.
        """
        if output_format not in ["parquet", "csv"]:
            raise ValueError(f"Unsupported format: {output_format}. Supported formats are 'parquet' and 'csv'.")
        self.format = output_format

        filename = self.name.replace(" ", "_").lower()
        dataset_dir = output_dir / filename
        dataset_dir.mkdir(parents=True, exist_ok=True)

        out_file = dataset_dir / f"{filename}.{output_format}"

        if self.format == "parquet":
            self.df.write_parquet(out_file)
        else:
            self.df.write_csv(out_file)

    def get_metadata(self, additional_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Generate metadata dictionary for the dataset."""
        metadata: dict[str, Any] = {
            "name": str(self.name) if self.name else "unknown",
            "description": str(self.__doc__).strip() if self.__doc__ else "No description available.",
            "source": str(self.source) if self.source else None,
            "created_at": datetime.now().isoformat() + "Z",
        }

        if hasattr(self, "cutoff_year"):
            metadata["cutoff_year"] = self.cutoff_year  # type: ignore

        metadata.update(
            {
                "format": self.format if hasattr(self, "format") else "unknown",
                "record_count": self.df.height,
                "columns": {name: str(dtype) for name, dtype in self.df.schema.items()},
                "iris-oc-mapper_version": __version__,
            }
        )

        if additional_metadata:
            metadata.update(additional_metadata)

        return metadata

    def save_metadata(self, output_dir: Path, additional_metadata: dict[str, Any] | None = None) -> Path:
        """Generate and save dataset metadata as JSON.

        Args:
            output_dir (Path): Directory where to save the metadata file.
            additional_metadata (dict[str, Any] | None, optional): Additional metadata to include.
        """
        filename = self.name.replace(" ", "_").lower()
        dataset_dir = output_dir / filename
        dataset_dir.mkdir(parents=True, exist_ok=True)

        metadata_file = dataset_dir / "metadata.json"
        metadata_file.write_text(
            json.dumps(self.get_metadata(additional_metadata), indent=4),
            encoding="utf-8",
        )
        return metadata_file


__all__ = ["IrisOCMapperDataset"]
