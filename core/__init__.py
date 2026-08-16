"""
Initialisation du noyau (Core) du système.
Expose les modèles de données, le registre des parseurs et les exceptions.
"""

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