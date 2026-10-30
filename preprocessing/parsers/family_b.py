# --- 1. Bibliothèques standards Python ---
import os
import re
import logging
from typing import List, Optional, Dict, Tuple

# --- 2. Bibliothèques externes ---
import pymupdf  # (extraction PDF : texte, blocs, tableaux)

from core import Chunk, ChunkMetadata, BaseFamilyParser, ParserRegistry
from core.utils import SystemUtils

logger = logging.getLogger(__name__)

# =============================================================================
# Helpers génériques
# =============================================================================

ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F]+")
# Glyphes privés utilisés par les puces Wingdings/Symbol des canevas Word :
# ils ne portent aucune information et polluent le texte indexé.
PRIVATE_USE_RE = re.compile(r"[\ue000-\uf8ff]")
INVISIBLE_RE = re.compile(r"[\u00ad\u200b-\u200f\u202a-\u202e\ufeff]")

ANNEE_RE = re.compile(r"(\d{4})\s*[/-]\s*(\d{4})")
NIVEAU_RE = re.compile(r"(licence|master|ing[ée]nieur|cycle\s+pr[ée]paratoire|doctorat)", re.I)

NIVEAU_LABELS = {
    "licence": "Licence",
    "master": "Master",
    "ingenieur": "Ingénieur",
    "cycle_preparatoire": "Cycle préparatoire",
}


def strip_arabic(text: str) -> str:
    """Supprime les résidus arabes d'une page par ailleurs française."""
    return ARABIC_RE.sub("", text)


