# Methodology
This document describes the workflow used by the `iris-oc-mapper` tool to search and match IRIS records against the OpenCitations Meta and Index datasets.

## Mapping Workflow
The workflow described below is meant to be applied independently to a single IRIS data dump, resulting in separate output datasets for each IRIS instance. References to IRIS is to be understood as referring to an individual IRIS data dump.

### 1. IRIS Data Extraction and PID Identification
Records are extracted from the `ODS_L1_IR_ITEM_MASTER_ALL` and `ODS_L1_IR_ITEM_IDENTIFIER` tables of IRIS and merged via a left join on the `ITEM_ID` field. Records with invalid identifiers (non-numeric, null or having duplicate `ITEM_ID`s) are discarded.
From this resulting master table, the first output dataset is obtained, _IRIS No PIDs_, comprising all IRIS records that do not have any of the persistent identifiers shared between IRIS and OC Meta, namely DOI, PMID, and ISBN, and therefore fall outside of the scope of the mapping workflow here described.

All remaining records, containing at least one DOI, PMID, or ISBN, are processed to construct a list of validated PIDs to be searched within OC Meta.
Identifiers are extracted from the `IDE_DOI`, `IDE_PMID`, and `IDE_ISBN` fields of the master table using regular expressions tailored to each PID type, followed by normalization and validation steps aimed at ensuring their correctness. Prior to the extraction step, all leading and trailing whitespace characters are removed from the identifier strings.

- **DOIs** are extracted using the regular expression `(10\.\d{4,}\/[^,\s;]*)`.

- **PMIDs** are extracted using `^(?:PMID:?\s*)?(0*[1-9][0-9]{0,8})[^\d]?$`, with leading zeroes removed after the extraction.

- **ISBNs** are identified using `(?:ISBN[-]*(?:1[03])?[ ]*(?:: )?)?(([0-9Xx][-. ]*){13}|([0-9Xx][-. ]*){10})`, and normalised by removing hyphens, dots, and whitespaces.

To further prevent false positive matches, ISBN identifiers are subject to an additional validation step based on the publication type of the corresponding IRIS record. ISBN identifiers are considered valid only for records associated with a predefined subset of MIUR publication types deemed compatible with ISBN assignment. The identified publication types are the following:

- Monografia o trattato scientifico (Monograph or scientific treatise)
- Concordanza (Concordance)
- Edizione critica di testi / di scavo (Critical edition)
- Pubblicazione di fonti inedite (Publication of unpublished sources)
- Commento scientifico (Scholarly commentary)
- Traduzione di libro (Book translation)
- Curatela (Editorship)

This restriction is particularly important because ISBNs typically identify container entities (e.g. monographs or edited volumes). Individual chapters or contributions (often not being assigned their own identifiers) may be submitted to the institution repositories with the ISBN of their container entity, resulting in these constituent parts often being represented by the ISBN of the container instead.

All validated identifiers are finally formatted to comply with the OC Meta syntax, using the normalized form `prefix:identifier` (e.g., doi:10.1234/abcd, pmid:12345678, isbn:9781234567890), with the entire string converted to lowercase.

### 2. Search in OpenCitations Meta
The three tables containing the extracted DOIs, PMIDs, and ISBNs are concatenated into a single table with schema `(iris_id, pid_type, pid)` and matched against the OC Meta data dump.
Each CSV file in the OC Meta archive is processed sequentially, extracting from the `id` field string: 
- the OC Meta identifier (OMID), using the regular expression `(omid:[^\s]+)`
- all associated DOIs, PMIDs, or ISBNs using `((?:doi|pmid|isbn):[^\s\"]+)`

Only rows containing at least one DOI, PMID, or ISBN are retained. These rows are then expanded into a long format, in which for each OMID, each associated PID is represented in a separate `(omid, pid)` record.
An inner join is then performed between this expanded OC Meta PID table and the IRIS PID table on the pid value, yielding `(iris_id, omid, pid)` records whose PIDs are shared between OC Meta and the list of PIDs extracted from IRIS.
The matched records is translated back into a wide representation, with one row per IRIS record and separate columns for each PID type. This transformation merges cases in which a single IRIS record found matches in OC Meta through different PIDs. For IRIS records that found a match with multiple PIDs of the same type, these identifiers are concatenated into a whitespace-separated string in the corresponding PID column.

To ensure temporal consistency across datasets, a publication-year cutoff is applied, retaining only records published in or before 2024. The publication year is extracted from the pub_date field using the regular expression (\d{4}). When pub_date is missing, the publication year recorded in the IRIS dataset is used as a fallback. Records dated after 2024 are discarded.

### 3. Search in OpenCitations Index
From the preliminary IRIS in OC Meta dataset, all associated OMIDs are extracte and searched for within the OC Index archive. Each OC Index file is scanned to identify citation records in which either the `citing` or `cited` field contains an OMID from the extracted list. The resulting matches are deduplicated by selecting a single occurrence per OC Index citation identifier.
A temporal cutoff at 2024 is also applied to the citation records, based on the year extracted from the creation field to ensure temporal consistency between the Meta and Index datasets.
This remaining set of citation records constitutes the _IRIS in OC Index_ dataset.

### 4. Deduplication
After constructing the IRIS in OC Index dataset, the _IRIS in OC Meta_ can be finalized by applying a deduplication step to address duplicated records originating upstream in OC Meta. Because of these duplicates, the same PID can appear in OC Meta linked to multiple OMIDs, resulting in multiple matched entities for a single IRIS record.
Records sharing the same `iris_id` are deduplicated by selecting the entry with the most complete publication date, defined as the date with the highest level of granularity (i.e., year–month preferred over year-only). When this is insufficient to deduplicate to a single entity (e.g. when multiple duplicates shared the same level of date granularity) the remaining candidates are ordered by OMID in descending order, and the first entry in the ordered sequence is selected.

This deduplication step is intentionally applied after querying OC Index, because Index contains citation records referencing every entity present in OC Meta. Using the pre-deduplicated set of OMIDs ensures that the matching process also accounts for duplicated OC Meta entities, preserving complete coverage during the citation mapping.
The last output dataset, _IRIS Not in OC Meta_, is obtained by performing an anti-join between the full IRIS master table and the final deduplicated IRIS in OC Meta table. This dataset captures all IRIS records for which no corresponding entity was found in OC Meta through any PID type.