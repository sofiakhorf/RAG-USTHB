import hashlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Optional, Tuple, Dict

import pymupdf  # Remplacement de fitz

from core.models import PipelineConfig

logger = logging.getLogger(__name__)

# Extensions Word « binaires » que LibreOffice sait convertir en .docx.
LEGACY_WORD_EXTENSIONS = {".doc", ".dot", ".rtf"}

# Délai par défaut d'une conversion LibreOffice. Le premier lancement de
# soffice (création du profil utilisateur, chargement des filtres) prend
# couramment 10-30 s sur une machine à froid ; 30 s était trop court et
# provoquait des échecs silencieux sur les .doc (documents jamais ingérés).
DEFAULT_CONVERSION_TIMEOUT = 180

# Cache persistant des .docx convertis. Il est volontairement placé HORS de
# `data/` : convertir « sur place » créait un .docx à côté de chaque .doc,
# que le pipeline ré-ingérait ensuite comme un document supplémentaire
# (doublons de chunks) et qui polluait le dossier source.
_CACHE_DIR = Path(tempfile.gettempdir()) / "rag_usthb_docx_cache"

# Emplacements d'installation usuels de LibreOffice, utilisés quand le
# binaire n'est pas dans le PATH (cas fréquent sous Windows : le dossier
# `program` n'est pas ajouté au PATH par l'installateur).
_SOFFICE_FALLBACKS = (
    r"C:\Program Files\LibreOffice\program\soffice.com",
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.com",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/usr/bin/soffice",
    "/usr/local/bin/soffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
)


