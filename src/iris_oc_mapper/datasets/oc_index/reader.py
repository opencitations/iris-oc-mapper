import logging
from pathlib import Path
from zipfile import ZipFile

logger = logging.getLogger(__name__)


class OCIndexReader:
    """Handles reading CSV files from OC Index dataset."""

    def __init__(self, dataset):
        self.oc_index_path = dataset.path
        self.config = dataset.config

        if self.oc_index_path.is_file() and self.oc_index_path.suffix == ".zip":
            self.unzip_oc_index(self.oc_index_path)

    def get_csv_archives(self) -> list[Path]:
        """Get list of CSV ZIP archives in the OC Index dataset unzipped directory.

        Returns:
            list[Path]: List of paths to CSV ZIP archives.
        """
        csv_archives = sorted(list(self.oc_index_path.glob("*.zip")))

        if not csv_archives:
            raise FileNotFoundError(
                f"No ZIP files found in '{self.oc_index_path}'. Please provide a valid path to the OC Index dataset."
            )

        logger.debug(f"Found {len(csv_archives)} ZIP archives in OC Index dataset at: {self.oc_index_path}")

        return csv_archives

    def unzip_oc_index(self, zip_path: Path):
        """Unzips OC Index's outer ZIP archive.

        This is needed because operating on a nested ZIP archive is computationally expensive
        (https://opencitations.hypotheses.org/2940).

        Args:
            zip_path (Path): Path to the OC Index ZIP archive.
        """
        unzipped_index_dirname = zip_path.with_suffix("")
        if not unzipped_index_dirname.exists():
            logger.info(
                "Unzipping OC Index dump archive: %s -> %s",
                zip_path,
                unzipped_index_dirname,
                extra={"cli_msg": " 📤 Unzipping OC Index dump archive..."},
            )
            with ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(unzipped_index_dirname)
