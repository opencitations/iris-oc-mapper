from pathlib import Path

from iris_oc_mapper.datasets.iris import IRISDataset, IRISNoPIDDataset


def load_iris_dataset(path: str | Path) -> IRISDataset:
    """Load an IRIS dataset.

    Args:
        path (str | Path): Path to the IRIS dataset, either a ZIP file or a directory containing the IRIS CSV files.

    Returns:
        IRISDataset: Initialized dataset instance.
    """

    return IRISDataset(path)


def create_no_pid_dataset(
    iris_dataset: IRISDataset,
) -> IRISNoPIDDataset:
    """Create the *IRIS no PID* dataset."""
    no_pid_df = iris_dataset.get_no_pid()

    return IRISNoPIDDataset(data=no_pid_df, source=iris_dataset.source)
