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

# Familles pris en charge pour les étudiants
FAMILIES_TO_PROCESS = ["A", "B", "C-D", "E", "G", "H"]

# Ajout des extensions Excel (.xlsx, .xls)
VALID_EXTENSIONS = {".pdf", ".docx", ".doc", ".jpg", ".jpeg", ".vsdx", ".drawio", ".png", ".xlsx", ".xls"}


def get_family_input_dirs(base_input_dir: Path):
    """Retourne les dossiers de données par famille dans le format data/famille XXX."""
    family_dirs = []
    for family in FAMILIES_TO_PROCESS:
        family_dir = base_input_dir / f"famille {family}"
        if family_dir.exists() and family_dir.is_dir():
            family_dirs.append((family, family_dir))
        else:
            logger.warning(f"Dossier introuvable pour la famille {family}: {family_dir}")
    return family_dirs

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
    parser.add_argument("--input-dir", type=str, default="data", help="Dossier racine contenant les dossiers data/famille XXX")
    parser.add_argument("--output-dir", type=str, default="Chunks_family", help="Dossier principal de sortie des chunks par famille")

    # --- NOUVEL ARGUMENT POUR LE DÉBOGAGE ---
    parser.add_argument("--full-text", action="store_true", help="Mode test : Affiche l'intégralité du texte extrait pour chaque chunk")

    parser.add_argument("--quiet", action="store_true", help="Désactive l'affichage détaillé dans la console")
    args = parser.parse_args()

    input_path = Path(args.input_dir)
    output_root = Path(args.output_dir)

    # 2. Validation des entrées
    if not input_path.exists():
        logger.error(f"Le dossier '{input_path.resolve()}' n'existe pas.")
        sys.exit(1)

    family_dirs = get_family_input_dirs(input_path)
    if not family_dirs:
        logger.warning(f"Aucune famille disponible dans : {input_path.resolve()} (recherche des dossiers 'famille A', 'famille B', 'famille C-D', 'famille E', 'famille G', 'famille H')")
        sys.exit(0)

    output_root.mkdir(parents=True, exist_ok=True)

    for family, family_dir in family_dirs:
        files = [str(f) for f in family_dir.rglob("*") if f.is_file() and f.suffix.lower() in VALID_EXTENSIONS]

        if not files:
            logger.warning(f"Aucun fichier compatible trouvé dans : {family_dir.resolve()}")
            continue

        logger.info(f"{family} : {len(files)} fichier(s) détecté(s). Démarrage du traitement...")

        # 4. Exécution du Pipeline (avec gestion d'erreurs)
        config = PipelineConfig(max_workers=settings.MAX_WORKERS)
        processor = BatchDocumentProcessor(config=config)

        try:
            chunks = processor.process_batch(files)
        except Exception as e:
            logger.error(f"Une erreur critique est survenue pendant le traitement batch pour la famille {family} : {e}", exc_info=True)
            continue

        # 5. Affichage optionnel (si pas en mode --quiet)
        if not args.quiet and chunks:
            display_chunks_summary(chunks, full_text=args.full_text)

        output_file = output_root / f"chunks_family_{family}.jsonl"

        # 6. Exportation JSONL (Streaming pour optimiser la mémoire)
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                for chunk in chunks:
                    chunk_json = json.dumps(chunk.model_dump(), ensure_ascii=False)
                    f.write(chunk_json + "\n")

            logger.info(f"Succès ! {len(chunks)} chunks exportés pour la famille {family} dans '{output_file.resolve()}'.")
        except IOError as e:
            logger.error(f"Impossible d'écrire le fichier de sortie '{output_file}' : {e}")
            continue

if __name__ == "__main__":
    main()