# Collectors package — one module per data source.
# Each collector implements BaseCollector and returns list[CollectedDocument].
from .cdc import CDCCollector
from .pubmed import PubMedCollector
from .who import WHOCollector

__all__ = ["PubMedCollector", "CDCCollector", "WHOCollector"]
