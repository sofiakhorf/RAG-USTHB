# -*- coding: utf-8 -*-
"""
router.py - Routeur Hybride pour l'architecture RAG USTHB
=========================================================
Fusion des points forts :
- Logique de couverture (60%) de header_patterns.py (Robustesse absolue)
- Nettoyage intelligent des noms de fichiers (CamelCase/Acronyme)
- Lecture de l'ordre visuel DOCX (Paragraphes + Tableaux)
- Retour de l'index de démarrage effectif pour le Parser
- Regroupement centralisé des mots-clés de familles
- Ordre d'exécution optimal (Tests rapides d'abord, I/O disque ensuite)
"""


import os
import re
import logging
from pathlib import Path
from typing import Tuple, Optional, List, Dict

import pymupdf
import openpyxl
from docx import Document
from docx.document import Document as _Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

# --- Imports pour le core ---
from core import PipelineConfig
from core.utils import SystemUtils

logger = logging.getLogger(__name__)
_FLAGS = re.IGNORECASE | re.UNICODE

# =========================================================================
# UTILITAIRES DE LECTURE DOCX (Ordre visuel)
# =========================================================================

def iter_block_items(parent):
    """
    Génère les paragraphes et les tableaux dans l'ordre visuel exact du document.
    Indispensable pour que le routeur lise le tableau de l'en-tête USTHB 
    (qui contient souvent République/Ministère/Université) avant le corps du texte.

    BUGFIX : la version précédente faisait `parent.element.iterchildren()`.
    Pour un `Document` entier, `parent.element` est la racine `<w:document>`,
    dont l'UNIQUE enfant est `<w:body>` -- donc la boucle ne trouvait jamais
    aucun `<w:p>`/`<w:tbl>` et retournait toujours 0 bloc (extraction de
    titre depuis le contenu silencieusement cassée pour tous les .docx/.doc).
    Il faut itérer sur `parent.element.body` pour un Document, ou sur
    `parent._tc` pour une Cell de tableau.
    """
    if isinstance(parent, _Document):
        parent_elm = parent.element.body
    elif isinstance(parent, _Cell):
        parent_elm = parent._tc
    else:
        raise ValueError(f"iter_block_items: type de parent non supporté ({type(parent)})")

    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)


# =========================================================================
# ROUTEUR DE DOCUMENTS
# =========================================================================

