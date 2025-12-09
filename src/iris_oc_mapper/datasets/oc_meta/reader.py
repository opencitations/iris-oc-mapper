import logging
import tarfile

logger = logging.getLogger(__name__)


class OCMetaReader:
    """Handles reading CSV files from OC Meta dataset."""

    def __init__(self, dataset):
        self.oc_meta_path = dataset.path
        self.config = dataset.config

        if not self.oc_meta_path.exists():
            raise FileNotFoundError(
                f"Folder or file '{self.oc_meta_path}' does not exist. Please provide a valid path to the OC Meta dataset."
            )
        logger.debug(f"Loading OC Meta dataset from: {self.oc_meta_path}")

        if self.oc_meta_path.name.endswith(".tar.gz"):
            self.archive = tarfile.open(self.oc_meta_path, "r:gz")
        elif self.oc_meta_path.name.endswith(".zip"):
            raise NotImplementedError("ZIP format not supported yet.")
        elif self.oc_meta_path.is_dir():
            self.archive = None
            raise NotImplementedError("Reading from directory not supported yet.")
        else:
            raise ValueError("Dataset format not supported yet.")

    def iter_members(self, archive):
        for member in archive:
            if member.isfile() and member.name.endswith(".csv"):
                yield member