class SystemUtils:
    # =========================================================================
    # CONVERSION DES DOCUMENTS WORD HÉRITÉS (.doc / .dot / .rtf)
    # =========================================================================

    @staticmethod
    def _resolve_soffice(config: Optional[PipelineConfig] = None) -> Optional[str]:
        """
        Trouve un exécutable LibreOffice utilisable.

        Ordre de résolution :
          1. `config.libreoffice_path` s'il existe réellement sur la machine ;
          2. `soffice` dans le PATH (`shutil.which`) ;
          3. emplacements d'installation standard (Windows / Linux / macOS).

        Le défaut historique de configuration (`/usr/bin/soffice`) n'existe pas
        sous Windows : sans cette résolution, toutes les conversions .doc
        échouaient en silence sur les postes Windows.
        """
        candidates = []
        configured = (getattr(config, "libreoffice_path", None) or "").strip()
        if configured:
            candidates.append(configured)

        which = (
            shutil.which("soffice")
            or shutil.which("soffice.exe")
            or shutil.which("soffice.com")
            or shutil.which("libreoffice")
        )
        if which:
            candidates.append(which)

        candidates.extend(_SOFFICE_FALLBACKS)

        for candidate in candidates:
            if not candidate:
                continue
            # Un chemin absolu inexistant est ignoré ; un nom nu est résolu
            # par le système d'exploitation au moment de l'exécution.
            if os.path.isabs(candidate):
                if os.path.isfile(candidate):
                    return candidate
            else:
                found = shutil.which(candidate)
                if found:
                    return found
                if candidate in ("soffice", "libreoffice"):
                    # `shutil.which` peut échouer alors que l'exécution
                    # fonctionne (PATH exotique) : on laisse une chance.
                    return candidate
        return None

    @staticmethod
    def _cache_target(source: Path) -> Path:
        """Chemin de cache déterministe, dépendant du contenu source."""
        try:
            stat = source.stat()
            fingerprint = f"{source.resolve()}|{stat.st_mtime_ns}|{stat.st_size}"
        except OSError:
            fingerprint = str(source.resolve())
        digest = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:12]
        # Le .docx porte EXACTEMENT le radical du fichier source, dans un
        # sous-dossier propre à cette version : le routeur continue donc de
        # dériver le même titre qu'avec le fichier original (pas de suffixe
        # de hachage dans `document_name`).
        return _CACHE_DIR / digest / f"{source.stem}.docx"

    @staticmethod
    def _is_valid_docx(path: Path) -> bool:
        if not path.is_file() or path.stat().st_size < 1024:
            return False
        try:
            return zipfile.is_zipfile(path)
        except OSError:
            return False

    @staticmethod
    def convert_doc_to_docx(
        file_path: str,
        config: Optional[PipelineConfig] = None,
        timeout: int = DEFAULT_CONVERSION_TIMEOUT,
    ) -> str:
        """
        Convertit un .doc/.dot/.rtf en .docx et retourne le chemin du .docx.

        Le résultat est mis en cache (clé = chemin + mtime + taille) dans un
        dossier temporaire dédié, jamais dans le dossier source. Les fichiers
        déjà .docx sont retournés tels quels ; les autres extensions aussi
        (aucune conversion pertinente).
        """
        path = Path(file_path).resolve()

        if not path.exists():
            raise FileNotFoundError(f"Fichier introuvable : {path}")

        suffix = path.suffix.lower()
        if suffix == ".docx":
            return str(path)
        if suffix not in LEGACY_WORD_EXTENSIONS:
            return str(path)

        cached = SystemUtils._cache_target(path)
        if SystemUtils._is_valid_docx(cached):
            logger.debug("Conversion .doc en cache réutilisée : %s -> %s", path.name, cached)
            return str(cached)

        soffice = SystemUtils._resolve_soffice(config)
        if not soffice:
            raise RuntimeError(
                f"LibreOffice (soffice) introuvable : impossible de convertir {path}. "
                "Installez LibreOffice ou renseignez LIBREOFFICE_PATH."
            )

        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cached.parent.mkdir(parents=True, exist_ok=True)

        errors = []
        # Deux tentatives : le tout premier lancement de soffice peut échouer
        # ou dépasser le délai (initialisation du profil), une seconde
        # tentative avec un profil neuf passe généralement.
        for attempt in range(2):
            work_dir = Path(tempfile.mkdtemp(prefix="lo_convert_"))
            profile_dir = work_dir / "profile"
            out_dir = work_dir / "out"
            out_dir.mkdir(parents=True, exist_ok=True)
            profile_dir.mkdir(parents=True, exist_ok=True)

            cmd = [
                soffice,
                f"-env:UserInstallation={profile_dir.as_uri()}",
                "--headless",
                "--norestore",
                "--convert-to",
                "docx",
                str(path),
                "--outdir",
                str(out_dir),
            ]

            effective_timeout = timeout if attempt == 0 else int(timeout * 1.5)
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=effective_timeout,
                )
                produced = out_dir / f"{path.stem}.docx"
                if produced.exists() and SystemUtils._is_valid_docx(produced):
                    shutil.copy2(produced, cached)
                    logger.info("Conversion LibreOffice réussie : %s -> %s", path.name, cached.name)
                    return str(cached)
                errors.append(
                    f"code {result.returncode}, sortie absente ou invalide "
                    f"(stdout={result.stdout.strip()[:200]!r}, stderr={result.stderr.strip()[:200]!r})"
                )
            except subprocess.TimeoutExpired:
                errors.append(f"délai dépassé après {effective_timeout}s")
            except OSError as exc:
                errors.append(f"{type(exc).__name__}: {exc}")
            finally:
                shutil.rmtree(work_dir, ignore_errors=True)

        raise RuntimeError(
            f"Conversion LibreOffice de {path.name} échouée après 2 tentatives "
            f"({'; '.join(errors)})."
        )

    @staticmethod
    def check_pdf_fonts_and_info(file_path: str) -> Tuple[bool, str]:
        has_text = False
        creator_info = ""
        try:
            res_fonts = subprocess.run(["pdffonts", file_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
            has_text = len(res_fonts.stdout.strip().split("\n")) > 2
        except FileNotFoundError:
            # Remplacement de fitz.open par pymupdf.open
            with pymupdf.open(file_path) as d:
                has_text = any(len(page.get_fonts()) > 0 for page in d)

        try:
            res_info = subprocess.run(["pdfinfo", file_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
            for line in res_info.stdout.split("\n"):
                if line.lower().startswith("creator:"):
                    creator_info = line.split(":", 1)[1].strip()
        except FileNotFoundError:
            # Remplacement de fitz.open par pymupdf.open
            with pymupdf.open(file_path) as d:
                creator_info = d.metadata.get("creator", "")

        return has_text, creator_info

    @staticmethod
    def is_arabic_page(text: str, threshold: float = 0.5) -> bool:
        """
        Renvoie True SEULEMENT si plus de 50% des caractères de la page sont en arabe.
        """
        clean_text = re.sub(r'\s+', '', text)
        if not clean_text:
            return False

        # Compter les caractères appartenant au bloc Unicode Arabe
        arabic_chars = len(re.findall(r'[\u0600-\u06FF]', clean_text))

        # Calculer le ratio
        ratio = arabic_chars / len(clean_text)

        return ratio > threshold


class AcademicMetadataExtractor:
    @staticmethod
    def extract_from_text(text: str) -> Dict[str, Optional[str]]:
        meta = {
            "annee_universitaire": None,
            "niveau": None,
            "formation": None,
            "ue": None,
            "matiere": None
        }
        ay_match = re.search(r"(20\d{2}[-/_]20\d{2}|\b20\d{2}\b)", text)
        if ay_match:
            meta["annee_universitaire"] = ay_match.group(0)

        niv_match = re.search(r"\b(L[1-3]|M[1-2]|ING[1-5]|LICENCE\s*[1-3]|MASTER\s*[1-2])\b", text, re.IGNORECASE)
        if niv_match:
            meta["niveau"] = niv_match.group(0).upper()

        spec_match = re.search(r"\b(ISIL|BIGDATA|SSI|IL|IA|GTR|RSD|ACAD|BIOINFO)\b", text, re.IGNORECASE)
        if spec_match:
            meta["formation"] = spec_match.group(0).upper()

        return meta