class DocumentRouter:
    """
    Routeur de documents avancé pour le système RAG USTHB.
    Retourne un tuple (family, prepared_path, effective_title, effective_start_line).
    """

    # =========================================================================
    # DATASOURCE : Regroupement de tous les mots-clés par famille
    # =========================================================================
    FAMILY_KEYWORDS: Dict[str, List[str]] = {
        # --- Mots-clés Schémas & Diagrammes vectoriels ---
        "J": [
            "organigramme", "organigrammes", "schéma", "schema", "schémas", "schemas",
            "diagramme", "diagramme de flux", "synoptique", "architecture système", "cartographie"
        ],
        # --- Mots-clés Plannings / Examens ---
        "E": [
            "base rattrapage", "publipostage", "base examen", "base examens",
            "planning examen", "planning examens", "examen", "examens"
        ],
        # --- Mots-clés Programmes / Syllabus / Canevas ---
        "B": [
            "canevas", "programmes modules", "programme module", "syllabus", 
            "fiche de voeux", "fiche de vœux", "tronc commun ingénieur d'etat en informatique",
            "canevas de mise en conformité", "offre de formation", 
            "licence professionnalisante ", "master professionnalisant",
            "cahier des charges", "intitulé de la licence"
        ],
        # --- Mots-clés Décrets / Juridique ---
        "F": [
            "décret", "decret", "arrêté", "arrete", "journal officiel",
            "قرار", "مرسوم", "قانون", "decision", "loi", "ordonnance"
        ],
        # --- Mots-clés Emplois du temps ---
        "H": [
            "emploi du temps", "emplois du temps", "planning cours", "edt"
        ],
        # --- Mots-clés PV de délibération ---
        "G": [
            "pv", "procès verbal", "proces verbal", "délibération", "deliberation"
        ],
        # --- Mots-clés Formulaires / Procédures ---
        "A": [
            "formulaire", "demande", "procédure", "procedure"
        ]
    }

    # =========================================================================
    # Patterns d'en-têtes fusionnés (Noms de A, Ancrages précis de B)
    # =========================================================================
    RAW_PATTERNS = [
        # --- Arabe (RTL) ---
        ("ar_republique", r"الجمهورية\s*الجزائرية\s*الديمقراطية\s*الشعبية"),
        ("ar_ministere", r"وزارة\s*التعليم\s*العالي.*"),
        ("ar_universite", r"جامعة\s*هواري\s*بومدين.*"),
        # variante where the 3 arabic lines are concatenated on one line
        ("ar_bloc_combine", r"الجمهورية.*?التكنولوجيا"),

        # --- République / Ministère (FR) ---
        ("fr_republique", r"R[eéè]publique\s+Alg[eéè]rienne\s+D[eéè]mocratique\s+et\s+Populaire.*"),
        ("fr_ministere", rf"Minist[eéè]re\s+de\s+l[’']\s*Enseignement\s+Sup[eéè]rieur.*"),
        # continuation de la ligne ministère quand coupée en 2 lignes
        ("fr_ministere_suite", r"^ET\s+DE\s+LA\s+RECHERCHE\s+SCIENTIFIQUE.*"),

        # --- Bloc combiné sur une seule ligne (cas des PDF/Word mal formatés) ---
        ("fr_bloc_combine", r"R[eéè]publique\s+Alg[eéè]rienne.*?Boum[eéè]dien.*"),
        
        # --- Université / USTHB ---
        # couvre: "Université des Sciences et de la Technologie Houari Boumediene(USTHB)", 
        # "UNIVERSITE DES SCIENCES ET DE LA TECHNOLOGIE", "Université é des Sciences" (coquille)
        ("fr_universite_usthb", r"Universit[eé]\s*[eé]?\s+des\s+Sciences\s+et\s+de\s+(la\s+)?Technologie(\s+Houari\s+Boum[eé]dien{1,2}e?)?.*"),
        ("fr_houari_boumediene_seul", r"\W?Houari\s+Boum[eé]dien{1,2}e?\W?"),
        ("fr_usthb_sigle", r"\bUSTHB\b"),

        # --- Faculté / Département ---
        ("fr_faculte", r"Facult[eé]\b.*"),
        ("fr_departement", r"D[eé]partement\b.*"),
        ("fr_institut", r"Institut\b.*"),

        # --- Vice-Rectorat / Sous-Direction ---
        ("fr_vice_rectorat", r"(?:VICE[\s\-]*)?RECTORAT\s+CHARG[eé]\s+DE\s+LA\s+RECHERCHE.*"),
        ("fr_vice_rectorat_generic", r"(?:Vice[\s\-]*)?Rectorat.*"),
        ("fr_sous_direction", r"(?:Sous[\s\-]*)?Direction.*"),
        ("fr_post_graduation_ligne", r"^Post[\s\-]*Graduation.*"),
        # la ligne peut être coupée juste après "de la Recherche"
        ("fr_post_graduation_suite", r"^Scientifique\s+et\s+de\s+l[’']\s*Habilitation\s+Universitaire.*"),
        # variante Vice-Rectorat coupée sur 2 lignes
        ("fr_relations_exterieures_suite", r"^ET\s+DES\s+RELATIONS\s+EXT[eé]RIEURES.*"),

        # --- Année universitaire ---
        # accepte 20.., 200., 20......., 20 / 20, avec ou sans points de remplissage
        ("fr_annee_universitaire", r"Ann[eé]e(\s+Universitaire)?\s*[:\-]?\s*20[0-9.…]{0,8}\s*/\s*20?[0-9.…]{0,8}"),

        # --- Lignes orphelines administratives ---
        # BUGFIX : ces fragments sont maintenant ANCRÉS en début de ligne (^),
        # contrairement à une version précédente qui les cherchait n'importe où
        # dans la ligne (re.search sans ancre). Sans ancre, "post-graduation"
        # matchait aussi à l'intérieur du vrai TITRE du formulaire
        # "AUTORISATION D'INSCRIPTION EN POST-GRADUATION", qui se retrouvait
        # à tort classé comme en-tête et donc jamais retourné comme titre.
        ("fr_orphelin_recherche", r"^recherche\s+scientifique\b.*"),
        ("fr_orphelin_habilitation", r"^habilitation\s+universitaire\b.*"),
        ("fr_orphelin_relations", r"^relations\s+ext[eé]rieures\b.*"),

        # --- Titres de formulaires spécifiques ---
        ("fr_premiere_annee_cycle", r"^PREMIERE\s+ANN[eé]E\s+DE\s+(MAGISTER|DOCTORAT|MASTER)\s*$"),
        ("fr_cycle_seul", r"^\s*(MAGISTER|DOCTORAT)\s*$"),
        ("fr_document_descriptif_diplome", r"DOCUMENT\s+DESCRIPTIVE?\s+ANNEXE\s+AU\s+DIPLOME"),
        ("fr_consigne_remplissage", r"\(A\s+remplir\s+avec\s+le\s+plus\s+grand\s+soin"),
        ("fr_usthb_le_date", r"USTHB\s+le\s*[.…\s]*"),
        # Le [\.…_]* capture les points simples, les points de suspension (…) et les tirets bas de remplissage
        ("fr_alger_le_date", r"(?:Fait\s+[aà]\s+)?Alger\s+le\s*[\.…_\s]*"),
        # Gère "A Monsieur le...", "À Madame la..."
        ("fr_politesse_destinataire", r"^[ÀA]\s+(?:Monsieur|Madame)\s+(?:le|la|l[’'])\s+.+"),

        # --- Séparateurs visuels ---
        # Prend en compte les *, les -, les _ et les = utilisés comme lignes
        ("fr_separators", r"[-_*=….~]{4,}"),

        # --- Coordonnées ---
        ("fr_adresses_bp", r"B\.?P\.?\s*\d+"),
        ("fr_adresses_lieux", r"(El[-\s]*Alia|Bab[-\s]*Ezzouar|Alger\s*\d{5})"),
        ("fr_contacts_tel_fax", r"(?:T[eé]l\.?|Fax)\s*:\s*[\d\s\(\)\-]{4,}"),
    ]

    # Compilation des patterns
    HEADER_PATTERNS = [(name, re.compile(pat, _FLAGS)) for name, pat in RAW_PATTERNS]

    # Carte de normalisation des apostrophes/guillemets
    _QUOTE_MAP = {
        "\u2019": "'", "\u2018": "'", "\u02bc": "'", "\u00ab": '"', "\u00bb": '"',
    }

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()

    # =========================================================================
    # 1. NETTOYAGE DES TITRES ISSUS DES FICHIERS (Excellence de la Version B)
    # =========================================================================

    @staticmethod
    def _clean_filename_title(name: str) -> str:
        """
        Nettoie un titre issu du NOM DE FICHIER (pas du contenu) :
        - remplace tirets/underscores par des espaces
          ("Demande-RNTG" -> "Demande RNTG", "Rapport_Individuel__1_" -> "Rapport Individuel 1")
        - insère un espace aux frontières de casse type camelCase/PascalCase
          ("DemandeStageIngenieur" -> "Demande Stage Ingenieur")
        - gère aussi les suites de majuscules suivies d'un mot
          ("FICHEDeSuivi" -> "FICHE De Suivi")
        - recolle défensivement d'éventuelles lettres isolées via
          _clean_spaced_text (rare sur un nom de fichier, mais garde une
          cohérence de traitement avec les titres extraits du contenu)
        - compresse les espaces multiples résultants

        Limite connue : un nom de fichier tout en minuscules et sans séparateur
        ne peut pas être redécoupé sans dictionnaire de segmentation -> il restera tel quel.
        """
        if not name:
            return name

        cleaned = name

        # 1. tirets / underscores (simples ou multiples, ex: "__1_") -> espaces
        cleaned = re.sub(r"[_\-]+", " ", cleaned)

        # 2. frontière minuscule/chiffre -> Majuscule ("StageIngenieur" -> "Stage Ingenieur")
        cleaned = re.sub(r"(?<=[a-zà-ÿ0-9])(?=[A-ZÀ-Ý])", " ", cleaned)

        # 3. frontière fin d'acronyme -> mot suivant ("PFEState" -> "PFE State")
        cleaned = re.sub(r"(?<=[A-ZÀ-Ý])(?=[A-ZÀ-Ý][a-zà-ÿ])", " ", cleaned)

        # 4. recollage défensif d'éventuelles lettres isolées par des espaces
        cleaned = DocumentRouter._clean_spaced_text(cleaned)

        # 5. compression finale des espaces
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        return cleaned

    @staticmethod
    def _clean_spaced_text(text: str) -> str:
        """
        Détecte et réassemble les textes ayant des lettres ou chiffres artificiellement espacés.
        
        BUGFIX : cette méthode corrige le comportement où "D E M A N D E" redevenait 
        "D E M A N D E" au lieu de "DEMANDE" (l'ancien code faisait `" ".join(...)` 
        au lieu de coller les lettres directement quand il s'agit d'un seul mot espacé).
        """
        if not text:
            return text
    
        # ÉTAPE 1 : Recoller immédiatement les apostrophes isolées par des espaces (ex: "D ’ I" -> "D’I")
        # Cela évite que l'apostrophe soit traitée comme une lettre isolée par la suite.
        text = re.sub(r'([a-zA-ZÀ-ÿ0-9])\s*([\'’`‘])\s*([a-zA-ZÀ-ÿ0-9])', r'\1\2\3', text)
    
        def _clean_match(match):
            segment = match.group(0)
            # 1. Si un très grand espacement (3 espaces ou plus) est présent,
            # il marque une VRAIE frontière de mot (ex: "...E       D..."
            # entre "DEMANDE" et "D'INSCRIPTION") -> on découpe là, on
            # recolle chaque mot séparément, puis on les rejoint par un
            # espace simple entre mots.
            if re.search(r'\s{3,}', segment):
                words = re.split(r'\s{3,}', segment)
                cleaned_words = [re.sub(r'\s+', '', w) for w in words if w.strip()]
                return " ".join(cleaned_words)

            # 2. Sinon, tout le segment ne forme qu'UN SEUL mot
            # artificiellement espacé lettre par lettre (ex: "I  N  S  C  R  I  P  T  I  O  N" 
            # -> "INSCRIPTION"). Il ne faut PAS rejoindre les lettres par des espaces : 
            # on les colle directement.
            return re.sub(r'\s+', '', segment)
    
        # ÉTAPE 2 : Expression régulière pour cibler les suites de caractères espacés
        # On autorise le tiret (-) et les apostrophes qui ont déjà été recollées à l'étape 1
        spaced_pattern = r'(?:[a-zA-ZÀ-ÿ0-9\-\'’`‘]\s+){2,}[a-zA-ZÀ-ÿ0-9\-\'’`‘]'
        text = re.sub(spaced_pattern, _clean_match, text)
    
        # ÉTAPE 3 : Nettoyage final des espaces multiples résiduels pour un rendu parfait
        return re.sub(r'\s+', ' ', text).strip()

    # =========================================================================
    # 2. LOGIQUE DE COUVERTURE 60% (Excellence de la Version A)
    # =========================================================================

    @classmethod
    def _normalize(cls, text: str) -> str:
        """Normalise les guillemets/apostrophes et compresse les espaces."""
        for src, dst in cls._QUOTE_MAP.items():
            text = text.replace(src, dst)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @classmethod
    def _is_header_line(cls, line: str, coverage_threshold: float = 0.6) -> bool:
        """
        True si la ligne est majoritairement constituée de boilerplate institutionnel.
        Utilise la logique de couverture (60%) : fusionne les intervals de match
        et vérifie qu'ils couvrent au moins 60% de la ligne utile.
        
        Stratégie : on cumule la couverture (en nb de caractères non-espace) de
        TOUS les patterns qui matchent quelque part dans la ligne — pas
        seulement le meilleur individuellement — car certains fichiers
        concatènent plusieurs blocs institutionnels sur une seule ligne.
        Si l'union des zones matchées couvre >= 60% de la ligne, elle est
        considérée comme header. Cela évite aussi de supprimer une ligne
        "utile" qui contiendrait accidentellement un mot-clé isolé.
        """
        norm = cls._normalize(line)
        stripped = norm.strip()
        
        if not stripped:
            return True

        useful_len = len(re.sub(r"\s+", "", stripped))
        if useful_len == 0 or useful_len <= 3:
            return True

        # Union des intervalles matchés par TOUS les patterns
        intervals = []
        for name, rx in cls.HEADER_PATTERNS:
            for m in rx.finditer(stripped):
                if m.start() != m.end():
                    intervals.append((m.start(), m.end()))

        if not intervals:
            return False

        # Fusion des intervalles chevauchants
        intervals.sort()
        merged = [intervals[0]]
        for s, e in intervals[1:]:
            ls, le = merged[-1]
            if s <= le:
                merged[-1] = (ls, max(le, e))
            else:
                merged.append((s, e))

        # Calcul de la couverture
        covered_chars = 0
        for s, e in merged:
            segment = stripped[s:e]
            covered_chars += len(re.sub(r"\s+", "", segment))

        return (covered_chars / useful_len) >= coverage_threshold

    # =========================================================================
    # 3. EXTRACTION DU CONTENU (Excellence de la Version A - Gestion Tableaux)
    # =========================================================================

    def _extract_title_from_content(self, file_path: str) -> Tuple[Optional[str], int]:
        """
        Parcourt le document (y compris les tableaux DOCX), saute l'en-tête 
        et retourne (titre_ou_None, effective_start_line).
        
        Retourne (titre_ou_None, effective_start_line) où effective_start_line
        est l'indice (0-based) de cette ligne dans `extracted_lines` -- c'est
        cette valeur qui doit être transmise au parser en aval pour qu'il
        saute directement l'en-tête institutionnel sans le retraiter.

        IMPORTANT pour l'alignement des indices côté parser : `extracted_lines`
        correspond aux lignes/paragraphes NON VIDES (après strip()), extraites
        de la même façon selon le type de fichier.
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
                # LECTURE VISUELLE : Paragraphes ET Tableaux mélangés
                # Si on utilise doc.paragraphs, on rate les en-têtes contenus dans
                # les tableaux invisibles de Word (très fréquent à l'USTHB).
                for block in iter_block_items(doc):
                    if isinstance(block, Paragraph):
                        if block.text.strip():
                            extracted_lines.append(block.text.strip())
                    elif isinstance(block, Table):
                        for row in block.rows:
                            row_texts = []
                            for cell in row.cells:
                                for p in cell.paragraphs:
                                    txt = p.text.strip()
                                    if txt:
                                        row_texts.append(txt)
                            if row_texts:
                                # .extend() "verse" chaque élément individuellement
                                extracted_lines.extend(row_texts)

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
            return None, 0

        # Filtrage des en-têtes avec la logique de couverture 60%
        max_scanned = min(len(extracted_lines), 15)
        for idx, line in enumerate(extracted_lines[:max_scanned]):
            # Despacement défensif : certains formulaires ont leur titre
            # écrit lettre par lettre -> on le recolle avant de le retourner.
            if not self._is_header_line(line) and len(line) > 3:
                clean_title = self._clean_spaced_text(line)
                return clean_title, idx

        # Aucune ligne de contenu exploitable trouvée dans la zone scannée :
        # on ne peut pas garantir un point de reprise fiable -> on retourne 0
        logger.warning(f"Aucun titre exploitable trouvé dans les {max_scanned} premières lignes de {file_path}.")
        return None, 0

    # =========================================================================
    # 4. ORCHESTRATION (Transmission d'Index)
    # =========================================================================

    def _is_opaque_or_too_long(self, filename: str) -> bool:
        """
        Vérifie si le nom de fichier est une suite uniquement alphanumérique/numérique
        sans espaces ou dépasse 30 caractères.
        """
        if len(filename) > 30: return True
        if filename.isdigit(): return True
        if re.match(r"^[a-fA-F0-9]{8,}$", filename): return True
        if re.match(r"^[a-zA-Z0-9]+$", filename) and not any(char.isspace() for char in filename) and len(filename) > 12:
            return True
        return False

    def _get_effective_title_and_index(self, file_path: str) -> Tuple[str, int]:
        """
        Remplace les anciennes fonctions redondantes.
        Réalise l'extraction I/O coûteuse UNE SEULE FOIS et retourne le titre et l'index, 
        que le nom du fichier soit opaque ou non.
        
        Point important : ce calcul de l'index est TOUJOURS effectué en scannant le 
        contenu, même quand le titre finalement retenu provient du nom de fichier -- 
        car le nom de fichier ne dit rien sur la position de l'en-tête DANS le document.
        """
        raw_name = Path(file_path).stem.strip()
        
        # Appel unique à la fonction coûteuse
        content_title, effective_start_line = self._extract_title_from_content(file_path)

        # Si le nom du fichier est inutilisable (opaque)
        if self._is_opaque_or_too_long(raw_name):
            if content_title:
                return content_title, effective_start_line
            return self._clean_filename_title(raw_name), effective_start_line

        # Si le nom du fichier est propre, on l'utilise, mais on conserve l'index trouvé dans le contenu
        return self._clean_filename_title(raw_name), effective_start_line

    def _matches_keywords(self, text: str, family_id: str) -> bool:
        """Vérifie si le texte contient l'un des mots-clés de la famille ciblée."""
        return any(kw in text for kw in self.FAMILY_KEYWORDS.get(family_id, []))

    # =========================================================================
    # 5. POINT D'ENTRÉE PRINCIPAL
    # =========================================================================

    @classmethod
    def classify_document(cls, file_path: str, config: Optional[PipelineConfig] = None) -> Tuple[str, str, str, int]:
        """
        Point d'entrée principal.
        Le flux est désormais linéaire et optimisé (sans appels redondants).
        Retourne (family, prepared_path, effective_title, effective_start_line).
        """
        router = cls(config=config)
        
        if file_path.lower().endswith(".doc"):
            logger.info(f"Fichier .doc détecté. Conversion : {file_path}")
            try:
                file_path = SystemUtils.convert_doc_to_docx(file_path, router.config)
            except Exception as e:
                logger.error(f"Échec de la conversion du fichier {file_path} : {e}")

        # Un seul appel orchestre tout
        family, effective_title, effective_start_line = router._determine_family(file_path)
        
        prepared_path = str(Path(file_path).resolve())
        
        return family, prepared_path, effective_title, effective_start_line

    def _determine_family(self, file_path: str) -> Tuple[str, str, int]:
        """
        Traite le fichier et retourne (famille, titre_effectif, index_de_demarrage).
        Centralise l'appel pour éviter toute redondance.
        ORDONNANCEMENT : Tests rapides (Extension) -> Tests coûteux (I/O Contenu)
        """
        file_path_obj = Path(file_path)
        ext = file_path_obj.suffix.lower()

        # -------------------------------------------------------------
        # 1. Règles absolues par extension SANS AUCUN contenu texte
        # possible (images, formats vectoriels) -> aucun I/O, titre = nom
        # de fichier nettoyé. NE PAS ajouter .xlsx/.xls ici : contrairement
        # aux jpg/vsdx, un xlsx a un contenu textuel exploitable (cellules),
        # donc il doit passer par _get_effective_title_and_index comme les
        # pdf/docx pour bénéficier de l'extraction de titre depuis le
        # contenu quand son nom de fichier est opaque.
        # -------------------------------------------------------------
        if ext in [".jpg", ".jpeg"]: 
            return "I", self._clean_filename_title(file_path_obj.stem), 0
        
        family_j_extensions = [".vsdx", ".vsd", ".drawio", ".svg", ".puml", ".plantuml"]
        if ext in family_j_extensions: 
            return "J", self._clean_filename_title(file_path_obj.stem), 0

        # -------------------------------------------------------------
        # 2. Extraction I/O unique (Lecture disque coûteuse)
        # -------------------------------------------------------------
        # pdf / docx / doc / xlsx / xls passent tous ici : un seul appel,
        # un seul parsing du fichier, quel que soit le format.
        effective_title, effective_start_line = self._get_effective_title_and_index(file_path)
        effective_title_clean = effective_title.lower() if effective_title else ""

        if ext in [".xlsx", ".xls"]:
            return "EXCEL", effective_title, effective_start_line

        # -------------------------------------------------------------
        # 3. Logique de classification par mots-clés (Utilisation du dictionnaire)
        # -------------------------------------------------------------
        if self._matches_keywords(effective_title_clean, "J"): 
            return "J", effective_title, effective_start_line

        if self._matches_keywords(effective_title_clean, "E"): 
            return "E", effective_title, effective_start_line

        # Analyse structurelle du PDF si nécessaire (déjà lu à l'étape 2, 
        # ici on ne fait qu'analyser la structure métadonnées/pages)
        page_count, is_scanned_pdf = (0, False)
        if ext == ".pdf":
            page_count, is_scanned_pdf = self._analyze_pdf(file_path)

        if self._matches_keywords(effective_title_clean, "B") and (4 <= page_count if ext == ".pdf" else False):
            return "B", effective_title, effective_start_line

        if ext == ".pdf" and is_scanned_pdf:
            if self._matches_keywords(effective_title_clean, "F"): 
                return "F", effective_title, effective_start_line
            # For scanned PDFs with opaque names, check actual page content
            # for legal keywords before giving up and classifying as image.
            if self._scanned_pdf_has_legal_content(file_path):
                return "F", effective_title, effective_start_line
            return "I", effective_title, effective_start_line

        if ext == ".pdf":
            if self._matches_keywords(effective_title_clean, "H"): 
                return "H", effective_title, effective_start_line
            if self._matches_keywords(effective_title_clean, "G"): 
                return "G", effective_title, effective_start_line

        # -------------------------------------------------------------
        # 4. Fallbacks
        # -------------------------------------------------------------
        if self._matches_keywords(effective_title_clean, "A"): 
            return "A", effective_title, effective_start_line
            
        if ext in [".pdf", ".docx", ".doc"]: 
            return "A", effective_title, effective_start_line
        
        return "FALLBACK", effective_title, effective_start_line

    _LEGAL_KEYWORDS_SCAN = [
        "décret", "decret", "arrêté", "arrete", "journal officiel",
        "قرار", "مرسوم", "قانون", "decision", "loi", "ordonnance",
        "الجمهورية", "وزارة", "république", "ministère", "ministere",
    ]

    def _scanned_pdf_has_legal_content(self, file_path: str) -> bool:
        """Quick OCR of page 1 to detect legal keywords in scanned PDFs
        with opaque filenames (e.g. '994.pdf')."""
        try:
            import pytesseract
            from PIL import Image

            if "TESSDATA_PREFIX" not in os.environ:
                local_tess = Path(__file__).resolve().parent.parent / "tessdata"
                if local_tess.exists():
                    os.environ["TESSDATA_PREFIX"] = str(local_tess)

            doc = pymupdf.open(file_path)
            if len(doc) == 0:
                doc.close()
                return False
            page = doc[0]
            pix = page.get_pixmap(dpi=200)  # 200 DPI provides sharp Arabic OCR
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            doc.close()

            text = pytesseract.image_to_string(img, lang="fra+ara", config="--psm 6")
            text_lower = text.lower()
            return any(kw in text_lower for kw in self._LEGAL_KEYWORDS_SCAN)
        except Exception as e:
            logger.warning(f"Quick OCR scan failed for {file_path}: {e}")
            return False

    def _analyze_pdf(self, file_path: str) -> Tuple[int, bool]:
        """
        Analyse un PDF pour déterminer :
        1. Le nombre de pages.
        2. S'il s'agit d'un PDF scanné (OCR nécessaire).
        """
        try:
            doc = pymupdf.open(file_path)
            page_count = len(doc)
            total_text_length = sum(len(doc[i].get_text("text").strip()) for i in range(min(page_count, 3)))
            doc.close()
            is_scanned = (total_text_length / max(min(page_count, 3), 1)) < 50
            return page_count, is_scanned
        except Exception as e:
            logger.error(f"Erreur d'analyse du PDF {file_path} : {e}")
            return 0, False