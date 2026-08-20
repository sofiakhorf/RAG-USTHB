import argparse
import json
import logging
import sys
from pathlib import Path

from config import settings
from core import PipelineConfig
from pipeline import BatchDocumentProcessor
import parsers  # Déclenche l'enregistrement dynamique de tous les parseurs

# Configuration du logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("RAG_Main")

# Ajout des extensions Excel (.xlsx, .xls)
VALID_EXTENSIONS = {".pdf", ".docx", ".doc", ".jpg", ".jpeg", ".vsdx", ".drawio", ".png", ".xlsx", ".xls"}

def display_chunks_summary(chunks: list, full_text: bool = False):
    """Affiche un résumé propre des chunks dans le terminal."""
    print("\n" + "=" * 70)
    print(f" MÉTADONNÉES EXTRAITES ({len(chunks)} CHUNKS GÉNÉRÉS)")
    print("=" * 70)

    for i, chunk in enumerate(chunks, 1):
        meta = chunk.metadata
        print(f"\n[CHUNK {i}/{len(chunks)}]")
        print(f"  📄 Document          : {meta.document_name}")
        print(f"  🏷️  Famille           : {meta.family_type}")
        print(f"  🎓 Niveau            : {meta.niveau or 'N/A'}")
        print(f"  📚 Formation         : {meta.formation or 'N/A'}")
        print(f"  📖 Matière / UE      : {meta.matiere or 'N/A'} / {meta.ue or 'N/A'}")
        print(f"  📅 Année Univ.       : {meta.annee_universitaire or 'N/A'}")
        print(f"  📑 Page              : {meta.page if meta.page is not None else 'N/A'}")
        print(f"  ⚙️  Mode Fallback     : {meta.is_fallback}")
        
        # --- NOUVELLE LOGIQUE D'AFFICHAGE DU TEXTE ---
        if full_text:
            print("\n  📝 CONTENU TEXTUEL INTÉGRAL :")
            # On utilise un délimiteur clair pour séparer le texte des métadonnées
            print("  " + "-" * 66)
            # On indente légèrement le texte pour qu'il soit bien aligné
            for line in chunk.text.split('\n'):
                print(f"  | {line}")
            print("  " + "-" * 66)
        else:
            # Ancien comportement (résumé)
            print(f"  📝 Extrait de texte  : {chunk.text[:120].strip().replace(chr(10), ' ')}...")
        
        print("-" * 70)

def main():
    # 1. Arguments
    parser = argparse.ArgumentParser(description="Pipeline d'ingestion RAG USTHB")
    parser.add_argument("--input-dir", type=str, default="data", help="Dossier contenant les documents")
    parser.add_argument("--output-file", type=str, default="chunks_output.jsonl", help="Fichier JSONL de sortie")
    
    # --- NOUVEL ARGUMENT POUR LE DÉBOGAGE ---
    parser.add_argument("--full-text", action="store_true", help="Mode test : Affiche l'intégralité du texte extrait pour chaque chunk")
    
    parser.add_argument("--quiet", action="store_true", help="Désactive l'affichage détaillé dans la console")
    args = parser.parse_args()

    input_path = Path(args.input_dir)
    output_path = Path(args.output_file)
    
    # 2. Validation des entrées
    if not input_path.exists():
        logger.error(f"Le dossier '{input_path.resolve()}' n'existe pas.")
        sys.exit(1)

    # 3. Découverte des fichiers
    files = [str(f) for f in input_path.rglob("*") if f.is_file() and f.suffix.lower() in VALID_EXTENSIONS]

    if not files:
        logger.warning(f"Aucun fichier compatible trouvé dans : {input_path.resolve()}")
        sys.exit(0)

    logger.info(f"{len(files)} fichier(s) détecté(s). Démarrage du traitement...")

    # 4. Exécution du Pipeline (avec gestion d'erreurs)
    config = PipelineConfig()
    processor = BatchDocumentProcessor(config=config)
    
    try:
        chunks = processor.process_batch(files)
    except Exception as e:
        logger.error(f"Une erreur critique est survenue pendant le traitement batch : {e}", exc_info=True)
        sys.exit(1)

    # 5. Affichage optionnel (si pas en mode --quiet)
    if not args.quiet and chunks:
        # On passe le flag full_text à la fonction d'affichage
        display_chunks_summary(chunks, full_text=args.full_text)

    # 6. Exportation JSONL (Streaming pour optimiser la mémoire)
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            for chunk in chunks:
                chunk_json = json.dumps(chunk.model_dump(), ensure_ascii=False)
                f.write(chunk_json + "\n")
                
        logger.info(f"Succès ! {len(chunks)} chunks exportés (format JSONL) dans '{output_path.resolve()}'.")
    except IOError as e:
        logger.error(f"Impossible d'écrire le fichier de sortie '{output_path}' : {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()