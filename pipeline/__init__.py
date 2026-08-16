"""
Initialisation du module Pipeline.
Expose les composants de routage et d'exécution par lot (batch).
"""

from pipeline.router import DocumentRouter
from pipeline.processor import BatchDocumentProcessor

__all__ = [
    "DocumentRouter",
    "BatchDocumentProcessor"
]