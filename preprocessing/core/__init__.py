"""
Initialisation du noyau (Core) du système.
Expose les modèles de données, le registre des parseurs et les exceptions.
"""

import os
from pathlib import Path

# Auto-configure TESSDATA_PREFIX to local tessdata containing ara, fra, eng, osd
_local_tessdata = Path(__file__).resolve().parent.parent / "tessdata"
if _local_tessdata.exists():
    os.environ["TESSDATA_PREFIX"] = str(_local_tessdata)

from core.models import Chunk, ChunkMetadata, PipelineConfig
from core.registry import BaseFamilyParser, ParserRegistry
from core.exceptions import (
    RAGIngestionError,
    RoutingError,
    ParsingError,
    OCRError,
    DependencyMissingError,
    InvalidMetadataError
)

__all__ = [
    # Models
    "Chunk",
    "ChunkMetadata",
    "PipelineConfig",
    
    # Registry
    "BaseFamilyParser",
    "ParserRegistry",
    
    # Exceptions
    "RAGIngestionError",
    "RoutingError",
    "ParsingError",
    "OCRError",
    "DependencyMissingError",
    "InvalidMetadataError",
]