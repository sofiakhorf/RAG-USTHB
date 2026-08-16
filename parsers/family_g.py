from core import Chunk, ChunkMetadata, BaseFamilyParser, ParserRegistry
from core.utils import SystemUtils, AcademicMetadataExtractor
from parsers.fallback import FallbackParser



"""
Parser famille G : PV de délibération (jury).

Couvre les DEUX sous-formats de PV rencontrés dans les documents USTHB :

  1) "PV de délibération global"
     -> en-tête sur 2 lignes fusionnées (N°, Matricule, Nom, S1[Moy/Créd],
        S2[Moy/Créd], Annuel[Moy/Créd], Décision du jury)
     -> une décision individuelle par étudiant ("Admis(e) avec dettes",
        "Admis(e) (session rattrapage)", ou case vide)

  2) "PV de délibération dette - Semestre X"
     -> en-tête sur 2 lignes avec des groupes d'UE (ex: C00F0001S, C00M0001S...)
        chacun contenant plusieurs matières + Moyenne UE + Crédit UE
     -> la 1ère colonne combine "N° - NOM Prénom" en une seule cellule
     -> pas de décision individuelle, mais un bilan global en pied de tableau
        ("Nombre total des étudiants / admis / n'ayant pas validé")

Le code d'origine (isdigit() sur le matricule, colonne "Decision" au lieu de
"Décision du jury", en-tête pris sur une seule ligne table[0], moyennes/
crédits jamais retrouvés car aucun nom de colonne ne contenait "Moy") ne
fonctionnait correctement sur AUCUN des deux formats : il perdait les
matricules alphanumériques (ex: 23238PSE2069), ne retrouvait jamais les
notes, et ne produisait aucun chunk sur le format "dette" (fallback
systématique). Voir l'explication détaillée fournie en dehors de ce fichier.
"""

import os
import re
import logging
from typing import Dict, List, Optional

import pdfplumber

logger = logging.getLogger(__name__)


