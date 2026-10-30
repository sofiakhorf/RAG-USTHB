import os
import logging
from typing import List, Optional
from concurrent.futures import ProcessPoolExecutor, as_completed

from core import PipelineConfig, Chunk, ParserRegistry
from pipeline.router import DocumentRouter
from parsers import FallbackParser

logger = logging.getLogger(__name__)


class BatchDocumentProcessor:
    """Moteur haut niveau permettant d'ingérer tout un dossier de documents en parallèle."""
    
    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()
       
    def process_batch(self, file_paths: List[str]) -> List[Chunk]:
        all_chunks: List[Chunk] = []
        
        logger.info(f"Démarrage du traitement parallèle de {len(file_paths)} fichiers avec {self.config.max_workers} workers.")
        
        with ProcessPoolExecutor(max_workers=self.config.max_workers) as executor:
            future_to_file = {
                executor.submit(_process_single_document_worker, path, self.config): path 
                for path in file_paths
            }
            
            for future in as_completed(future_to_file):
                path = future_to_file[future]
                try:
                    chunks = future.result()
                    all_chunks.extend(chunks)
                    logger.info(f"✓ Succès: {os.path.basename(path)} -> {len(chunks)} chunks générés.")
                except Exception as exc:
                    logger.critical(f"✗ Échec critique non géré pour {path}: {exc}")

        return all_chunks


def _process_single_document_worker(file_path: str, config: PipelineConfig) -> List[Chunk]:
    """Worker autonome exécuté au sein du ProcessPoolExecutor."""
    
    # Initialisation par défaut pour garantir que le FallbackParser 
    # aura des valeurs valides même si le routeur crashe.
    family = "UNKNOWN"
    effective_title = None
    effective_start_line = 0
    
    try:
        # 1. Déballage du tuple à 4 éléments renvoyé par classify_document
        family, prepared_path, effective_title, effective_start_line = DocumentRouter.classify_document(file_path, config)
        
        # 2. Récupération et exécution du parseur métier
        parser = ParserRegistry.get_parser(family, config)
        
        return parser.parse(
            prepared_path, 
            document_title=effective_title, 
            effective_start_line=effective_start_line
        )

    except Exception as e:
        logger.error(f"Erreur durant le parsing de {file_path}: {e}")
        
        # 3. Appel du FallbackParser avec la famille trouvée (ou "UNKNOWN") et le titre effectif
        return FallbackParser.parse_safe(
            file_path=file_path, 
            family=family, 
            document_title=effective_title
        )