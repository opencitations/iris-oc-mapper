import logging
from os import makedirs
from os.path import exists

import pandera.polars as pa
import polars as pl
from pandera.typing.polars import Series

from iris_oc_mapper.utils import setup_logging

setup_logging()


class IRISConverter(object):
    __PERSON = "ODS_L1_IR_ITEM_CON_PERSON"
    __DESCRIPTION = "ODS_L1_IR_ITEM_DESCRIPTION"
    __IDENTIFIER = "ODS_L1_IR_ITEM_IDENTIFIER"
    __LANGUAGE = "ODS_L1_IR_ITEM_LANGUAGE"
    __MASTER_ALL = "ODS_L1_IR_ITEM_MASTER_ALL"
    __PUBLISHER = "ODS_L1_IR_ITEM_PUBLISHER"
    __RELATION = "ODS_L1_IR_ITEM_RELATION"
    __TYPE = "ODS_L1_IR_ITEM_TYPE"
    __l = logging.getLogger(__name__)

    def __init__(
        self,
        folder_path,
        separator,
        encoding,
        extension,
        destination_path,
        use_item_types=False,
        miur_map_file=None,
        config=None,
    ):
        self.__l.info("Create the handler initialise all the paths and checking their existence")
        self.folder_path = folder_path
        self.person_path = self.__init_path(folder_path / (self.__PERSON + "." + extension))
        self.description_path = self.__init_path(folder_path / (self.__DESCRIPTION + "." + extension))
        self.identifier_path = self.__init_path(folder_path / (self.__IDENTIFIER + "." + extension))
        self.language_path = self.__init_path(folder_path / (self.__LANGUAGE + "." + extension))
        self.master_path = self.__init_path(folder_path / (self.__MASTER_ALL + "." + extension))
        self.publisher_path = self.__init_path(folder_path / (self.__PUBLISHER + "." + extension))
        self.relation_path = self.__init_path(folder_path / (self.__RELATION + "." + extension))
        self.types_path = None
        self.miur_map = self.__load_miur_map(miur_map_file)
        self.config = config if config is not None else {}
        if use_item_types:
            self.types_path = self.__init_path(folder_path / (self.__TYPE + "." + extension))

        self.sep = separator
        self.encoding = encoding
        self.dest = destination_path

    def __init_path(self, path):
        if not exists(path):
            self.__l.warning(
                "The file at the path '%s' does not exist. "
                "Consequently, no information will be used for this "
                "specific category." % path
            )
            return None
        else:
            return path

    def __load_miur_map(self, miur_map_file):
        if miur_map_file is None:
            return None

        if not exists(miur_map_file):
            self.__l.warning(
                "The MIUR map file at the path '%s' does not exist. "
                "Consequently, no MIUR mapping will be applied." % miur_map_file
            )
            return None

        self.__l.info("Loading MIUR map from '%s'" % miur_map_file)
        try:
            miur_map_df = pl.read_csv(miur_map_file, separator=",")
            return miur_map_df
        except Exception as e:
            self.__l.error("Failed to load MIUR map: %s" % str(e))
            return None

    def processData(self, path, columns, dest_file_name, store_in_file=True):
        """Process the data from the given path, selecting specified columns and optionally storing the result in a file.

        Args:
            path (Path): The path to the input data file.
            columns (list or None): The list of columns to select from the data. If None, all columns are selected.
            dest_file_name (str): The name of the destination file (without extension) to store the processed data.
            store_in_file (bool): Whether to store the processed data in a file.

        Returns:
            pl.DataFrame: The processed data frame.
        """
        self.__l.info("Processing file '%s'" % path)
        if path.suffix == ".csv":
            original = pl.read_csv(path, separator=self.sep, encoding=self.encoding, infer_schema_length=0, null_values=["null", "NULL", ""])
        elif path.suffix == ".xlsx":
            original = pl.read_excel(path, infer_schema_length=0)
        else:
            self.__l.warning(
                "The the file at the path '%s' cannot be processed "
                "because it is defined in a format that is not recognised." % path
            )
            raise ValueError("File format not recognised")

        if not exists(self.dest):
            makedirs(self.dest)

        if columns is None:
            result = original
        else:
            result = original.select(columns)

        if store_in_file:
            self.__l.info(
                f"Saving processed data to '{self.dest / (dest_file_name + '.csv')}'",
                extra={"cli_msg": f"Processed data saved to {dest_file_name}.csv"},
            )
            result.write_csv(self.dest / (dest_file_name + ".csv"))

        return result

    def processPerson(self):
        return self.processData(
            self.person_path,
            [
                "ITEM_ID",
                "RM_PERSON_ID",
                "PID",
                "ORCID",
                "FIRST_NAME",
                "LAST_NAME",
                "PLACE",
            ],
            self.__PERSON,
        )

    def processDescription(self):
        return self.processData(
            self.description_path,
            [
                "ITEM_ID",
                "DES_ALLPEOPLE",
                "DES_ALLPEOPLEORIGINAL",
                "DES_NUMBEROFAUTHORS",
                "DES_NUMBEROFAUTHORS_INT",
            ],
            self.__DESCRIPTION,
        )

    def processIdentifier(self):
        return self.processData(
            self.identifier_path,
            [
                "ITEM_ID",
                "IDE_DOI",
                "IDE_EISBN",
                "IDE_ISBN",
                "IDE_ISBN_1",
                "IDE_ISBN_2",
                "IDE_ISBN_3",
                "IDE_ISMN",
                "IDE_OTHER",
                "IDE_PATENTNO",
                "IDE_PATENTNOGR",
                "IDE_PATENTNOPB",
                "IDE_PMID",
                "IDE_SOURCE",
                "IDE_UGOV",
                "IDE_URL",
                "IDE_URL_1",
                "IDE_URL_2",
                "IDE_URL_3",
                "IDE_CITATION",
            ],
            self.__IDENTIFIER,
        )

    def processLanguage(self):
        return self.processData(self.language_path, None, self.__LANGUAGE)

    def processPublisher(self):
        return self.processData(
            self.publisher_path,
            ["ITEM_ID", "PUB_NAME", "PUB_PLACE", "PUB_COUNTRY", "PUB_COUNTRY_I18N"],
            self.__PUBLISHER,
        )

    def processRelation(self):
        return self.processData(self.relation_path, None, self.__RELATION)

    def __validate_miur_mapping(self, master_df, miur_map):
        class MiurTypes(pa.DataFrameModel):
            # IRIS_TYPE_NAME: Series[str] = pa.Field(isin=master_df["OWNING_COLLECTION_DES"].unique().to_list())
            MIUR_TYPE_NAME: Series[str] = pa.Field(isin=list(self.config.get("miur_types").values()))

        try:
            MiurTypes.validate(miur_map, lazy=True)
        except pa.errors.SchemaErrors as e:
            fc = e.failure_cases
            self.__l.error(f"{len(fc)} errors found in the MIUR mapping file provided: ")
            for case in fc.iter_rows():
                if case[2] == "MIUR_TYPE_NAME":
                    self.__l.error(f'⚠️  "{case[0]}" is not a valid MIUR type. (row {case})')
            raise ValueError("MIUR mapping validation failed. See errors above.")

    def _check_miur_types(self, df):
        iris_types = dict(
            df[["OWNING_COLLECTION", "OWNING_COLLECTION_DES"]]
            .drop_nulls("OWNING_COLLECTION")
            .unique("OWNING_COLLECTION")
            .sort("OWNING_COLLECTION")
            .iter_rows()
        )
        missing_types = set(iris_types.values()) - set(self.miur_map["IRIS_TYPE_NAME"].to_list())
        if missing_types:
            self.__l.warning(
                "The following IRIS type names are missing in the MIUR mapping file:\n"
                + "\n".join(f' - "{t}"' for t in missing_types)
            )

    def processMasterAll(self):
        columns = [
            "ITEM_ID",
            "DATE_ISSUED_YEAR",
            "TITLE",
            "OWNING_COLLECTION",
            "OWNING_COLLECTION_DES",
        ]

        df = self.processData(self.master_path, columns, self.__MASTER_ALL, store_in_file=False)

        if self.types_path is not None:
            item_types = self.processData(
                self.types_path,
                ["ITEM_ID", "TYPE_CONTRIBUTION", "TYPE_DCMI"],
                self.__TYPE,
                store_in_file=False,
            )

            df = df.join(item_types, left_on="ITEM_ID", right_on="ITEM_ID")

            df = df.with_columns(
                pl.concat_str(
                    [
                        pl.col("OWNING_COLLECTION_DES"),
                        pl.col("TYPE_CONTRIBUTION"),
                        pl.col("TYPE_DCMI"),
                    ],
                    separator="; ",
                    ignore_nulls=True,
                ).alias("OWNING_COLLECTION_DES")
            )

        if self.miur_map is not None:
            self.__validate_miur_mapping(df, self.miur_map)

            df = df.join(
                self.miur_map,
                left_on="OWNING_COLLECTION_DES",
                right_on="IRIS_TYPE_NAME",
                how="left",
            )

            if null_count := df.filter(
                pl.col("MIUR_TYPE_NAME").is_null() & pl.col("OWNING_COLLECTION_DES").is_not_null()
            ).height:
                self.__l.warning(
                    f"⚠️  {null_count} records did not have a corresponding MIUR mapping."
                    " You might want to check the IRIS type names in the MIUR mapping file for errors."
                )
                self._check_miur_types(df)
                self.__l.warning("Details of IRIS items missing MIUR mappings:")
                self.__l.warning(
                    "\n" +
                    "\n".join(
                        f"{item['OWNING_COLLECTION_DES']}: {item['missing_count']}" for item in
                        df.filter(pl.col("MIUR_TYPE_NAME").is_null() & pl.col("OWNING_COLLECTION_DES").is_not_null())
                        .group_by("OWNING_COLLECTION_DES")
                        .agg(pl.len().alias("missing_count")).to_dicts()
                    )
                )

        df.write_csv(self.dest / (self.__MASTER_ALL + ".csv"))

    def convertData(self):
        self.__l.info("Start the conversion process")
        for step in [
            self.processDescription,
            self.processIdentifier,
            self.processLanguage,
            self.processMasterAll,
            self.processPerson,
            self.processPublisher,
            self.processRelation
        ]:
            try:
                step()
            except Exception as e:
                self.__l.error(f"{step.__name__} Failed: {e}", exc_info=False)

        self.__l.info("End the conversion process")

