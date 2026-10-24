import re
import unicodedata
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import os
import pdfplumber

from core import Chunk, ChunkMetadata, BaseFamilyParser, ParserRegistry
from core.utils import SystemUtils, AcademicMetadataExtractor
from parsers.fallback import FallbackParser

logger = logging.getLogger("RAG_USTHB")


@dataclass
class ParserConfig:
    batch_size_examens: int = 8
    reset_ctx_per_page: bool = False
    # Nombre max de lignes scannées en début de tableau pour trouver la VRAIE
    # ligne d'en-tête (les PDF USTHB intercalent souvent logo/titre/sous-titre
    # avant l'en-tête réel : "Année | Spécialité | Date | Horaire | Module | Salle").
    header_search_limit: int = 20
    # Seuil minimal de champs mappés pour considérer un column-mapping valide.
    min_valid_col_map_fields: int = 2


@ParserRegistry.register("E")
class FamilyEParser(BaseFamilyParser):
    """Parser pour extraire et normaliser les plannings d'examens à partir de fichiers PDF

    avec extraction des métadonnées d'en-tête de page.
    """

    # Regex étendues pour supporter tirets, points, plages horaires et "en ligne"
    DATE_REGEX = re.compile(
        r"\b(?:\d{1,2}[\/\.-]\d{1,2}[\/\.-]\d{2,4})\b", re.IGNORECASE
    )
    TIME_REGEX = re.compile(
        r"\b(?:\d{1,2}\s*[hH:]\s*\d{0,2}(?:\s*[-–—]\s*\d{1,2}\s*[hH:]\s*\d{0,2})?|en\s+ligne)\b",
        re.IGNORECASE,
    )

    # Repli pour les tableaux où pdfplumber fusionne plusieurs lignes logiques
    # (Date / Horaire / Module / Salle) dans UNE SEULE cellule multi-lignes,
    # faute de bordures internes dans le PDF source. Chaque ligne du bloc
    # ressemble à : "[S1|S2 ]date horaire module... salle" où "salle" est le
    # dernier token (sans espace) de la ligne.
    EMBEDDED_LINE_REGEX = re.compile(
        r"^\s*(?:(S\d)\s+)?"
        r"(\d{1,2}[\/\.-]\d{1,2}[\/\.-]\d{2,4})\s+"
        r"(\d{1,2}\s*[:hH]\s*\d{2}(?::\d{2})?"
        r"(?:\s*[-–—]\s*\d{1,2}\s*[:hH]\s*\d{2}(?::\d{2})?)?|en\s+ligne)\s+"
        r"(.+?)\s+(\S+)\s*$",
        re.IGNORECASE,
    )

    # Longueur en-deçà de laquelle un mot-clé est comparé en mot entier
    # (limites \b) plutôt qu'en sous-chaîne, pour éviter les faux positifs
    # (ex: "an" ne doit pas matcher à l'intérieur de "ANGLAIS" ou "ANADISS").
    SHORT_KEYWORD_MAXLEN = 3

    KEYWORDS_MAP = {
        "annee": [
            "annee",
            "an",
            "promo",
            "niveau",
            "l1",
            "l2",
            "l3",
            "m1",
            "m2",
            "licence",
            "master",
        ],
        "specialite": ["specialite", "parcours", "filiere", "option", "tronc"],
        "semestre": ["semestre", "sem", "s1", "s2"],
        "section": ["section", "sec", "groupe"],
        "module": ["module", "matiere", "epreuve", "intitule", "unite"],
        "date": ["date", "jour"],
        "horaire": ["horaire", "heure", "creneau", "temps"],
        # "locaux" (orthographe correcte) ajouté : c'est l'intitulé de colonne
        # réellement utilisé dans plusieurs plannings USTHB au lieu de "Salle".
        "salle": ["salle", "lieu", "amphi", "local", "locaux", "locoaux"],
        "type_examen": ["type", "session", "rattrapage", "examen"],
    }

    def __init__(self, config: Optional[ParserConfig] = None):
        self.config = config or ParserConfig()

    @staticmethod
    def _normalize_text(text: Optional[str]) -> str:
        """Nettoie le texte : supprime les accents, met en minuscules et rassemble les espaces."""
        if not text:
            return ""
        text = " ".join(str(text).split())
        text_nkfd = unicodedata.normalize("NFKD", text)
        no_accents = "".join(
            [c for c in text_nkfd if not unicodedata.combining(c)]
        )
        return no_accents.lower().strip()

    @classmethod
    def _keyword_matches(cls, keyword: str, normalized_cell: str) -> bool:
        """Teste si un mot-clé correspond à une cellule déjà normalisée.

        Les mots-clés courts (<= SHORT_KEYWORD_MAXLEN) sont comparés en mot
        entier (limites \\b) afin d'éviter les faux positifs (ex: "an" ne doit
        pas matcher "anglais"/"anadiss", "sec" ne doit pas matcher "securite").
        Les mots-clés plus longs restent comparés en sous-chaîne, ce qui reste
        nécessaire pour tolérer les fautes de frappe des documents sources
        (ex: "sectionn" contient bien "section").
        """
        if not normalized_cell:
            return False
        if len(keyword) <= cls.SHORT_KEYWORD_MAXLEN:
            return re.search(rf"\b{re.escape(keyword)}\b", normalized_cell) is not None
        return keyword in normalized_cell

    @staticmethod
    def extract_header_metadata(page_text: str) -> Dict[str, str]:
        """Extrait les attributs globaux (Semestre, Session, Type d'examen, Année Universitaire)

        depuis le texte brut de l'en-tête de page via Regex.
        """
        metadata = {
            "semestre": "",
            "session": "",
            "type_examen": "",
            "annee_universitaire": "",
        }

        if not page_text:
            return metadata

        # 1. Extraction du Semestre (ex: "Semestre 1", "S2")
        sem_match = re.search(
            r"\b(?:Semestre|Sem|S)\s*(\d+)\b", page_text, re.IGNORECASE
        )
        if sem_match:
            metadata["semestre"] = f"Semestre {sem_match.group(1)}"

        # 2. Extraction de la Session (ex: "Session 1", "Session 2")
        sess_match = re.search(
            r"\bSession\s*(\d+)\b", page_text, re.IGNORECASE
        )
        if sess_match:
            metadata["session"] = f"Session {sess_match.group(1)}"

        # 3. Détection du Type d'examen (Rattrapage vs Examen Normal)
        if re.search(r"Rattrapage", page_text, re.IGNORECASE):
            metadata["type_examen"] = "Rattrapage"
        elif re.search(
            r"Planning\s+des\s+Examens|Examen", page_text, re.IGNORECASE
        ):
            metadata["type_examen"] = "Examen Normal"

        # 4. Extraction de l'Année Universitaire (ex: "2025/2026", "2025-2026")
        year_match = re.search(r"\b(20\d{2}[-/]20\d{2})\b", page_text)
        if year_match:
            metadata["annee_universitaire"] = year_match.group(1)

        return metadata

    @staticmethod
    def _normalize_semestre(value: str) -> str:
        """Uniformise l'affichage du semestre : "S1"/"S2" -> "Semestre 1"/"Semestre 2".

        Certains tableaux utilisent une colonne dédiée avec des valeurs
        abrégées ("S1", "S2") alors que l'en-tête de page produit "Semestre 1".
        On uniformise pour garder des phrases narratives cohérentes.
        """
        if not value:
            return value
        m = re.fullmatch(r"[Ss](\d+)", value.strip())
        if m:
            return f"Semestre {m.group(1)}"
        return value

    def _is_header(self, row: List[Optional[str]]) -> bool:
        """Détecte de manière robuste si une ligne est un en-tête de tableau.

        Deux conditions cumulatives :
        1) au moins 2 cellules distinctes reconnaissent un mot-clé de colonne ;
        2) ces cellules représentent une part significative des cellules non
           vides de la ligne, ET la ligne a un nombre de cellules non vides
           cohérent avec un en-tête réel (qui remplit quasiment toutes les
           colonnes). Cette 2e condition est essentielle : une ligne de
           sous-titre du type "Semestre 2 Session 1" / "Année Universitaire
           2025/2026" (seulement 2 cellules non vides sur 7) matchait sinon à
           tort "semestre" et "annee", avant même d'atteindre le vrai en-tête
           du tableau.
        """
        non_empty_cells = [cell for cell in row if cell]
        normalized_row = [self._normalize_text(cell) for cell in non_empty_cells]
        if not normalized_row:
            return False

        header_hits = 0
        for cell in normalized_row:
            for key_list in self.KEYWORDS_MAP.values():
                if any(self._keyword_matches(kw, cell) for kw in key_list):
                    header_hits += 1
                    break

        if header_hits < 2:
            return False

        total_cols = len(row)
        min_non_empty = max(3, (total_cols + 1) // 2)
        if len(non_empty_cells) < min_non_empty:
            return False
        if header_hits / len(non_empty_cells) < 0.5:
            return False
        return True

    def _build_col_map_from_row(
        self, header_row: List[Optional[str]]
    ) -> Dict[str, int]:
        col_map: Dict[str, int] = {}
        for col_idx, cell in enumerate(header_row):
            clean_cell = self._normalize_text(cell)
            if not clean_cell:
                continue
            for field_name, keywords in self.KEYWORDS_MAP.items():
                if field_name not in col_map and any(
                    self._keyword_matches(kw, clean_cell) for kw in keywords
                ):
                    col_map[field_name] = col_idx
        return col_map

    def _detect_column_mapping(
        self, table: List[List[Optional[str]]]
    ) -> Tuple[Dict[str, int], Optional[int]]:
        """Identifie dynamiquement l'index des colonnes et la ligne d'en-tête réelle.

        Les PDF USTHB placent fréquemment plusieurs lignes de logo/titre/
        sous-titre AVANT la véritable ligne d'en-tête du tableau (parfois à
        la ligne 8 ou plus). On scanne donc une fenêtre plus large que les 3
        premières lignes, et on s'appuie sur la PREMIÈRE ligne qui satisfait
        _is_header (>= 2 colonnes reconnues) pour construire le mapping, au
        lieu d'agréger plusieurs lignes différentes (ce qui pouvait capter à
        tort des mots comme "examens" présents dans un titre).

        Retourne (col_map, index_de_la_ligne_d_entete). L'index est utilisé
        par parse() pour ignorer sans ambiguïté toutes les lignes de
        logo/titre précédant l'en-tête, même si elles ne sont pas elles-mêmes
        détectées comme "header" par _is_header.
        """
        search_limit = min(len(table), self.config.header_search_limit)
        for idx in range(search_limit):
            row = table[idx]
            if row and self._is_header(row):
                return self._build_col_map_from_row(row), idx

        # Repli : aucune ligne d'en-tête franche trouvée. On retombe sur
        # l'ancien comportement (agrégation sur les 3 premières lignes) pour
        # ne pas régresser sur des tableaux atypiques déjà bien gérés.
        col_map: Dict[str, int] = {}
        for row in table[:3]:
            if not row:
                continue
            for col_idx, cell in enumerate(row):
                clean_cell = self._normalize_text(cell)
                if not clean_cell:
                    continue
                for field_name, keywords in self.KEYWORDS_MAP.items():
                    if field_name not in col_map and any(
                        self._keyword_matches(kw, clean_cell) for kw in keywords
                    ):
                        col_map[field_name] = col_idx
        return col_map, None

    def _extract_record(
        self, row: List[Optional[str]], col_map: Dict[str, int]
    ) -> Dict[str, str]:
        """Extrait les données d'une ligne avec correction d'inversion et fallback par regex."""
        raw_data: Dict[str, str] = {}
        row_len = len(row)

        for field_name, col_idx in col_map.items():
            if col_idx < row_len and row[col_idx] is not None:
                raw_data[field_name] = " ".join(str(row[col_idx]).split())
            else:
                raw_data[field_name] = ""

        date_val = raw_data.get("date", "")
        time_val = raw_data.get("horaire", "")

        # Permutation si Date et Horaire sont inversés dans les colonnes
        if (
            date_val
            and self.TIME_REGEX.match(date_val)
            and (not time_val or self.DATE_REGEX.match(time_val))
        ):
             # 1. On stocke correctement dans le dictionnaire (en inversant les variables erronées)
             raw_data["date"] = time_val  # car time_val contenait en réalité la date
             raw_data["horaire"] = date_val  # car date_val contenait en réalité l'heure

             # 2. On corrige les variables d'origine pour la suite du script
             date_val, time_val = raw_data["date"], raw_data["horaire"]

        # Fallback Regex si un champ est manquant
        if not date_val or not time_val:
            for cell in row:
                if cell is None:
                    continue
                cell_str = " ".join(str(cell).split())
                if not date_val:
                    match_date = self.DATE_REGEX.search(cell_str)
                    if match_date:
                        date_val = match_date.group(0)
                        raw_data["date"] = date_val
                if not time_val:
                    match_time = self.TIME_REGEX.search(cell_str)
                    if match_time:
                        time_val = match_time.group(0)
                        raw_data["horaire"] = time_val

        return raw_data

    def _find_embedded_block_cell(
        self, row: List[Optional[str]]
    ) -> Optional[str]:
        """Repère une cellule contenant plusieurs lignes d'examens fusionnées.

        Certains PDF (tableaux sans bordures internes) font fusionner par
        pdfplumber les colonnes Date/Horaire/Module/Salle dans une seule
        cellule multi-lignes rattachée à une autre colonne (ex: "semestre").
        On la reconnaît à la présence d'un saut de ligne ET d'au moins deux
        dates détectées dans la cellule.
        """
        for cell in row:
            if not cell or "\n" not in str(cell):
                continue
            if len(self.DATE_REGEX.findall(str(cell))) >= 2:
                return str(cell)
        return None

    def _expand_embedded_block(
        self, block_text: str, base_record: Dict[str, str]
    ) -> List[Dict[str, str]]:
        """Découpe une cellule multi-lignes fusionnée en plusieurs enregistrements."""
        records: List[Dict[str, str]] = []
        current_semestre = base_record.get("semestre", "")
        for line in block_text.split("\n"):
            line = line.strip()
            if not line:
                continue
            match = self.EMBEDDED_LINE_REGEX.match(line)
            if not match:
                continue
            sem_marker, date_val, horaire_val, module_val, salle_val = match.groups()
            if sem_marker:
                current_semestre = self._normalize_semestre(sem_marker)
            record = dict(base_record)
            record["semestre"] = current_semestre
            record["date"] = date_val.strip()
            record["horaire"] = horaire_val.strip()
            record["module"] = module_val.strip()
            record["salle"] = salle_val.strip()
            records.append(record)
        return records

    def _extract_records(
        self, row: List[Optional[str]], col_map: Dict[str, int]
    ) -> List[Dict[str, str]]:
        """Extrait un ou plusieurs enregistrements d'examen à partir d'une ligne du tableau.

        Retourne une liste car une seule ligne physique du PDF peut en
        réalité contenir plusieurs examens fusionnés dans une cellule (voir
        _find_embedded_block_cell).
        """
        base_record = self._extract_record(row, col_map)

        module = base_record.get("module", "").strip()
        date_exam = base_record.get("date", "").strip()

        if module and date_exam:
            base_record["semestre"] = self._normalize_semestre(
                base_record.get("semestre", "")
            )
            return [base_record]

        # Le mapping "normal" n'a rien donné : on cherche un bloc fusionné.
        block_text = self._find_embedded_block_cell(row)
        if not block_text:
            return [base_record]

        expanded = self._expand_embedded_block(block_text, base_record)
        return expanded if expanded else [base_record]

    def parse(
        self, 
        file_path: str, 
        document_title: Optional[str] = None,
        effective_start_line: int = 0
    ) -> List[Chunk]:
        """Parcourt le PDF, extrait les métadonnées d'en-tête et du tableau, et génère des Chunks."""
        clean_title = document_title if document_title else os.path.basename(file_path)
        chunks: List[Chunk] = []
        current_exam_lines: List[str] = []
        current_exam_pages: List[int] = []

        # Context global persistant incluant les métadonnées d'en-tête
        ctx: Dict[str, str] = {
            "annee": "",
            "specialite": "",
            "semestre": "",
            "section": "",
            "session": "",
            "type_examen": "",
            "annee_universitaire": "",
        }

        # Dernier mapping de colonnes valide connu, réutilisé si une page/table
        # ne présente pas de ligne d'en-tête franche (page de continuation).
        last_col_map: Dict[str, int] = {}

        try:
            with pdfplumber.open(file_path) as pdf:
                for page_idx, page in enumerate(pdf.pages):
                    if self.config.reset_ctx_per_page:
                        ctx = {k: "" for k in ctx}

                    # 1. Extraction et mise à jour des métadonnées d'en-tête de la page
                    page_text = page.extract_text() or ""
                    
                    # --- Tronquer l'en-tête institutionnel avant l'extraction des métadonnées ---
                    if effective_start_line > 0:
                        text_lines = page_text.split('\n')
                        if effective_start_line < len(text_lines):
                            page_text = "\n".join(text_lines[effective_start_line:])
                            
                    header_meta = self.extract_header_metadata(page_text)
                    for meta_key, meta_val in header_meta.items():
                        if meta_val:
                            ctx[meta_key] = meta_val

                    # 2. Traitement des tableaux
                    tables = page.extract_tables() or []
                    for table in tables:
                        if not table:
                            continue

                        col_map, header_idx = self._detect_column_mapping(table)

                        if len(col_map) >= self.config.min_valid_col_map_fields:
                            last_col_map = col_map
                        else:
                            # Mapping trop pauvre (ex: page de continuation sans
                            # en-tête répété) : on retombe sur le dernier mapping valide.
                            col_map = last_col_map
                            header_idx = None

                        last_row_date = ""
                        last_row_horaire = ""

                        for row_idx, row in enumerate(table):
                            if not row:
                                continue
                            # Toute ligne à ou avant l'en-tête détecté est du
                            # logo/titre/en-tête, jamais de la donnée -> on l'ignore.
                            if header_idx is not None and row_idx <= header_idx:
                                continue
                            if self._is_header(row):
                                last_row_date = ""
                                last_row_horaire = ""
                                continue

                            records = self._extract_records(row, col_map)

                            for record in records:
                                # Propagation si Date/Horaire est fusionnée avec la ligne précédente (rowspan)
                                if not record.get("date") and last_row_date and record.get("module"):
                                    record["date"] = last_row_date
                                    if not record.get("horaire") and last_row_horaire:
                                        record["horaire"] = last_row_horaire

                                # 3. Mise à jour du contexte persistant à partir du tableau
                                for ctx_key in ctx.keys():
                                    if record.get(ctx_key):
                                        ctx[ctx_key] = record[ctx_key]

                                module = record.get("module", "").strip()
                                date_exam = record.get("date", "").strip()

                                # Validation minimale
                                if not module or not date_exam:
                                    continue

                                last_row_date = date_exam
                                last_row_horaire = record.get("horaire", "").strip()

                                # Construction des éléments de la phrase narrative
                                type_exam = (
                                    record.get("type_examen")
                                    or ctx.get("type_examen")
                                    or ""
                                )
                                session_str = (
                                    f" ({ctx['session']})" if ctx.get("session") else ""
                                )
                                if type_exam:
                                    if type_exam.lower().startswith("examen"):
                                        prefixe = f"{type_exam}{session_str}".strip()
                                    else:
                                        prefixe = f"Examen {type_exam}{session_str}".strip()
                                else:
                                    prefixe = "Examen"

                                horaire_str = (
                                    f" à {record['horaire']}"
                                    if record.get("horaire")
                                    else ""
                                )
                                salle_str = (
                                    f", salle {record['salle']}"
                                    if record.get("salle")
                                    else ""
                                )
                                semestre_str = (
                                    f" ({ctx['semestre']})" if ctx.get("semestre") else ""
                                )

                                parcours_parts = [
                                    p
                                    for p in [ctx.get("annee"), ctx.get("specialite")]
                                    if p
                                ]
                                parcours_str = (
                                    f", parcours {' '.join(parcours_parts)}"
                                    if parcours_parts
                                    else ""
                                )
                                section_str = (
                                    f" section {ctx['section']}"
                                    if ctx.get("section")
                                    else ""
                                )
                                annee_univ_str = (
                                    f" [{ctx['annee_universitaire']}]"
                                    if ctx.get("annee_universitaire")
                                    else ""
                                )

                                sentence = (
                                    f"{prefixe} {module}{semestre_str}{annee_univ_str}"
                                    f"{parcours_str}{section_str}"
                                    f", le {date_exam}{horaire_str}{salle_str}."
                                )

                                current_exam_lines.append(sentence)
                                current_exam_pages.append(page_idx + 1)

                                if len(current_exam_lines) >= self.config.batch_size_examens:
                                    chunk_page = current_exam_pages[0] if current_exam_pages else page_idx + 1
                                    chunks.append(
                                        self._build_chunk(
                                            current_exam_lines, chunk_page, ctx, clean_title
                                        )
                                    )
                                    current_exam_lines = []
                                    current_exam_pages = []

                if current_exam_lines:
                    chunk_page = current_exam_pages[0] if current_exam_pages else len(pdf.pages)
                    chunks.append(
                        self._build_chunk(
                            current_exam_lines, chunk_page, ctx, clean_title
                        )
                    )

        except Exception as e:
            logger.error(f"Erreur d'extraction sémantique E sur {file_path}: {e}", exc_info=True)
            chunks = []

        return chunks if chunks else FallbackParser.parse_safe(file_path, "E")

    def _build_chunk(
        self, lines: List[str], page_num: int, ctx: Dict[str, str], document_title: str
    ) -> Chunk:
        """Génère un Chunk contenant les lignes textuelles et le dictionnaire complet des métadonnées."""
        header = "--- Planning d'examens USTHB ---\n"
        content = header + "\n".join(lines)

        metadata = ChunkMetadata(
            type="exam_schedule",
            document_name=document_title,
            family_type="E",
            page=page_num,
            count=len(lines),
            semestre=ctx.get("semestre", "") or None,
            session=ctx.get("session", ""),
            type_examen=ctx.get("type_examen", ""),
            annee_universitaire=ctx.get("annee_universitaire", "") or None,
            annee=ctx.get("annee", ""),
            specialite=ctx.get("specialite", ""),
            section=ctx.get("section", ""),
        )

        return Chunk(text=content, metadata=metadata)
