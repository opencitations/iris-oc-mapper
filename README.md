# iris-oc-mapper

A tool for mapping CINECA IRIS bibliographic records to [OpenCitations](https://opencitations.net/) Meta and Index datasets, with built-in utilities for interacting with IRIS data dumps.

## Description

`iris-oc-mapper` provides a command-line tool to search bibliographic entities from an IRIS (Institutional Research Information System) dump within OpenCitations Meta and Index data dumps. It also provides a high-level interface for interacting with IRIS data dumps.

It allows to:
* Convert IRIS dumps into structured and manageable CSV archives.
* Map IRIS records types to the types defined by MIUR.
* Analyze IRIS dumps to extract relevant bibliographic information.
* Map the coverage of IRIS dumps within the OpenCitations Meta and Index datasets.
* Create sub-datasets of IRIS dumps based on their mapping status (found in OC Meta, not found, found in OC Index, records without persistent identifiers).
* Generate reports summarizing the analysis and mapping results.

## Installation
#### From PyPI
```bash
pip install iris-oc-mapper
```

#### From Source

1. Clone this repository:

    ```bash
    git clone https://github.com/leonardozilli/iris-oc-mapper.git
    cd iris-oc-mapper
    ```

2. Install the package:
    ```bash
    pip install .
    ```

## Usage

`iris-oc-mapper` provides two main commands: `map` and `convert`. In order to `map` IRIS records, it is advised to first process the original IRIS dump using the `convert` command.

### 1. Process original IRIS dump
This step converts the original IRIS dump files into structured CSV files that can be used for mapping. It also allows to include subcategories from an optional `ITEM_TYPE` IRIS file into the main IRIS tables, as well as providing a way to map the IRIS internal record types to MIUR types.

```bash
iris-oc-mapper convert [OPTIONS]
```

#### Options

* `--path PATH`, `-p PATH`: Path of the folder containing original IRIS dump files.
* `--destination PATH`, `-d PATH`: Destination folder for converted CSV files.
* `--types`, `-t`: Include if `ITEM_TYPE` is present in the IRIS dump to concatenate subtypes to the main type.
* `--separator STRING`, `-s STRING`: Column separator in original files. Defaults to `,`.
* `--encoding STRING`, `-e STRING`: File encoding. Defaults to `utf-8`.
* `--format STRING`, `-f STRING`: Original dump file format (extension). Defaults to `csv`.
* `--miur-map PATH`, `-m PATH`: Path to the MIUR type mapping CSV file to map IRIS types to MIUR types. If not provided, no mapping is performed.

#### Example

```bash
iris-oc-mapper convert \
  --path data/original_iris \
  --destination data/iris_csv \
  --types \
  --separator "," \
  --encoding "utf-8"
  --miur-map resources/miur_type_mapping.csv
```

### 2. Map IRIS records to OpenCitations
Searches for IRIS bibliographic entries within the OpenCitations Meta and Index data dumps.

```bash
iris-oc-mapper map [OPTIONS]
```

#### Options

* `--iris PATH`, `-i PATH`: Path to the IRIS data dump folder or compressed archive.
* `--meta PATH`, `-m PATH`: Path to the OpenCitations Meta dump folder or compressed archive.
* `--index PATH`, `-x PATH`: Path to the OpenCitations Index dump folder or compressed archive.
* `--skip-index`, `-si`: Skip OC Index mapping.
* `--output PATH`, `-o PATH`: Output directory for results. Defaults to `results/`.
* `--output-format [csv|parquet]`, `-f FORMAT`: Format for output datasets. Defaults to `csv`.
* `--cutoff INTEGER`, `-c INTEGER`: Include only records published up to this year.
* `--generate-report`, `-r`: Generate an HTML mapping report. Defaults to `True`.
* `--save-datasets STRING`, `-s STRING`: Save final output datasets to disk. Use `"all"` to save all, or a comma-separated list: `"in_meta,no_id,not_in_meta,in_index"`.
* `--batch-size INTEGER`, `-b INTEGER`: Number of files per OC Meta batch. Defaults to 200.
* `--max-workers INTEGER`, `-w INTEGER`: Max parallel workers for OC Index processing. Defaults to 2.
* `--config PATH`, `-cf PATH`: YAML configuration file to override defaults.
* `--debug`, `-d`: Enable debug logging.

#### Example

```bash
iris-oc-mapper map \
  --iris data/iris.zip \
  --meta data/oc_meta.zip \
  --index data/oc_index.zip \
  --cutoff 2024 \
  -s "in_meta, in_index, not_in_meta, no_pid" \
  --output results/ \

```

### Configuration

#### Download OC Data Dumps
Download the most recent OpenCitations data dumps at:
*   [OpenCitations Meta Data Dump](https://doi.org/10.5281/zenodo.15625650)
*   [OpenCitations Index Data Dump](https://doi.org/10.6084/m9.figshare.24356626)

#### ISBN validation and MIUR Type Mapping
In order to prevent false positive matches during the mapping process, the tool validates PIDs against the record types of their corresponding IRIS entries. This is especially important for ISBNs, as they can often be incorrectly assigned to items that should not have them (e.g., journal articles).
By declaring a set of types that are legitimately allowed to contain ISBNs, the tool can avoid considering records with invalid ISBN assignments, and improve the mapping accuracy.

The set of record types specified in the default configuration of the tool consists of MIUR types, hence the need to map IRIS internal record types to MIUR categories in the preliminary conversion step.
The MIUR mapping has the advantage of providing a standardized set of categories that can be consistently applied across different IRIS instances, facilitating comparisons and analyses.

To create your own MIUR type mapping file, you can inspect the IRIS type labels and their descriptors directly from the IRIS dataset:
```python
from iris_oc_mapper.datasets.iris import load_iris_dataset
iris = load_iris_dataset('path_to_iris_dump')
type_dict = iris.get_type_dict()
print(type_dict)
```

The list of MIUR types considered valid for ISBN validation is specified in the YAML configuration file under the `miur_types` section.

When building your MIUR mapping CSV, ensure that all IRIS and MIUR type labels are written exactly as defined in their sources, preserving both case and spacing.

Use the resulting labels to construct the MIUR mapping CSV file, following the example provided in the `resources/` directory.

If you prefer not to use MIUR types for validation, you can disable MIUR-based checks by adjusting the YAML configuration. In particular:

* set `type_validation_column` to `OWNING_COLLECTION`, and

* define in `pid_type_validation` the IRIS type codes that are valid for each PID type you wish to validate.

Then pass your configuration file using the `--config` option when running the `map` command.


#### YAML Configuration File
A YAML configuration file can be provided to override default settings for the mapping process. This file can specify parameters such as valid PID types and batch sizes for processing.
An example configuration file is available in the `resources/` directory.

## Performance Considerations
Mapping large IRIS dumps against OpenCitations datasets can be resource-intensive.
For a full mapping, at least 5 GB of available RAM space is recommended. The full mapping process takes approximately 15 minutes to complete.

You can optimize resource usage by:
* Adjusting the `--batch-size` option to control the number of files processed in each batch during the OC Meta mapping.
* Using the `--max-workers` option to tame resource usage during the OC Index mapping process.

## License

This project is licensed under the MIT License. See the [`LICENSE`](LICENSE) file for details.

## Contacts and Acknowledgements

Project repository: [https://github.com/opencitations/iris-oc-mapper](https://github.com/opencitations/iris-oc-mapper)

For issues, discussions, or contributions, please open a GitHub issue, or contact:

- **Prof. Silvio Peroni** (supervision) – [@essepuntato](https://github.com/essepuntato) – silvio.peroni@unibo.it
- **Dr. Ivan Heibi** (supervision) – [@ivanhb](https://github.com/ivanhb) - ivan.heibi2@unibo.it
- **Leonardo Zilli** (software development) – [@leonardozilli](https://github.com/leonardozilli) – leonardo.zilli@studio.unibo.it
- **Erica Andreose** (core contributor) – [@EricaAndreose](https://github.com/EricaAndreose) – erica.andreose@studio.unibo.it


The authors would also like to express their gratitude to the collaborators and colleagues from the various universities and institutions who provided valuable feedback and support throughout the development of the project.


## Citation

```
tba
```
