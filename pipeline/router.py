import os
import re
import logging
from pathlib import Path
from typing import Tuple, Optional

import pymupdf
import openpyxl
from docx import Document

# --- Nouveaux imports simplifiés pour le core ---
from core import PipelineConfig
from core.utils import SystemUtils  # Ajout de l'import pour la conversion

logger = logging.getLogger(__name__)

class DocumentRouter:
    """
    Routeur de documents avancé pour le système RAG USTHB.
    Classifie les documents selon leur extension, structure, métadonnées
    et mots-clés extraits du titre ou du contenu.
    """

    # En-têtes institutionnels courants à ignorer lors de l'extraction du titre dans le contenu
    HEADER_PATTERNS = [
        # 1. État et Ministère (Dès qu'on voit République ou Ministère, on saute la ligne)
        r"r[eé]publique\s+alg[eé]rienne.*",
        r"minist[eè]re\s+(?:de\s+)?l['’`‘\s]*enseignement.*",
        
        # 2. Identifiants de l'Université (Gère USTHB, le nom complet, ou juste Houari Boumediene)
        r"universit[eé]\s+des\s+sciences.*",
        r"houari\s+boumediene.*",
        r"\busthb\b.*",
        
        # 3. Structures Administratives Hautes (Rectorat, Vice-rectorat, Sous-direction)
        # Rend le préfixe optionnel (ex: matche "Rectorat" tout court ou "Vice-rectorat")
        r"(?:vice[-\s]*)?rectorat.*",
        r"(?:sous[-\s]*)?direction.*",
        
        # 4. Structures Administratives Basses (Facultés, Instituts, Départements)
        # On attrape le mot clé, et on ignore la spécialité qui suit (ex: Département d'Informatique)
        r"facult[eé]\b.*",
        r"d[eé]partement\b.*",
        r"institut\b.*",
        
        # 5. Lignes orphelines fréquentes (Fragments de phrases coupées par des retours à la ligne)
        r"(?:post[-\s]*graduation|recherche\s+scientifique|habilitation\s+universitaire|relations\s+ext[eé]rieures).*",
        
        # 6. Séparateurs visuels étendus (Prend en compte les *, les -, les _ et les = utilisés comme lignes)
        r"[-_*=]{4,}",
        
        # 7. Métadonnées temporelles
        r"ann[eé]e\s+universitaire.*[\d]{4}.*",
    ]    
    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()

    @classmethod
    def classify_document(cls, file_path: str, config: Optional[PipelineConfig] = None) -> Tuple[str, str, str]:
        """
        Point d'entrée principal pour le classement.
        Retourne un tuple (family, prepared_path, effective_title).
        """
        router = cls(config=config)
        
        if file_path.lower().endswith(".doc"):
            logger.info(f"Fichier .doc détecté dans le routeur. Lancement de la conversion pour : {file_path}")
            try:
                file_path = SystemUtils.convert_doc_to_docx(file_path, router.config)
            except Exception as e:
                logger.error(f"Échec de la conversion du fichier {file_path} : {e}")

        family = router._determine_family(file_path)
        
        # --- AJOUT : Récupération du titre propre calculé ---
        effective_title = router._get_effective_name(file_path)
        
        prepared_path = str(Path(file_path).resolve())
        
        # Le tuple retourne maintenant 3 éléments
        return family, prepared_path, effective_title

    def _determine_family(self, file_path: str) -> str:
        """
        Détermine la famille du document en fonction des contraintes métier
        et du contenu du fichier.
        """
        file_path_obj = Path(file_path)
        ext = file_path_obj.suffix.lower()

        # 1. Règle absolue JPG -> Famille I
        if ext in [".jpg", ".jpeg"]:
            logger.info(f"[{file_path_obj.name}] Fichier image JPG détecté -> Famille I")
            return "I"

        # 2. Branchement direct Famille J par extensions vectorielles / diagrammes
        family_j_extensions = [".vsdx", ".vsd", ".drawio", ".svg", ".puml", ".plantuml"]
        if ext in family_j_extensions:
            logger.info(f"[{file_path_obj.name}] Extension de diagramme ({ext}) détectée -> Famille J")
            return "J"

        # 3. Extraction du nom effectif (depuis le chemin ou le contenu si opaque/long)
        effective_name = self._get_effective_name(file_path)
        effective_name_clean = effective_name.lower()

        # 4. Branchement Famille J par mots-clés (Organigrammes & Schémas vectoriels)
        family_j_keywords = [
            "organigramme", "organigrammes", "schéma", "schema", "schémas", "schemas",
            "diagramme", "diagramme de flux", "synoptique", "architecture système", "cartographie"
        ]
        if any(kw in effective_name_clean for kw in family_j_keywords):
            logger.info(f"[{effective_name}] Mots-clés de schéma/organigramme détectés -> Famille J")
            return "J"

        # 5. Règle Famille E (Plannings / Examens)
        family_e_keywords = [
            "base rattrapage", "publipostage", "base examen", "base examens",
            "planning examen", "planning examens", "examen", "examens"
        ]
        if any(kw in effective_name_clean for kw in family_e_keywords):
            logger.info(f"[{effective_name}] Mots-clés d'examens détectés -> Famille E")
            return "E"

        # 6. Récupération des infos PDF si applicable
        page_count = 0
        is_scanned_pdf = False
        if ext == ".pdf":
            page_count, is_scanned_pdf = self._analyze_pdf(file_path)

        # 7. Règle Famille B (Programmes / Syllabus / Canevas)
        family_b_keywords = ["canevas", "programmes modules", "programme module", "syllabus", "fiche de voeux", "fiche de vœux"]
        has_b_keyword = any(kw in effective_name_clean for kw in family_b_keywords)
        is_b_page_length = (4 <= page_count) if ext == ".pdf" else False

        if has_b_keyword and is_b_page_length:
            logger.info(f"[{effective_name}] Critères Famille B validés (Mots-clés: {has_b_keyword}, Pages: {page_count}) -> Famille B")
            return "B"

        # 8. Règle PDF OCR (Famille I ou Famille F pour les décrets)
        if ext == ".pdf" and is_scanned_pdf:
            if any(kw in effective_name_clean for kw in ["décret", "decret", "arrêté", "arrete", "journal officiel"]):
                return "F"
            else:
                logger.info(f"[{effective_name}] PDF scanné (OCR requis) détecté -> Famille I")
                return "I"

        # 9. Règles Familles G & H (Sont TOUJOURS des PDF)
        if ext == ".pdf":
            # Famille H : Emplois du temps
            if any(kw in effective_name_clean for kw in ["emploi du temps", "emplois du temps", "planning cours", "edt"]):
                logger.info(f"[{effective_name}] Emploi du temps détecté -> Famille H")
                return "H"

            # Famille G : PV de délibération
            if any(kw in effective_name_clean for kw in ["pv", "procès verbal", "proces verbal", "délibération", "deliberation"]):
                logger.info(f"[{effective_name}] PV de délibération détecté -> Famille G")
                return "G"

        # 10. Traitement des fichiers Excel
        if ext in [".xlsx", ".xls"]:
            return "EXCEL"

        # 11. Règle Famille A (Formulaires / Procédures)
        if any(kw in effective_name_clean for kw in ["formulaire", "demande", "procédure", "procedure"]):
            return "A"

        # Fallback par défaut selon l'extension
        if ext in [".pdf", ".docx", ".doc"]:
            return "A"
        
        return "FALLBACK"

    # =========================================================================
    # METHODES AUXILIAIRES D'EXTRACTION ET D'ANALYSE
    # =========================================================================
    def _clean_spaced_text(text: str) -> str:
            """
            Détecte et réassemble les textes ayant des lettres ou chiffres artificiellement espacés,
            y compris avec des variations d'espaces extrêmes et des apostrophes isolées.
            """
            if not text:
                return text
        
            # ÉTAPE 1 : Recoller immédiatement les apostrophes isolées par des espaces (ex: "D ’ I" -> "D’I")
            # Cela évite que l'apostrophe soit traitée comme une lettre isolée par la suite.
            text = re.sub(r'([a-zA-ZÀ-ÿ0-9])\s*([\'’`‘])\s*([a-zA-ZÀ-ÿ0-9])', r'\1\2\3', text)
        
            # Fonction interne pour nettoyer une zone spécifique détectée
            def _clean_match(match):
                segment = match.group(0)
                # 1. Séparation des mots par les très grands espacements (4 espaces ou plus)
                if re.search(r'\s{3,}', segment):
                    words = re.split(r'\s{3,}', segment)
                else:
                    # Sinon, on sépare par les doubles espaces ou plus (2 ou plus)
                    words = re.split(r'\s{2,}', segment)
                    
                # 2. Suppression de TOUS les espaces internes pour chaque mot reconstruit
                cleaned_words = [re.sub(r'\s+', '', w) for w in words if w.strip()]
                return " ".join(cleaned_words)
        
            # ÉTAPE 2 : Expression régulière pour cibler les suites de caractères espacés
            # On autorise le tiret (-) et les apostrophes qui ont déjà été recollées à l'étape 1
            spaced_pattern = r'(?:[a-zA-ZÀ-ÿ0-9\-\'’`‘]\s+){2,}[a-zA-ZÀ-ÿ0-9\-\'’`‘]'
            text = re.sub(spaced_pattern, _clean_match, text)
        
            # ÉTAPE 3 : Nettoyage final des espaces multiples résiduels pour un rendu parfait
            return re.sub(r'\s+', ' ', text).strip()



        
    def _get_effective_name(self, file_path: str) -> str:
        """
        Extrait le nom du fichier. Si le nom issu du chemin est opaque (numérique/alphanumérique)
        ou dépasse 25 caractères, extrait le nom à partir du contenu du fichier après l'en-tête.
        """
        raw_name = Path(file_path).stem.strip()

        if self._is_opaque_or_too_long(raw_name):
            logger.warning(f"Nom de fichier opaque ou trop long ('{raw_name}'). Extraction du titre depuis le contenu...")
            content_title = self._extract_title_from_content(file_path)
            if content_title:
                logger.info(f"Titre extrait du contenu : '{content_title}'")
                return content_title

        return raw_name

    def _is_opaque_or_too_long(self, filename: str) -> bool:
        """
        Vérifie si le nom de fichier est une suite uniquement alphanumérique/numérique
        sans espaces ou dépasse 50 caractères.
        """
        if len(filename) > 30:
            return True
        if filename.isdigit():
            return True
        if re.match(r"^[a-fA-F0-9]{8,}$", filename):
            return True
        if re.match(r"^[a-zA-Z0-9]+$", filename) and not any(char.isspace() for char in filename):
            if len(filename) > 12:
                return True
        return False

    def _extract_title_from_content(self, file_path: str) -> Optional[str]:
        """
        Parcourt les premières lignes du document, saute les en-têtes administratifs
        et retourne le premier titre significatif.
        """
        ext = Path(file_path).suffix.lower()
        extracted_lines = []

        try:
            if ext == ".pdf":
                doc = pymupdf.open(file_path)
                if len(doc) > 0:
                    text = doc[0].get_text("text")
                    extracted_lines = [line.strip() for line in text.split("\n") if line.strip()]
                doc.close()

            elif ext in [".docx", ".doc"]:
                doc = Document(file_path)
                extracted_lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

            elif ext in [".xlsx", ".xls"]:
                wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
                sheet = wb.active
                for row in sheet.iter_rows(max_row=10, values_only=True):
                    row_str = " ".join([str(cell) for cell in row if cell is not None]).strip()
                    if row_str:
                        extracted_lines.append(row_str)
                wb.close()

        except Exception as e:
            logger.error(f"Erreur lors de la lecture du contenu de {file_path} : {e}")
            return None

        # Filtrage des lignes d'en-tête
        for line in extracted_lines[:15]:
            line_clean = line.lower()
            is_header = any(re.search(pattern, line_clean) for pattern in self.HEADER_PATTERNS)
            if not is_header and len(line) > 3:
                return line

        return None

    def _analyze_pdf(self, file_path: str) -> Tuple[int, bool]:
        """
        Analyse un PDF pour déterminer :
        1. Le nombre de pages.
        2. S'il s'agit d'un PDF scanné (OCR nécessaire).
        """
        try:
            doc = pymupdf.open(file_path)
            page_count = len(doc)
            total_text_length = 0

            pages_to_check = min(page_count, 3)
            for i in range(pages_to_check):
                total_text_length += len(doc[i].get_text("text").strip())

            doc.close()

            is_scanned = (total_text_length / max(pages_to_check, 1)) < 50
            return page_count, is_scanned

        except Exception as e:
            logger.error(f"Erreur d'analyse du PDF {file_path} : {e}")
            return 0, False