@ParserRegistry.register("G")
class FamilyGParser(BaseFamilyParser):
    """Famille G : PV de délibération (résultats de jury), tous sous-formats."""

    HEADER_RE_ANNEE = re.compile(r"Année\s*Académique\s*:\s*([0-9]{4}/[0-9]{4})")
    HEADER_RE_NIVEAU = re.compile(r"Niveau\s*:\s*([^\n]+)")
    HEADER_RE_SPECIALITE = re.compile(r"Spécialité\s*:\s*([^\n]+)")
    HEADER_RE_FILIERE = re.compile(r"Filière\s*:\s*([^\n]+)")
    HEADER_RE_SEMESTRE = re.compile(r"Semestre\s*(\d+)")
    HEADER_RE_ARRETE = re.compile(r"Arrêté.*?formation\s*:\s*([^\n]+)")
    FOOTER_RE_TOTAL = re.compile(r"Nombre total des [ée]tudiants\s*:?\s*(\d+)")
    FOOTER_RE_ADMIS = re.compile(r"Nombre total [ée]tudiants admis\s*:?\s*(\d+)")
    FOOTER_RE_NONVALIDE = re.compile(r"n[’']ayant pas valid[ée]\s*(\d+)")

    def parse(self, file_path: str, document_title: Optional[str] = None) -> List[Chunk]:
        # --- AJOUT : Détermination du titre propre ---
        clean_title = document_title if document_title else os.path.basename(file_path)
        try:
            with pdfplumber.open(file_path) as pdf:
                full_text = "\n".join((p.extract_text() or "") for p in pdf.pages)
                doc_meta = self._extract_document_meta(full_text)

                last_columns: Optional[List[str]] = None
                last_fmt: Optional[str] = None

                for idx, page in enumerate(pdf.pages):
                    raw_table = page.extract_table()
                    if not raw_table:
                        continue

                    header_rows, data_rows = self._split_header(raw_table)

                    if header_rows:
                        columns = self._flatten_header(header_rows)
                        fmt = "dette" if self._is_dette_format(columns) else "global"
                        last_columns, last_fmt = columns, fmt
                    elif last_columns is not None:
                        # Page sans en-tête détecté (rare, ex. suite de tableau) :
                        # on réutilise l'en-tête de la page précédente.
                        columns, fmt = last_columns, last_fmt
                        data_rows = raw_table
                    else:
                        continue

                    if fmt == "global":
                        chunks.extend(self._parse_global_rows(data_rows, columns, clean_title, idx))
                    else:
                        chunks.extend(self._parse_dette_rows(data_rows, columns, clean_title, idx, doc_meta))

                summary_chunk = self._extract_summary(full_text, clean_title)
                if summary_chunk:
                    chunks.append(summary_chunk)

        except Exception as e:
            logger.error(f"Erreur d'extraction sémantique G sur {file_path}: {e}")

        return chunks if chunks else FallbackParser.parse_safe(file_path, "G")

    # ---------------- Métadonnées globales du document ----------------

    def _extract_document_meta(self, text: str) -> Dict[str, str]:
        meta = {}
        for key, pattern in [
            ("annee", self.HEADER_RE_ANNEE),
            ("niveau", self.HEADER_RE_NIVEAU),
            ("specialite", self.HEADER_RE_SPECIALITE),
            ("filiere", self.HEADER_RE_FILIERE),
            ("arrete", self.HEADER_RE_ARRETE),
        ]:
            m = pattern.search(text)
            if m:
                meta[key] = m.group(1).strip()
        sem = self.HEADER_RE_SEMESTRE.search(text)
        if sem:
            meta["semestre"] = sem.group(1)
        return meta

    # ---------------- Détection & fusion des en-têtes multi-lignes ----------------

    def _split_header(self, table: List[List[Optional[str]]]):
        """
        Sépare les 1 à 2 lignes d'en-tête (haut de tableau) des lignes de données.
        Une ligne est une ligne de données si sa/ses première(s) cellule(s)
        ressemble(nt) à un numéro d'ordre ("12") ou à "12 - NOM Prénom".
        """
        header_rows = []
        i = 0
        while i < len(table) and i < 3:
            row = table[i]
            first_cells = [c for c in row[:3] if c]
            looks_like_data = any(
                re.match(r"^\s*\d+\s*-", str(c)) or str(c).strip().isdigit()
                for c in first_cells
            )
            if looks_like_data:
                break
            header_rows.append(row)
            i += 1
        return header_rows, table[i:]

    def _flatten_header(self, header_rows: List[List[Optional[str]]]) -> List[str]:
        """
        Combine 1 ou 2 lignes d'en-tête (cellules fusionnées = None) en une liste
        de labels de colonnes lisibles et uniques. Distingue None (cellule
        fusionnée -> hérite du groupe précédent) de "" (cellule vide mais NON
        fusionnée -> pas d'héritage), ce qui est indispensable pour ne pas
        "faire déborder" un groupe d'UE sur les colonnes suivantes.
        """
        ncols = max(len(r) for r in header_rows)
        normalized = [list(r) + [None] * (ncols - len(r)) for r in header_rows]

        def clean(v):
            if v is None or v == "":
                return v
            return str(v).replace("\n", " ").strip()

        top_row = [clean(v) for v in normalized[0]]
        top_filled, last = [], ""
        for v in top_row:
            if v is None:
                top_filled.append(last)
            elif v == "":
                top_filled.append("")
                last = ""
            else:
                last = v
                top_filled.append(v)
        normalized[0] = top_filled

        for r in range(1, len(normalized)):
            row = [clean(v) for v in normalized[r]]
            filled, last = [], ""
            for j in range(ncols):
                same_group = (
                    j > 0 and top_filled[j] == top_filled[j - 1] and top_filled[j] != ""
                )
                v = row[j]
                if v is None:
                    filled.append(last if same_group else "")
                else:
                    last = v
                    filled.append(v)
            normalized[r] = filled

        labels = []
        for j in range(ncols):
            parts = []
            for r in range(len(normalized)):
                val = normalized[r][j]
                if val and val not in parts:
                    parts.append(val)
            labels.append(" | ".join(parts) if parts else f"col_{j}")

        counts, unique = {}, []
        for lab in labels:
            counts[lab] = counts.get(lab, 0) + 1
            unique.append(lab if counts[lab] == 1 else f"{lab}#{counts[lab]}")
        return unique

    def _is_dette_format(self, columns: List[str]) -> bool:
        joined = " ".join(columns)
        if "Moyenne UE" in joined or "Crédit UE" in joined:
            return True
        return "écision du jury" not in joined and "Moyenne" in joined and "Semestre" in joined

    def _row_to_dict(self, row: List[Optional[str]], columns: List[str]) -> Dict[str, Optional[str]]:
        row = list(row) + [None] * (len(columns) - len(row))
        out = {}
        for j, col in enumerate(columns):
            v = row[j]
            out[col] = v.strip() if isinstance(v, str) else v
        return out

    # ---------------- Format "global" (S1/S2/Annuel + décision du jury) ----------------

    def _parse_global_rows(self, data_rows, columns, document_title: str, page_idx: int) -> List[Chunk]:
        chunks = []
        matricule_col = next((c for c in columns if "Matricule" in c), None)
        nom_col = next((c for c in columns if "Nom" in c), None)
        decision_col = next((c for c in columns if "écision" in c), None)

        for raw_row in data_rows:
            if not raw_row or all(c in (None, "") for c in raw_row):
                continue
            d = self._row_to_dict(raw_row, columns)
            matricule = str(d.get(matricule_col, "") or "").strip()
            nom = str(d.get(nom_col, "") or "").strip()
            if not matricule and not nom:
                continue  # ligne résiduelle (ex: 2e ligne d'en-tête)

            # Une case "décision" vide ne veut PAS forcément dire "admis sans
            # dette" : on ne l'invente pas, on le signale explicitement.
            decision = str(d.get(decision_col, "") or "").strip() or "Non renseignée"

            details = []
            for col, val in d.items():
                if col in (matricule_col, nom_col, decision_col) or val in (None, ""):
                    continue
                if any(k in col for k in ["Moy", "Créd"]):
                    details.append(f"{col}={val}")

            text = (
                f"Délibération jury - Matricule {matricule or 'N/A'} ({nom or 'N/A'}): "
                f"Décision={decision}. Résultats: {', '.join(details)}."
            )
            chunks.append(Chunk(
                text=text,
                metadata=ChunkMetadata(
                    document_name=document_title,
                    family_type="G",
                    matricule=matricule or None,
                    decision=decision,
                    page=page_idx + 1,
                )
            ))
        return chunks

    # ---------------- Format "dette" (détail par UE/matière) ----------------

    def _parse_dette_rows(self, data_rows, columns, document_title: str, page_idx: int, doc_meta: Dict[str, str]) -> List[Chunk]:
        chunks = []
        for raw_row in data_rows:
            if not raw_row or all(c in (None, "") for c in raw_row):
                continue
            first_cell = str(raw_row[0] or "").strip()
            # DOTALL : certains noms sont sur 2 lignes dans la cellule PDF
            # (ex: "6 - BELHADJ ZIANE NADIR\nMOULOUD").
            m = re.match(r"^\s*(\d+)\s*-\s*(.+)$", first_cell, flags=re.DOTALL)
            if not m:
                continue
            numero = m.group(1)
            nom = " ".join(m.group(2).split())
            # Le matricule peut être vide (ligne non encore complétée dans le PV) :
            # on garde quand même l'étudiant plutôt que de le perdre.
            matricule = str(raw_row[1] or "").strip() if len(raw_row) > 1 else ""

            d = self._row_to_dict(raw_row, columns)
            details = []
            for col, val in d.items():
                if val in (None, "") or col in ("col_0", "col_1"):
                    continue
                details.append(f"{col}={val}")

            semestre = doc_meta.get("semestre", "?")
            text = (
                f"Délibération dette (semestre {semestre}) - N°{numero} "
                f"Matricule {matricule or 'N/A'} ({nom}): {', '.join(details)}."
            )
            chunks.append(Chunk(
                text=text,
                metadata=ChunkMetadata(
                    document_name=document_title,
                    family_type="G",
                    matricule=matricule or None,
                    decision=None,
                    page=page_idx + 1,
                )
            ))
        return chunks

    # ---------------- Bilan global (pied de tableau format "dette") ----------------

    def _extract_summary(self, text: str, document_title: str) -> Optional[Chunk]:
        total = self.FOOTER_RE_TOTAL.search(text)
        admis = self.FOOTER_RE_ADMIS.search(text)
        non_valide = self.FOOTER_RE_NONVALIDE.search(text)
        if not (total or admis or non_valide):
            return None
        parts = []
        if total:
            parts.append(f"Total étudiants={total.group(1)}")
        if admis:
            parts.append(f"Admis={admis.group(1)}")
        if non_valide:
            parts.append(f"N'ayant pas validé={non_valide.group(1)}")
        return Chunk(
            text=f"Bilan de la délibération - {', '.join(parts)}.",
            metadata=ChunkMetadata(
                document_name=document_title,
                family_type="G",
                matricule=None,
                decision=None,
                page=-1,
            )
        )