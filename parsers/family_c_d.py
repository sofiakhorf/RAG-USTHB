import os
import re
import logging
from typing import List, Dict, Any, Tuple, Optional
import openpyxl

# --- Imports alignés sur la nouvelle architecture modulaire ---
from core import Chunk, ChunkMetadata, BaseFamilyParser, ParserRegistry
from core.utils import AcademicMetadataExtractor
from parsers.fallback import FallbackParser

logger = logging.getLogger("RAG_USTHB_EXCEL")

# =====================================================================
# 1. UTILS DE SEGMENTATION & GRILLE EXCEL (D2)
# =====================================================================

UNWANTED_STUDENT_COL_RE = re.compile(r"\b(semaine\s*\d*|sem\s*\d*|cc|td|tp)\b", re.IGNORECASE)

class ExcelSegmentationUtils:
    
    @staticmethod
    def get_real_bounds(ws) -> Tuple[int, int]:
        max_r, max_c = 0, 0
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is not None and str(cell.value).strip() != "":
                    max_r = max(max_r, cell.row)
                    max_c = max(max_c, cell.column)
        return max_r, max_c

    @staticmethod
    def get_block_max_column(ws, r0: int, r1: int) -> int:
        """Calcule le nombre maximal de colonnes non vides spécifique à un bloc."""
        block_max_c = 0
        for r in range(r0, r1 + 1):
            for c in range(1, ws.max_column + 1):
                val = ws.cell(row=r, column=c).value
                if val is not None and str(val).strip() != "":
                    block_max_c = max(block_max_c, c)
        return max(block_max_c, 1)

    @staticmethod
    def segment_sheet_into_blocks(ws) -> List[Tuple[int, int]]:
        """Découpe la feuille en blocs de lignes non vides (Segmentation D2)."""
        max_r, max_c = ExcelSegmentationUtils.get_real_bounds(ws)
        if max_r == 0:
            return []
            
        blank_rows = {
            r for r in range(1, max_r + 1)
            if all(ws.cell(row=r, column=c).value is None or str(ws.cell(row=r, column=c).value).strip() == "" for c in range(1, max_c + 1))
        }
        
        blocks, start = [], None
        for r in range(1, max_r + 1):
            if r in blank_rows:
                if start is not None:
                    blocks.append((start, r - 1))
                    start = None
            elif start is None:
                start = r
                
        if start is not None:
            blocks.append((start, max_r))
            
        return blocks

    @staticmethod
    def refine_block_title_and_bounds(ws, r0: int, r1: int, block_max_c: int) -> Tuple[int, int, Optional[str]]:
        """Sépare les bandeaux-titres du véritable tableau lorsque pas de ligne vide."""
        if block_max_c == 1:
            return r0, r1, None
            
        table_r0 = r0
        titre_bloc = None
        
        for r in range(r0, r1 + 1):
            non_empty_vals = [
                ws.cell(row=r, column=c).value 
                for c in range(1, block_max_c + 1) 
                if ws.cell(row=r, column=c).value is not None and str(ws.cell(row=r, column=c).value).strip() != ""
            ]
            
            if len(non_empty_vals) == 1:
                titre_bloc = str(non_empty_vals[0]).strip()
                table_r0 = r + 1
            elif len(non_empty_vals) > 1:
                break
                
        if table_r0 > r1:
            return r0, r1, titre_bloc
            
        return table_r0, r1, titre_bloc

    @staticmethod
    def filter_unwanted_student_columns(ws, table_r0: int, table_r1: int, block_max_c: int) -> List[int]:
        """Identifie et filtre les colonnes à supprimer (Semaine X, CC, TD, TP)."""
        cols_to_keep = []
        for c in range(1, block_max_c + 1):
            should_drop = False
            # Inspecte le header et les premières lignes du tableau
            for r in range(table_r0, min(table_r0 + 3, table_r1 + 1)):
                val = ws.cell(row=r, column=c).value
                if val is not None and UNWANTED_STUDENT_COL_RE.search(str(val).strip()):
                    should_drop = True
                    break
            if not should_drop:
                cols_to_keep.append(c)
        return cols_to_keep

    @staticmethod
    def resolve_grid(ws, r0: int, r1: int, valid_cols: List[int]) -> List[List[Any]]:
        """Construit la grille 2D uniquement sur les colonnes valides en gérant les fusions."""
        if not valid_cols:
            return []

        grid = [
            [ws.cell(row=r, column=c).value for c in valid_cols] 
            for r in range(r0, r1 + 1)
        ]
        
        col_map = {c: idx for idx, c in enumerate(valid_cols)}
        
        for rng in ws.merged_cells.ranges:
            if rng.min_row > r1 or rng.max_row < r0:
                continue
            
            top_val = ws.cell(row=rng.min_row, column=rng.min_col).value
            min_r = max(rng.min_row, r0)
            max_r_bound = min(rng.max_row, r1)
            
            merged_valid_cols = [c for c in range(rng.min_col, rng.max_col + 1) if c in col_map]
            
            for r in range(min_r, max_r_bound + 1):
                for c in merged_valid_cols:
                    grid[r - r0][col_map[c]] = top_val
                    
        return grid


