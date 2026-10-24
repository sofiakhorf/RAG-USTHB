from pydantic import BaseModel, Field
from typing import Optional






class PipelineConfig(BaseModel):
    """Configuration globale du pipeline d'ingestion RAG."""
    libreoffice_path: str = "soffice"
    tesseract_lang: str = "fra"
    max_workers: int = Field(default=4, description="Nombre de processus parallèles")
    batch_size_excel: int = 15
    batch_size_examens: int = 8
    
    reset_ctx_per_page: bool = False




class ChunkMetadata(BaseModel):
    """Schéma strict des métadonnées injectées dans la base vectorielle."""
    document_name: str
    family_type: str
    procedure: Optional[str] = None
    formation: Optional[str] = None
    niveau: Optional[str] = None
    semestre: Optional[str] = None
    ue: Optional[str] = None
    matiere: Optional[str] = None
    annee_universitaire: Optional[str] = None
    page: Optional[int] = None
    #  champs spécifiques Excel
    sheet_name: Optional[str] = None     # Nom de la feuille Excel
    block_range: Optional[str] = None    # Plage de lignes (ex: "1-15")
    block_title: Optional[str] = None    # Titre ou bandeau du bloc
    is_fallback: bool = False

    class Config:
        extra = "allow"




class Chunk(BaseModel):
    """Contrat de données final pour le découpage RAG."""
    text: str
    metadata: ChunkMetadata

    @property
    def content(self) -> str:
        return self.text

