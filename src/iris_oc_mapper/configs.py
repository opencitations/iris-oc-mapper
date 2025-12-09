from pathlib import Path
from typing import Dict, List, Union

import yaml  # type: ignore
from pydantic import BaseModel, Field


class IrisConfig(BaseModel):
    # Core data extraction
    core_columns: Dict[str, List[str] | str] = Field(
        default_factory=lambda: {  # type: ignore
            "ODS_L1_IR_ITEM_MASTER_ALL.csv": "ALL",
            "ODS_L1_IR_ITEM_IDENTIFIER.csv": ["IDE_DOI", "IDE_ISBN", "IDE_PMID"],
        }
    )

    # Metadata extraction
    metadata_columns: Dict[str, List[str] | str] = Field(
        default_factory=lambda: {  # type: ignore
            "ODS_L1_IR_ITEM_DESCRIPTION.csv": "ALL",
            "ODS_L1_IR_ITEM_PUBLISHER.csv": ["PUB_NAME", "PUB_PLACE", "PUB_COUNTRY"],
            "ODS_L1_IR_ITEM_LANGUAGE.csv": ["LAN_ISO"],
            "ODS_L1_IR_ITEM_RELATION.csv": ["REL_ISPARTOFBOOK", "REL_ISPARTOFJOURNAL"],
        }
    )

    # PID type validation
    type_validation_column: str = (
        "MIUR_TYPE_CODE"  # Column to use for type validation (OWNING_COLLECTION | MIUR_TYPE_CODE)
    )

    pid_type_validation: Dict[str, dict] = Field(
        default_factory=lambda: {"isbn": {"valid_types": [276, 277, 280, 281, 282, 283, 284]}}
    )

    miur_types: dict = {
        262: "Articolo in rivista",
        263: "Recensione in rivista",
        264: "Scheda bibliografica",
        265: "Nota a sentenza",
        266: "Abstract in rivista",
        267: "Traduzione in rivista",
        268: "Contributo in volume (Capitolo o Saggio)",
        269: "Prefazione/Postfazione",
        270: "Breve introduzione",
        271: "Voce (in dizionario o enciclopedia)",
        272: "Traduzione in volume",
        273: "Contributo in Atti di convegno",
        274: "Abstract in Atti di convegno",
        275: "Poster",
        276: "Monografia o trattato scientifico",
        277: "Concordanza",
        278: "Indice",
        279: "Bibliografia",
        280: "Edizione critica di testi/di scavo",
        281: "Pubblicazione di fonti inedite",
        282: "Commento scientifico",
        283: "Traduzione di libro",
        284: "Curatela",
        285: "Brevetto",
        286: "Composizione",
        287: "Disegno",
        288: "Design",
        289: "Performance",
        290: "Esposizione",
        291: "Mostra",
        292: "Manufatto",
        293: "Prototipo d'arte e relativi progetti",
        294: "Cartografia",
        295: "Banca dati",
        296: "Software",
        298: "Altro",
        301: "Recensione in volume",
        302: "Schede di catalogo/repertorio o corpus",
        1337: "Progetto Architettonico",
    }


class OCMetaConfig(BaseModel):
    n_files: int = 38601
    batch_size: int = 200


class OCIndexConfig(BaseModel):
    max_workers: int = 2


class IRISOCMapperConfig(BaseModel):
    iris: IrisConfig = IrisConfig()
    oc_meta: OCMetaConfig = OCMetaConfig()
    oc_index: OCIndexConfig = OCIndexConfig()

    @classmethod
    def from_yaml(cls, path: Union[str, Path]) -> "IRISOCMapperConfig":
        """
        Load configuration from a YAML file and merge it with defaults.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"Error parsing YAML file: {e}")

        return cls(**data)


def load_config(dataset: str | None = None) -> dict:
    config = IRISOCMapperConfig().model_dump()

    if dataset and dataset in config:
        return config[dataset]

    return config
