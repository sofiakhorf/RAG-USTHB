import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import os
import pdfplumber

from core import Chunk, ChunkMetadata, BaseFamilyParser, ParserRegistry
from core.utils import SystemUtils, AcademicMetadataExtractor
from parsers.fallback import FallbackParser


@dataclass
class ParserConfig:
    batch_size_examens: int = 8
    reset_ctx_per_page: bool = False


@ParserRegistry.register("E")  # <-- AJOUT : Enregistrement dans le registre
class FamilyEParser(BaseFamilyParser):  # <-- AJOUT : Héritage de la classe de base
    """Parser pour extraire et normaliser les plannings d'examens à partir de fichiers PDF

    avec extraction des métadonnées d'en-tête de page.
    """

    # Regex étendues pour supporter tirets, points, plages horaires et "en ligne"
    DATE_REGEX = re.compile(
        r"\b(?:\d{1,2}[\/\.-]\d{1,2}[\/\.-]\d{2,4})\b", re.IGNORECASE
    )
    TIME_REGEX = re.compile(
        r"\b(?:\d{1,2}\s*[hH:]\s*\d{0,2}(?:\s*[-–â]\s*\d{1,2}\s*[hH:]\s*\d{0,2})?|en\s+ligne)\b",
        re.IGNORECASE,
    )

    KEYWORDS_MAP = {
        "annee": [
            "annee",
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
        "salle": ["salle", "lieu", "amphi", "local", "locoaux"],
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

    def _is_header(self, row: List[Optional[str]]) -> bool:
        """Détecte de manière robuste si une ligne est un en-tête de tableau."""
        normalized_row = [self._normalize_text(cell) for cell in row if cell]
        header_hits = 0
        for cell in normalized_row:
            for key_list in self.KEYWORDS_MAP.values():
                if any(kw in cell for kw in key_list):
                    header_hits += 1
                    break
        return header_hits >= 2

    def _detect_column_mapping(
        self, table: List[List[Optional[str]]]
    ) -> Dict[str, int]:
        """Identifie dynamiquement l'index des colonnes sur les premières lignes."""
        col_map: Dict[str, int] = {}
        for row in table[:3]:
            if not row:
                continue
            for col_idx, cell in enumerate(row):
                clean_cell = self._normalize_text(cell)
                if not clean_cell:
                    continue
                for field_name, keywords in self.KEYWORDS_MAP.items():
                    if field_name not in col_map:
                        if any(kw in clean_cell for kw in keywords):
                            col_map[field_name] = col_idx
        return col_map

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

        with pdfplumber.open(file_path) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                if self.config.reset_ctx_per_page:
                    ctx = {k: "" for k in ctx}

                # 1. Extraction et mise à jour des métadonnées d'en-tête de la page
                page_text = page.extract_text() or ""
                
                # --- AJOUT : Tronquer l'en-tête institutionnel avant l'extraction des métadonnées ---
                if  effective_start_line > 0:
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

                    col_map = self._detect_column_mapping(table)

                    for row in table:
                        if not row or self._is_header(row):
                            continue

                        record = self._extract_record(row, col_map)

                        # 3. Mise à jour du contexte persistant à partir du tableau
                        for ctx_key in ctx.keys():
                            if record.get(ctx_key):
                                ctx[ctx_key] = record[ctx_key]

                        module = record.get("module", "").strip()
                        date_exam = record.get("date", "").strip()

                        # Validation minimale
                        if not module or not date_exam:
                            continue

                        # Construction des éléments de la phrase narrative
                        type_exam = (
                            record.get("type_examen")
                            or ctx.get("type_examen")
                            or ""
                        )
                        session_str = (
                            f" ({ctx['session']})" if ctx.get("session") else ""
                        )
                        prefixe = (
                            f"Examen {type_exam}{session_str}".strip()
                            if type_exam
                            else "Examen"
                        )

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

                        if len(current_exam_lines) >= self.config.batch_size_examens:
                            # --- MODIFICATION : Transmission de clean_title ---
                            chunks.append(
                                self._build_chunk(
                                    current_exam_lines, page_idx + 1, ctx, clean_title
                                )
                            )
                            current_exam_lines = []

            if current_exam_lines:
                # --- MODIFICATION : Transmission de clean_title ---
                chunks.append(
                    self._build_chunk(
                        current_exam_lines, len(pdf.pages), ctx, clean_title
                    )
                )

        return chunks

    def _build_chunk(
        self, lines: List[str], page_num: int, ctx: Dict[str, str], document_title: str
    ) -> Chunk:
        """Génère un Chunk contenant les lignes textuelles et le dictionnaire complet des métadonnées."""
        header = "--- Planning d'examens USTHB ---\n"
        content = header + "\n".join(lines)

        metadata = {
            "type": "exam_schedule",
            "document_name": document_title,
            "page": page_num,
            "count": len(lines),
            "semestre": ctx.get("semestre", ""),
            "session": ctx.get("session", ""),
            "type_examen": ctx.get("type_examen", ""),
            "annee_universitaire": ctx.get("annee_universitaire", ""),
            "annee": ctx.get("annee", ""),
            "specialite": ctx.get("specialite", ""),
            "section": ctx.get("section", ""),
        }

        return Chunk(content=content, metadata=metadata)