def clean_line(text: str) -> str:
    """Nettoie une ligne de texte PDF (glyphes privés, espaces, puces)."""
    text = PRIVATE_USE_RE.sub("", text)
    text = INVISIBLE_RE.sub("", text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    # Puces isolées en début de ligne ("•", "·", "✓", "-" orphelin)
    text = re.sub(r"^[\s•·▪◦✓✔\-–—]+", "", text)
    return text.strip()


# -----------------------------------------------------------------------------
# Formation / niveau / année
# -----------------------------------------------------------------------------

FORMATION_FILENAME_HINTS: Dict[str, Tuple[str, str]] = {
    "isil": ("ISIL", "licence"),
    "bigdataa": ("BIGDATAA", "master"),
    "bigdata": ("BIGDATAA", "master"),
}

FORMATION_CONTENT_HINTS = [
    (re.compile(r"tronc\s+commun.{0,30}ing[ée]nieur", re.I), "TC-INGENIEUR", "cycle_preparatoire"),
    (re.compile(r"ing[ée]nieur\s+d.?[ée]tat", re.I), None, "ingenieur"),
    (re.compile(r"licence\s+professionnalisante", re.I), None, "licence"),
    (re.compile(r"\bmaster\b", re.I), None, "master"),
]

ACRONYM_RE = re.compile(r"\(([A-ZÀ-Ö]{2,12})\)")


def detect_formation_niveau(file_path: str, cover_text: str) -> Tuple[str, str]:
    lower_name = os.path.basename(file_path).lower()
    for key, value in FORMATION_FILENAME_HINTS.items():
        if key in lower_name:
            return value

    for pattern, formation, niveau in FORMATION_CONTENT_HINTS:
        if pattern.search(cover_text):
            if formation is None:
                m = ACRONYM_RE.search(cover_text)
                formation = m.group(1) if m else "UNKNOWN"
            return formation, niveau

    logger.warning(
        "FamilyB: formation/niveau introuvable pour %s — marqué UNKNOWN.", file_path
    )
    return "UNKNOWN", "UNKNOWN"


def detect_annee_universitaire(doc: "pymupdf.Document") -> Optional[str]:
    """Année universitaire majoritaire du document.

    Le canevas ISIL affiche « 2012-2013 » sur la page de garde (en-tête
    obsolète) alors que la couverture et les 79 autres pages indiquent
    2021-2022 : on retient donc la valeur la plus fréquente, pas la première.
    """
    counts: Dict[str, int] = {}
    for page in doc:
        try:
            text = page.get_text()
        except Exception:
            continue
        for m in ANNEE_RE.finditer(text):
            y1, y2 = int(m.group(1)), int(m.group(2))
            if y2 != y1 + 1 or not (1990 <= y1 <= 2100):
                continue
            label = f"{y1}/{y2}"
            counts[label] = counts.get(label, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]


DOCUMENT_NAMES = {
    "ISIL": "Offre de formation Licence ISIL",
    "TC-INGENIEUR": "Offre de formation Tronc Commun Ingénieur",
}


# -----------------------------------------------------------------------------
# Ancrages de structure
# -----------------------------------------------------------------------------

# "Semestre : S3" / "Semestre : 01" (les libellés de tableaux
# "1- Semestre 1 :" et les lignes de sommaire à points de suite sont exclus).
SEMESTRE_ANCHOR_RE = re.compile(r"^Semestre\s*:\s*(?:S\s*)?0*([1-6])\s*$", re.I)
UE_LINE_RE = re.compile(r"^Unit[ée]\s+d.enseignement\s*:?\s*(.*)$", re.I)
MATIERE_LINE_RE = re.compile(
    r"^(?:intitul[ée]\s+d[eu]\s+la?\s+)?(?:mati[èe]re|module)\s*:\s*(.+)$", re.I
)
CREDITS_LINE_RE = re.compile(r"^Cr[ée]dits?\s*:\s*(\d+)", re.I)
COEFFICIENT_LINE_RE = re.compile(r"^Coefficients?\s*:\s*(\d+)", re.I)

# En-têtes / pieds de page des deux canevas.
HEADER_RES = [
    re.compile(r"^Etablissement\s*:\s*USTHB$", re.I),
    re.compile(r"^Intitul[ée]\s+de\s+la\s+licence\s*:\s*ISIL$", re.I),
    re.compile(r"^Page\s+\d+$", re.I),
    re.compile(r"^Ann[ée]e\s+universitaire\s*:\s*\d{4}\s*[-/]\s*\d{4}$", re.I),
    re.compile(r"^TRONC\s+COMMUN\s+ING[ÉE]NIEUR.*$", re.I),
    re.compile(r"^Annexe\s+de\s+l.arr[êe]t[ée].*$", re.I),
    re.compile(r"^fixant\s+le\s+programme.*$", re.I),
    re.compile(r"^du\s+domaine\s*[«\"].*$", re.I),
    re.compile(r"^Date,\s*signature\s+et\s+visas?.*$", re.I),
]

# Sections qui suivent la dernière fiche : visas, conventions, lettres types.
STOP_RE = re.compile(
    r"^(?:[IVX]+\s*[-–.]\s*)?(?:Accords?\s*/\s*Conventions?|Avis\s+et\s+visas|"
    r"LETTRE\s+D.INTENTION|Conventions?\s+et\s+accords?)\b",
    re.I,
)


def is_header_line(line: str) -> bool:
    return any(r.match(line) for r in HEADER_RES)


def normalize_semestre(raw_text: str) -> Optional[str]:
    m = SEMESTRE_ANCHOR_RE.match(raw_text)
    return f"S{int(m.group(1))}" if m else None


UE_LABELS = (
    ("fondamentale", "Fondamentale"),
    ("méthodologique", "Méthodologique"),
    ("methodologique", "Méthodologique"),
    ("découverte", "Découverte"),
    ("decouverte", "Découverte"),
    ("transversale", "Transversale"),
)


def normalize_ue(raw: Optional[str]) -> Optional[str]:
    """Uniformise les libellés TC (« fondamentale. » → « Fondamentale »)."""
    if not raw:
        return None
    value = raw.strip().rstrip(".").strip()
    lower = value.lower()
    for key, label in UE_LABELS:
        if lower.startswith(key):
            if "ut" in lower and label == "Transversale":
                return "Transversale (UT)"
            return label
    return value or None


def build_metadata(**kwargs) -> ChunkMetadata:
    """Construit ChunkMetadata sans échouer si un champ optionnel manque."""
    try:
        return ChunkMetadata(**kwargs)
    except TypeError:
        kwargs.pop("semestre", None)
        return ChunkMetadata(**kwargs)


def split_lines(lines: List[str], limit: int) -> List[List[str]]:
    """Découpe une liste de lignes en blocs d'au plus `limit` caractères."""
    parts: List[List[str]] = []
    current: List[str] = []
    size = 0
    for line in lines:
        if current and size + len(line) + 1 > limit:
            parts.append(current)
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        parts.append(current)
    return parts


@ParserRegistry.register("B")
class FamilyBParser(BaseFamilyParser):
    """Canevas d'offre de formation (fiches matières + tableaux semestriels).

    Deux sources de la famille B partagent le même template :
      * Cahier des charges Licence ISIL (26 fiches, 2021/2022) ;
      * Canevas Tronc Commun Ingénieur (30 fiches, 2023/2024).

    Chaque fiche matière devient un chunk autonome (contexte licence /
    semestre / UE / matière / année répété), chaque tableau récapitulatif de
    semestre devient un chunk unique aplati (une ligne par matière), et les
    pages de garde, sommaires, prose institutionnelle et visas sont exclues.
    """

    MAX_CHUNK_CHARS = 6000
    MIN_CHUNK_CHARS = 150
    JUNK_PAGE_MAX_MEAN_LINE = 12
    JUNK_PAGE_MIN_LINES = 200

    def parse(
        self,
        file_path: str,
        document_title: Optional[str] = None,
        effective_start_line: int = 0,
    ) -> List[Chunk]:
        chunks: List[Chunk] = []
        try:
            doc = pymupdf.open(file_path)
        except Exception:
            logger.exception("FamilyB: impossible d'ouvrir %s", file_path)
            return chunks

        try:
            cover_text = "".join(
                doc[i].get_text() for i in range(min(4, len(doc)))
            )
            formation, niveau = detect_formation_niveau(file_path, cover_text)
            niveau_label = NIVEAU_LABELS.get(niveau, niveau.title() if niveau else "UNKNOWN")
            annee_univ = detect_annee_universitaire(doc)
            document_name = DOCUMENT_NAMES.get(
                formation,
                document_title or os.path.basename(file_path),
            )

            base_meta = dict(
                document_name=document_name,
                family_type="B",
                formation=formation,
                niveau=niveau_label,
                annee_universitaire=annee_univ,
            )

            fiches, table_chunks = self._extract_document(
                doc, base_meta, formation, niveau_label, annee_univ
            )
            chunks.extend(table_chunks)
            chunks.extend(fiches)
        finally:
            doc.close()

        return chunks

    # -------------------------------------------------------------------------
    # Extraction principale
    # -------------------------------------------------------------------------
    def _extract_document(
        self,
        doc: "pymupdf.Document",
        base_meta: dict,
        formation: str,
        niveau_label: str,
        annee_univ: Optional[str],
    ) -> Tuple[List[Chunk], List[Chunk]]:
        fiches: List[Chunk] = []
        tables: List[Chunk] = []

        current: Optional[dict] = None
        pending_header: List[str] = []
        buf: List[str] = []
        stopped = False

        def open_fiche(page_no: int, matiere: str) -> dict:
            semestre = ue = credits = coef = None
            for line in pending_header:
                m = SEMESTRE_ANCHOR_RE.match(line)
                if m:
                    semestre = f"S{int(m.group(1))}"
                    continue
                m = UE_LINE_RE.match(line)
                if m:
                    ue = normalize_ue(m.group(1).strip() or None)
                    continue
                m = CREDITS_LINE_RE.match(line)
                if m:
                    credits = int(m.group(1))
                    continue
                m = COEFFICIENT_LINE_RE.match(line)
                if m:
                    coef = int(m.group(1))
            return {
                "page": page_no,
                "semestre": semestre,
                "ue": ue,
                "matiere": matiere,
                "credits": credits,
                "coef": coef,
            }

        def close_fiche() -> None:
            nonlocal buf
            if current is None:
                buf = []
                return
            body = [line for line in buf if line]
            if body:
                fiches.extend(
                    self._build_fiche_chunk(
                        current, body, base_meta, niveau_label, formation, annee_univ
                    )
                )
            buf = []

        for page_index, page in enumerate(doc):
            page_no = page_index + 1
            try:
                page_text = page.get_text()
            except Exception:
                logger.exception("FamilyB: lecture page %s impossible (%s)", page_no, doc.name)
                continue

            lines = self._page_lines(page)
            if self._is_junk_page(lines):
                continue

            # --- tableaux récapitulatifs de semestre -------------------------
            table_bboxes = []
            try:
                found_tables = page.find_tables().tables
            except Exception:
                found_tables = []
            for tab in found_tables:
                try:
                    rows = tab.extract()
                except Exception:
                    continue
                # pymupdf détecte aussi des mises en page (listes de chapitres,
                # bibliographies) comme des « tableaux » : seuls les vrais
                # récapitulatifs semestriels (UE / Crédits / Coeff / VHS) sont
                # traités ici, le reste doit rester dans le corps de la fiche.
                if not self._is_recap_table(rows):
                    continue
                table_bboxes.append(tab.bbox)
                semestre = self._semestre_for_table(page, tab.bbox)
                if semestre is None:
                    semestre = current["semestre"] if current else None
                if semestre is None:
                    continue
                table_lines = self._flatten_table(rows, formation, semestre)
                if table_lines:
                    tables.append(
                        self._build_table_chunk(
                            semestre, table_lines, page_no, base_meta, niveau_label,
                            formation, annee_univ,
                        )
                    )

            if stopped:
                continue

            for line in lines:
                if not line:
                    continue
                if is_header_line(line):
                    continue
                if table_bboxes and self._is_inside_table(page, line, table_bboxes):
                    continue
                if current is not None and STOP_RE.match(line):
                    stopped = True
                    break

                m_sem = SEMESTRE_ANCHOR_RE.match(line)
                if m_sem:
                    pending_header.append(line)
                    continue

                m_ue = UE_LINE_RE.match(line)
                if m_ue:
                    pending_header.append(line)
                    continue

                m_mat = MATIERE_LINE_RE.match(line)
                if m_mat:
                    close_fiche()
                    pending_header.append(line)
                    current = open_fiche(page_no, m_mat.group(1).strip())
                    pending_header = []
                    continue

                if current is None:
                    # Prose institutionnelle / page de garde : ignorée.
                    continue

                m_cred = CREDITS_LINE_RE.match(line)
                if m_cred:
                    current["credits"] = int(m_cred.group(1))
                m_coef = COEFFICIENT_LINE_RE.match(line)
                if m_coef:
                    current["coef"] = int(m_coef.group(1))
                if pending_header:
                    buf.extend(pending_header)
                    pending_header = []
                if not buf or buf[-1] != line:
                    buf.append(line)

        close_fiche()
        return fiches, tables

    # -------------------------------------------------------------------------
    # Lecture de page
    # -------------------------------------------------------------------------
    def _page_lines(self, page: "pymupdf.Page") -> List[str]:
        """Lignes nettoyées de la page, hors tableaux."""
        lines: List[str] = []
        try:
            raw_lines = page.get_text().split("\n")
        except Exception:
            return lines
        for raw in raw_lines:
            line = clean_line(strip_arabic(raw))
            if line:
                lines.append(line)
        return lines

    def _is_junk_page(self, lines: List[str]) -> bool:
        if not lines:
            return True
        if len(lines) < self.JUNK_PAGE_MIN_LINES:
            return False
        mean_len = sum(len(line) for line in lines) / len(lines)
        return mean_len < self.JUNK_PAGE_MAX_MEAN_LINE

    @staticmethod
    def _is_inside_table(page: "pymupdf.Page", line: str, bboxes) -> bool:
        """Vrai si la ligne appartient à un tableau déjà extrait.

        Les tableaux récapitulatifs sont traités séparément ; leur texte ne
        doit pas être recopié dans la fiche matière voisine.
        """
        if not bboxes:
            return False
        try:
            rects = page.search_for(line)
        except Exception:
            return False
        for rect in rects:
            for x0, y0, x1, y1 in bboxes:
                if (
                    rect.x0 >= x0 - 1
                    and rect.y0 >= y0 - 1
                    and rect.x1 <= x1 + 1
                    and rect.y1 <= y1 + 1
                ):
                    return True
        return False

    @staticmethod
    def _semestre_for_table(page: "pymupdf.Page", bbox) -> Optional[str]:
        """Semestre du libellé « Semestre N » situé juste au-dessus du tableau."""
        _, ty0, _, _ = bbox
        best = None
        for n in range(1, 7):
            for rect in page.search_for(f"Semestre {n}"):
                if rect.y0 <= ty0 + 2 and rect.y0 > (best[0] if best else -1):
                    best = (rect.y0, n)
        return f"S{best[1]}" if best else None

    # -------------------------------------------------------------------------
    # Fiches matières
    # -------------------------------------------------------------------------
    def _build_fiche_chunk(
        self,
        fiche: dict,
        body_lines: List[str],
        base_meta: dict,
        niveau_label: str,
        formation: str,
        annee_univ: Optional[str],
    ) -> List[Chunk]:
        semestre = fiche.get("semestre") or "?"
        ue = fiche.get("ue") or ""
        matiere = fiche.get("matiere") or ""
        credits = fiche.get("credits")
        coef = fiche.get("coef")

        header_parts = [f"{niveau_label} {formation}", f"Semestre {semestre}"]
        if ue:
            header_parts.append(f"UE {ue}")
        header_parts.append(f"Matière : {matiere}")
        if annee_univ:
            header_parts.append(f"Année universitaire {annee_univ}")
        if credits is not None:
            header_parts.append(f"Crédits {credits}")
        if coef is not None:
            header_parts.append(f"Coefficient {coef}")
        header = " — ".join(header_parts)

        # Retire l'ancrage "Matière : ..." du corps (déjà dans l'en-tête).
        body = [
            line
            for line in body_lines
            if not MATIERE_LINE_RE.match(line)
        ]
        limit = self.MAX_CHUNK_CHARS - len(header) - 40
        parts = split_lines(body, max(limit, 500))

        chunks: List[Chunk] = []
        for index, part in enumerate(parts, 1):
            suffix = f" (partie {index}/{len(parts)})" if len(parts) > 1 else ""
            text = f"{header}{suffix}\n\n" + "\n".join(part)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            chunks.append(
                Chunk(
                    text=text,
                    metadata=build_metadata(
                        **base_meta,
                        page=fiche.get("page"),
                        semestre=semestre if semestre != "?" else None,
                        ue=ue or None,
                        matiere=matiere or None,
                    ),
                )
            )
        return chunks

    # -------------------------------------------------------------------------
    # Tableaux récapitulatifs
    # -------------------------------------------------------------------------
    @staticmethod
    def _is_recap_table(rows: List[list]) -> bool:
        """Vrai uniquement pour un tableau d'organisation semestrielle."""
        if not rows or len(rows) < 3:
            return False
        width = max(len(row) for row in rows)
        if width < 8:
            return False
        header = [
            re.sub(r"\s+", " ", str(cell)).strip()
            for row in rows[:3]
            for cell in row
            if cell
        ]
        has_credits = any(re.search(r"cr[ée]dits?", cell, re.I) for cell in header)
        has_coeff = any(re.match(r"coef", cell, re.I) for cell in header)
        has_ue = any(re.search(r"unit[ée]s?\s+d.enseignement", cell, re.I) for cell in header)
        return has_credits and has_coeff and has_ue

    def _flatten_table(self, rows: List[list], formation: str, semestre: str) -> List[str]:
        if formation == "TC-INGENIEUR":
            return self._flatten_tc_table(rows)
        return self._flatten_isil_table(rows)

    @staticmethod
    def _cell(row: list, index: Optional[int]) -> str:
        if index is None or index >= len(row):
            return ""
        value = row[index]
        if not value:
            return ""
        value = PRIVATE_USE_RE.sub("", str(value))
        value = value.replace("\u00a0", " ")
        value = re.sub(r"\s*\n\s*", " ", value)
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    @staticmethod
    def _find_col(rows: List[list], labels, exact: bool = False) -> Optional[int]:
        for row in rows:
            for idx, cell in enumerate(row):
                if not cell:
                    continue
                value = re.sub(r"\s+", " ", str(cell)).strip().lower()
                for label in labels:
                    if (value == label) if exact else value.startswith(label):
                        return idx
        return None

    def _flatten_isil_table(self, rows: List[list]) -> List[str]:
        vhs_col = self._find_col(rows, ["vhs"])
        coeff_col = self._find_col(rows, ["coeff"])
        credits_col = self._find_col(rows, ["crédits", "credits"])
        continu_col = self._find_col(rows, ["continu"])
        examen_col = self._find_col(rows, ["examen"])
        c_col = self._find_col(rows, ["c"], exact=True)
        td_col = self._find_col(rows, ["td"], exact=True)
        tp_col = self._find_col(rows, ["tp"], exact=True)
        autres_col = self._find_col(rows, ["autres"])

        out: List[str] = []
        current_ue = ""
        for row in rows:
            first = self._cell(row, 0)
            if not first or first.lower().startswith(("unité", "unite")):
                continue
            if re.match(r"^UE\s", first, re.I):
                continue  # "UE fondamentales", "UE Méthodologique"...
            if re.match(r"^UE[A-Z]\d+\s*\(O/P\)", first, re.I):
                current_ue = first.split("(")[0].strip()
                continue
            if first.lower().startswith("total semestre"):
                credits = self._cell(row, credits_col)
                coef = self._cell(row, coeff_col)
                vhs = self._cell(row, vhs_col)
                details = []
                if vhs:
                    details.append(f"VHS {vhs}")
                for label, col in (
                    ("C", c_col), ("TD", td_col), ("TP", tp_col), ("Autres", autres_col)
                ):
                    value = self._cell(row, col)
                    if value and value not in ("-", "/"):
                        details.append(f"{label} {value}")
                if coef:
                    details.append(f"Coefficient {coef}")
                if credits:
                    details.append(f"Crédits {credits}")
                out.append(f"{first} : " + ", ".join(details))
                continue

            parts = [f"- {first}"]
            if current_ue:
                parts.append(f"UE {current_ue}")
            coef = self._cell(row, coeff_col)
            credits = self._cell(row, credits_col)
            if coef:
                parts.append(f"Coefficient {coef}")
            if credits:
                parts.append(f"Crédits {credits}")
            for label, col in (
                ("C", c_col), ("TD", td_col), ("TP", tp_col), ("Autres", autres_col)
            ):
                value = self._cell(row, col)
                if value and value != "-":
                    parts.append(f"{label} {value}")
            vhs = self._cell(row, vhs_col)
            if vhs:
                parts.append(f"VHS {vhs}")
            continu = self._cell(row, continu_col)
            examen = self._cell(row, examen_col)
            if continu and continu not in ("/", "-"):
                parts.append(f"Continu {continu}")
            if examen and examen not in ("/", "-"):
                parts.append(f"Examen {examen}")
            out.append(" | ".join(parts))
        return out

    @staticmethod
    def _format_ue_group(group: str) -> str:
        """« UE Fondamentale Code : UEF 5.5.1 Crédits : 12 … » → lisible."""
        match = re.match(r"^(UE\s+[^ ]+)", group, re.I)
        label = match.group(1) if match else group
        details = []
        code = re.search(r"code\s*:\s*([A-Z0-9.\s]+?)(?:\s+Cr[ée]dits|\s+Coefficients|$)", group, re.I)
        credits = re.search(r"cr[ée]dits\s*:\s*(\d+)", group, re.I)
        coef = re.search(r"coefficients?\s*:\s*(\d+)", group, re.I)
        if code:
            details.append(f"Code {code.group(1).strip()}")
        if credits:
            details.append(f"Crédits {credits.group(1)}")
        if coef:
            details.append(f"Coefficients {coef.group(1)}")
        return f"{label} ({', '.join(details)})" if details else group

    def _flatten_tc_table(self, rows: List[list]) -> List[str]:
        credits_col = self._find_col(rows, ["crédits", "credits"])
        coeff_col = self._find_col(rows, ["coef"])
        vhs_col = self._find_col(rows, ["vhs"])
        continu_col = self._find_col(rows, ["continu"])
        examen_col = self._find_col(rows, ["examen"])
        c_col = self._find_col(rows, ["c"], exact=True)
        td_col = self._find_col(rows, ["td"], exact=True)
        tp_col = self._find_col(rows, ["tp"], exact=True)
        matiere_col = self._find_col(rows, ["intitulés des matières", "intitules des matieres"])
        ue_col = 0 if matiere_col != 0 else None

        out: List[str] = []
        current_ue = ""
        for row in rows:
            group = self._cell(row, ue_col)
            matiere = self._cell(row, matiere_col)
            if group and re.search(r"\bcode\s*:", group, re.I):
                current_ue = self._format_ue_group(group)
            if not matiere:
                if group.lower().startswith("total semestre"):
                    credits = self._cell(row, credits_col)
                    coef = self._cell(row, coeff_col)
                    vhs = self._cell(row, vhs_col)
                    details = []
                    if vhs:
                        details.append(f"VHS {vhs}")
                    for label, col in (("C", c_col), ("TD", td_col), ("TP", tp_col)):
                        value = self._cell(row, col)
                        if value and value not in ("-", "/"):
                            details.append(f"{label} {value}")
                    if coef:
                        details.append(f"Coefficient {coef}")
                    if credits:
                        details.append(f"Crédits {credits}")
                    out.append(f"{group} : " + ", ".join(details))
                continue
            if matiere.lower().startswith(("unités", "unites", "intitulés", "intitules")):
                continue

            parts = [f"- {matiere}"]
            if current_ue:
                parts.append(current_ue)
            credits = self._cell(row, credits_col)
            coef = self._cell(row, coeff_col)
            if coef:
                parts.append(f"Coefficient {coef}")
            if credits:
                parts.append(f"Crédits {credits}")
            for label, col in (("C", c_col), ("TD", td_col), ("TP", tp_col)):
                value = self._cell(row, col)
                if value and value != "-":
                    parts.append(f"{label} {value}")
            vhs = self._cell(row, vhs_col)
            if vhs:
                parts.append(f"VHS {vhs}")
            continu = self._cell(row, continu_col)
            examen = self._cell(row, examen_col)
            if continu and continu not in ("/", "-"):
                parts.append(f"Continu {continu}")
            if examen and examen not in ("/", "-"):
                parts.append(f"Examen {examen}")
            out.append(" | ".join(parts))
        return out

    def _build_table_chunk(
        self,
        semestre: str,
        table_lines: List[str],
        page_no: int,
        base_meta: dict,
        niveau_label: str,
        formation: str,
        annee_univ: Optional[str],
    ) -> Chunk:
        header_parts = [
            f"{niveau_label} {formation}",
            f"Semestre {semestre}",
            "Organisation semestrielle des enseignements",
        ]
        if annee_univ:
            header_parts.append(f"Année universitaire {annee_univ}")
        header = " — ".join(header_parts)
        text = header + "\n\n" + "\n".join(table_lines)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return Chunk(
            text=text,
            metadata=build_metadata(
                **base_meta,
                page=page_no,
                semestre=semestre,
            ),
        )