# =====================================================================
# 2. PARSEURS DE BLOCS EXCEL
# =====================================================================

SECTION_RE = re.compile(r"^(Sujets?\s+\w+.*)$", re.IGNORECASE)
SOURCE_RE = re.compile(r"^Source\s*:", re.IGNORECASE)
BULLET_RE = re.compile(r"^[\u00b7-]\s*")
NUMBERED_SPLIT_RE = re.compile(r"(?:^|\n)\s*\d+[-.]\s*")

class ExcelBlockParsers:

    @staticmethod
    def _is_row_valid(row: List[Any]) -> bool:
        return any(v is not None and str(v).strip() != "" for v in row)

    @staticmethod
    def parse_flat_block(grid: List[List[Any]]) -> Tuple[List[str], List[Dict[str, Any]]]:
        clean_rows = [row for row in grid if ExcelBlockParsers._is_row_valid(row)]
        if not clean_rows:
            return [], []

        header_idx = 0
        header_row = clean_rows[header_idx]
        header = [
            str(h).strip() if (h is not None and str(h).strip() != "") else f"col_{i}" 
            for i, h in enumerate(header_row)
        ]
        
        records = []
        for r in clean_rows[header_idx + 1:]:
            row_dict = {
                header[i]: (str(r[i]).strip() if i < len(r) and r[i] is not None else "") 
                for i in range(len(header))
            }
            if any(val != "" for val in row_dict.values()):
                records.append(row_dict)
                
        return header, records

    @staticmethod
    def parse_free_text_column(grid: List[List[Any]]) -> List[Dict[str, Any]]:
        items, section, source = [], None, None
        for row in grid:
            cell = row[0]
            if cell is None or not str(cell).strip():
                continue
            text = str(cell).strip()
            
            if SECTION_RE.match(text):
                section = text
                continue
            if SOURCE_RE.match(text):
                source = text
                continue
                
            text_clean = BULLET_RE.sub("", text)
            sub_items = [s.strip() for s in NUMBERED_SPLIT_RE.split(text_clean) if s.strip()]
            
            for s in sub_items:
                items.append({
                    "section": section,
                    "source": source,
                    "sujet": s
                })
        return items

    @staticmethod
    def parse_planning_soutenance_block(grid: List[List[Any]], titre_bloc: str) -> List[Dict[str, Any]]:
        if len(grid) < 4:
            return []
            
        room_row = grid[1]
        records = []
        
        for row in grid[3:]:
            date, creneau = row[0], row[1]
            if creneau is None:
                continue
                
            c = 2
            while c + 2 < len(room_row):
                salle = room_row[c]
                n_projet = row[c]
                president = row[c + 1]
                membres = row[c + 2]
                
                if n_projet:
                    records.append({
                        "bloc_titre": titre_bloc,
                        "salle": salle,
                        "date": date,
                        "creneau": creneau,
                        "n_projet": n_projet,
                        "president": president,
                        "membres": membres,
                    })
                c += 3
        return records


# =====================================================================
# 3. MOTEUR EXCEL PRINCIPAL (Familles C & D)
# =====================================================================


