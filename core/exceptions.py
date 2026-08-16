"""
Exceptions personnalisées pour le pipeline d'ingestion RAG USTHB.
"""

class RAGIngestionError(Exception):
    """Exception de base pour toutes les erreurs du système d'ingestion RAG."""
    pass

class RoutingError(RAGIngestionError):
    """Levée lorsqu'un document ne peut pas être classifié ou routé correctement."""
    pass

class ParsingError(RAGIngestionError):
    """Levée lorsqu'un parseur spécifique échoue à extraire le contenu d'un document."""
    pass

class OCRError(ParsingError):
    """Levée lorsque l'extraction textuelle par vision (Tesseract/OCR) échoue."""
    pass

class DependencyMissingError(RAGIngestionError):
    """Levée lorsqu'une dépendance système requise (ex: LibreOffice, Tesseract) est introuvable."""
    pass

class InvalidMetadataError(RAGIngestionError):
    """Levée lorsque les métadonnées extraites d'un document sont invalides ou corrompues."""
    pass