@ParserRegistry.register("EXCEL")
class ExcelWorkbookParser(BaseFamilyParser):
    
    def __init__(self, config=None):
        super().__init__(config)

    @staticmethod
    def _is_planning_file(filename: str) -> bool:
        """
        Exige la présence d'un terme de type 'planning' ET d'un terme de type 'soutenance/pfe'.
        Exemples valides : 'planning_soutenance.xlsx', 'planning_pfe_2026.xlsx'
        """
        pattern_planning = r"planning|emploi_du_temps|agenda"
        pattern_soutenance = r"soutenance[s]?|pfe"
    
        has_planning = bool(re.search(pattern_planning, filename, re.IGNORECASE))
        has_soutenance = bool(re.search(pattern_soutenance, filename, re.IGNORECASE))
    
        return has_planning and has_soutenance

    @staticmethod
    def _is_student_list_file(filename: str) -> bool:
        """
        Exige un type de document (liste/affichage) AND un sujet (étudiant/notes) AND un niveau académique.
        Exemples valides : 'liste_etudiants_M2.xlsx', 'affichage_notes_L3.xlsx'
        """
        pattern_type = r"\b(liste|affichage)\b"
        pattern_subject = r"\b(etudiant[s]?|note[s]?|resultat[s]?)\b"
        pattern_level = r"\b(L[1-3]|M[1-2]|ING[1-5])\b"
    
        has_type = bool(re.search(pattern_type, filename, re.IGNORECASE))
        has_subject = bool(re.search(pattern_subject, filename, re.IGNORECASE))
        has_level = bool(re.search(pattern_level, filename, re.IGNORECASE))
    
        return has_type and has_subject and has_level

    def parse(
        self, 
        file_path: str, 
        document_title: Optional[str] = None,
        effective_start_line: int = 0
    ) -> List[Chunk]:
        # --- AJOUT : Injection du titre propre ---
        filename = document_title if document_title else os.path.basename(file_path)
        file_meta = AcademicMetadataExtractor.extract_from_text(filename)
        wb = openpyxl.load_workbook(file_path, data_only=True)
        chunks = []

        is_planning = self._is_planning_file(filename)
        is_student_list = self._is_student_list_file(filename)

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            blocks = ExcelSegmentationUtils.segment_sheet_into_blocks(ws)
            
            for (r0, r1) in blocks:
                block_max_c = ExcelSegmentationUtils.get_block_max_column(ws, r0, r1)
                if r1 < effective_start_line:
                   continue
                r0 = max(r0, effective_start_line) # Ajuster le début du bloc si ça chevauche
                # 1. Extraction du titre et séparation du vrai tableau
                table_r0, table_r1, titre_bloc = ExcelSegmentationUtils.refine_block_title_and_bounds(
                    ws, r0, r1, block_max_c
                )
                
                # 2. Filtrage des colonnes (Semaine X, CC, TD, TP) si liste d'étudiants
                if is_student_list:
                    valid_cols = ExcelSegmentationUtils.filter_unwanted_student_columns(
                        ws, table_r0, table_r1, block_max_c
                    )
                else:
                    valid_cols = list(range(1, block_max_c + 1))

                # 3. Construction de la grille 2D
                grid = ExcelSegmentationUtils.resolve_grid(ws, table_r0, table_r1, valid_cols)
                
                if not grid:
                    continue

                # Vérification si colonne unique (C-texte-libre)
                non_empty_cols = {c for row in grid for c, v in enumerate(row) if v is not None and str(v).strip() != ""}
                is_single_col = non_empty_cols in ({0}, set())
                
                block_meta = AcademicMetadataExtractor.extract_from_text(titre_bloc or "")
                merged_academic = {
                    "annee_universitaire": block_meta["annee_universitaire"] or file_meta["annee_universitaire"],
                    "niveau": block_meta["niveau"] or file_meta["niveau"],
                    "formation": block_meta["formation"] or file_meta["formation"]
                }

                # --- CAS 1 : C-texte-libre ---
                if is_single_col:
                    items = ExcelBlockParsers.parse_free_text_column(grid)
                    for item in items:
                        txt = f"Sujet ({item['section'] or 'Général'}) - Source: {item['source'] or 'N/A'}\n{item['sujet']}"
                        chunks.append(Chunk(
                            text=txt,
                            metadata=ChunkMetadata(
                                document_name=filename,
                                family_type="C-texte-libre",
                                sheet_name=sheet_name,
                                block_range=f"{table_r0}-{table_r1}",
                                block_title=item['section'] or titre_bloc,
                                **merged_academic
                            )
                        ))

                # --- CAS 2 : Famille D (Planning / Soutenances activé via le nom du fichier) ---
                elif is_planning:
                    titre = titre_bloc or f"Planning Soutenances ({sheet_name})"
                    soutenances = ExcelBlockParsers.parse_planning_soutenance_block(grid, titre)
                    
                    if soutenances:
                        for rec in soutenances:
                            txt = (
                                f"Soutenance PFE [{rec['bloc_titre']}]\n"
                                f"Salle: {rec['salle']} | Date: {rec['date']} | Créneau: {rec['creneau']}\n"
                                f"Projet: {rec['n_projet']} | Président: {rec['president']} | Membres: {rec['membres']}"
                            )
                            chunks.append(Chunk(
                                text=txt,
                                metadata=ChunkMetadata(
                                    document_name=filename,
                                    family_type="D",
                                    sheet_name=sheet_name,
                                    block_range=f"{table_r0}-{table_r1}",
                                    block_title=rec['bloc_titre'],
                                    **merged_academic
                                )
                            ))
                    else:
                        for row in grid:
                            row_txt = " | ".join([str(v) for v in row if v is not None and str(v).strip() != ""])
                            if row_txt.strip():
                                chunks.append(Chunk(
                                    text=f"[\n{titre}\n] {row_txt}",
                                    metadata=ChunkMetadata(
                                        document_name=filename,
                                        family_type="D",
                                        sheet_name=sheet_name,
                                        block_range=f"{table_r0}-{table_r1}",
                                        block_title=titre,
                                        **merged_academic
                                    )
                                ))

                # --- CAS 3 : Famille C (Tableau Plat standard / Liste Étudiants nettoyée) ---
                else:
                    header, records = ExcelBlockParsers.parse_flat_block(grid)
                    for rec in records:
                        rec_str = " | ".join([f"{k}: {v}" for k, v in rec.items() if v])
                        if rec_str.strip():
                            txt = f"[{titre_bloc}]\n{rec_str}" if titre_bloc else rec_str
                            chunks.append(Chunk(
                                text=txt,
                                metadata=ChunkMetadata(
                                    document_name=filename,
                                    family_type="C",
                                    sheet_name=sheet_name,
                                    block_range=f"{table_r0}-{table_r1}",
                                    block_title=titre_bloc,
                                    **merged_academic
                                )
                            ))

        return chunks