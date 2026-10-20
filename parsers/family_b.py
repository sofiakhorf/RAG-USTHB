# --- 1. Bibliothèques standards Python ---
import os
import re
import logging
from typing import List, Optional, Dict, Tuple

# --- 2. Bibliothèques externes ---
import pymupdf  # (pour l'extraction PDF avancée : texte, dict, tables, dessins)

from core import Chunk, ChunkMetadata, BaseFamilyParser, ParserRegistry
from core.utils import SystemUtils, AcademicMetadataExtractor
from parsers.fallback import FallbackParser

logger = logging.getLogger(__name__)

# =============================================================================
# Helpers
# =============================================================================

ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F]+")


def strip_arabic(text: str) -> str:
    """Remove residual Arabic runs left on otherwise-French pages.

    FIX: the original code only ran this on a throw-away `text_simple`
    variable used for the arabic-page/signature-page checks. The text that
    actually ends up in chunks (extracted via `page.get_text("dict")`) never
    went through it, so bidi leftovers survived into the corpus.
    """
    return ARABIC_RE.sub("", text)


# -----------------------------------------------------------------------------
# Formation / niveau detection
#
# FIX: the original `formation = "ISIL" if "isil" in file_path.lower() else
# "BIGDATAA"` silently mislabels every formation that isn't ISIL as
# "BIGDATAA / master" — confirmed on the "Tronc Commun Ingénieur" canevas,
# which has nothing to do with BigData and is not a master's degree. Wrong
# metadata is worse than missing metadata in a RAG index (it actively
# misleads retrieval/filtering), so unknown formations are now tagged
# "UNKNOWN" instead of guessed.
#
# Detection order:
#   1. Filename hints for formations we know for certain (fast path).
#   2. Content-based heuristics against the cover page(s).
#   3. UNKNOWN, logged, rather than a wrong guess.
# -----------------------------------------------------------------------------

FORMATION_FILENAME_HINTS: Dict[str, Tuple[str, str]] = {
    "isil": ("ISIL", "licence"),
    "bigdataa": ("BIGDATAA", "master"),
    "bigdata": ("BIGDATAA", "master"),
}

# (pattern on cover-page text, formation or None to auto-extract, niveau)
FORMATION_CONTENT_HINTS = [
    (re.compile(r"tronc\s+commun.{0,20}ing[ée]nieur", re.I), "TC-INGENIEUR", "cycle_preparatoire"),
    (re.compile(r"ing[ée]nieur\s+d.?[ée]tat", re.I), None, "ingenieur"),
    (re.compile(r"licence\s+professionnalisante", re.I), None, "licence"),
    (re.compile(r"\bmaster\b", re.I), None, "master"),
]

# Formation acronyms are conventionally given in parentheses on the cover
# page, e.g. "...des Systèmes d'Information et des Logiciels (ISIL)".
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
        "FamilyB: could not identify formation/niveau for %s — tagging UNKNOWN "
        "instead of defaulting to a guess. Consider extending "
        "FORMATION_FILENAME_HINTS / FORMATION_CONTENT_HINTS.",
        file_path,
    )
    return "UNKNOWN", "UNKNOWN"


# -----------------------------------------------------------------------------
# Structural anchors.
#
# Both sample families (TC canevas and ISIL cahier des charges) use the same
# fixed institutional template for each "fiche matière":
#     Semestre : <n>
#     Unité d'enseignement : <...>
#     Matière : <...>
# These anchors are far more reliable than a font-size heuristic and are used
# in preference to it. Font size is kept only for the coarse, document-level
# chapter title (current_h1), which is not part of this fixed template.
# -----------------------------------------------------------------------------

# Matches "Semestre : S3", "Semestre 1 :", "1- Semestre 1 :", "Semestre : 01"...
SEMESTRE_BOUNDARY_RE = re.compile(r"^(?:\d+[\-.)]\s*)?semestre\b\s*:?\s*(.*)$", re.I)
SEMESTRE_NUM_RE = re.compile(r"semestre\s*:?\s*s?\s*0*([0-9]+)", re.I)
UE_LINE_RE = re.compile(r"^unit[ée]\s+d.enseignement\s*:?\s*(.+)$", re.I)
# FIX: the previous h3 regex also matched any line starting with "<digit> -"
# or the bare word "Code :" ANYWHERE in a chunk's body. Since "Contenu de la
# matière" sections are full of numbered sub-items ("1- Introduction",
# "2- Définitions", ...), that regex fired constantly on ordinary body text,
# overwriting the tracked matière name mid-fiche. Only the literal
# "Matière : ..." / "Module : ..." anchor is used now.
MATIERE_LINE_RE = re.compile(r"^(?:intitul[ée]\s+d[eu]\s+la?\s+)?(?:mati[èe]re|module)\s*:?\s*(.+)$", re.I)


def normalize_semestre(raw_text: str) -> Optional[str]:
    m = SEMESTRE_NUM_RE.search(raw_text)
    return f"S{int(m.group(1))}" if m else None


def build_metadata(**kwargs) -> ChunkMetadata:
    """Construct ChunkMetadata defensively.

    `semestre` is new. If the ChunkMetadata model in this codebase hasn't
    been extended with that field yet, drop it rather than raising —
    the semester is always still embedded in the chunk's text breadcrumb.
    """
    try:
        return ChunkMetadata(**kwargs)
    except TypeError:
        kwargs.pop("semestre", None)
        return ChunkMetadata(**kwargs)


@ParserRegistry.register("B")
class FamilyBParser(BaseFamilyParser):

    SIGNATURE_MAX_TEXT_LEN = 80
    H1_FONT_MIN_SIZE = 15

    def parse(
        self,
        file_path: str,
        document_title: Optional[str] = None,
        effective_start_line: int = 0,
    ) -> List[Chunk]:
        clean_title = document_title if document_title else os.path.basename(file_path)
        chunks: List[Chunk] = []
        doc = pymupdf.open(file_path)

        # Formation/niveau are document-level, not page-level: read the cover.
        cover_text = "".join(doc[i].get_text() for i in range(min(2, len(doc))))
        formation, niveau = detect_formation_niveau(file_path, cover_text)

        current_h1 = ""
        current_semestre: Optional[str] = None
        current_ue = ""
        current_matiere = ""
        fiche_buffer: List[str] = []

        def flush(page_no: int) -> None:
            """Close whatever fiche is currently being accumulated.

            FIX: in the original code, the heading-detection elif-ladder ran
            BEFORE this check, so by the time a fiche was flushed on hitting
            a new "Matière :" line, `current_h3` (the matière name) had
            *already* been overwritten with the NEW matière — every closed
            chunk was mislabeled with the matière that comes after it, not
            its own. Flushing now always happens with the still-untouched
            metadata of the fiche being closed; state is only updated
            afterwards, once the old buffer is safely on its way to `chunks`.
            """
            nonlocal fiche_buffer
            if not fiche_buffer:
                return
            breadcrumb = (
                f"{(niveau or '').upper()} {formation} > "
                f"{current_semestre or '?'} > {current_ue or '?'} > {current_matiere or '?'}\n"
            )
            chunks.append(Chunk(
                text=breadcrumb + "\n".join(fiche_buffer),
                metadata=build_metadata(
                    document_name=clean_title,
                    family_type="B",
                    formation=formation,
                    page=page_no,
                    ue=current_ue or None,
                    matiere=current_matiere or None,
                    semestre=current_semestre,
                ),
            ))
            fiche_buffer = []

        for idx, page in enumerate(doc):
            try:
                text_simple = page.get_text()
            except Exception:
                logger.exception("FamilyB: failed to read page %s of %s", idx + 1, file_path)
                continue

            # Filtre pages en arabe
            if SystemUtils.is_arabic_page(text_simple):
                continue

            # Filtre pages de signatures / tampons
            if len(text_simple.strip()) < self.SIGNATURE_MAX_TEXT_LEN and len(page.get_images()) > 0:
                chunks.append(Chunk(
                    text=f"[{formation}] Page visée et approuvée par les autorités.",
                    metadata=build_metadata(
                        document_name=clean_title,
                        family_type="B",
                        formation=formation,
                        page=idx + 1,
                    ),
                ))
                continue

            # ---------------------------------------------------------------
            # Text blocks are fetched once per page and reused both to locate
            # semester headings (for accurate table labeling, right below)
            # and for the spatial text pass further down.
            # ---------------------------------------------------------------
            blocks = page.get_text("dict")["blocks"]
            text_blocks = [b for b in blocks if "lines" in b]

            # Position (top y) of each "Semestre N" heading on this page, so
            # that when two recap tables share one page (e.g. Semestre 5 and
            # Semestre 6 stacked on the same sheet, which happens in the
            # ISIL cahier des charges) each table is matched to the heading
            # directly above it rather than both being tagged with whichever
            # "Semestre" text appears first anywhere on the page.
            semestre_anchors: List[Tuple[float, str]] = []
            for b in text_blocks:
                for line in b["lines"]:
                    line_text = "".join(s["text"] for s in line["spans"]).strip()
                    if re.search(r"[\-.]{4,}", line_text):
                        continue  # table-of-contents leader line
                    if SEMESTRE_BOUNDARY_RE.match(line_text):
                        sem_val = normalize_semestre(line_text)
                        if sem_val:
                            semestre_anchors.append((b["bbox"][1], sem_val))
            semestre_anchors.sort(key=lambda t: t[0])

            def semestre_for_y(y_top: float) -> Optional[str]:
                candidate = None
                for anchor_y, sem in semestre_anchors:
                    if anchor_y <= y_top + 1:  # heading must sit above the table
                        candidate = sem
                    else:
                        break
                return candidate or current_semestre

            # ---------------------------------------------------------------
            # 2. EXTRACTION ET TRAITEMENT DES TABLEAUX
            # ---------------------------------------------------------------
            table_bboxes = []
            try:
                tabs = page.find_tables()
            except Exception:
                logger.exception("FamilyB: table extraction failed on page %s of %s", idx + 1, file_path)
                tabs = []

            for tab in tabs:
                table_bboxes.append(tab.bbox)
                rows = tab.extract()

                cleaned_rows = []
                for row in rows:
                    cells = [strip_arabic(re.sub(r"\s+", " ", cell.strip())) for cell in row if cell and cell.strip()]
                    if cells:
                        cleaned_rows.append(" | ".join(cells))

                # A "recap" table is one of the semester-organization tables
                # from section II ("Fiche d'organisation semestrielle") —
                # recognizable by a "Crédits"/"Coeff" style header. They never
                # contain a "Matière :" anchor, so left in the generic flow
                # below they would silently merge into whatever fiche happens
                # to be open — often several pages away and about an
                # unrelated matière — and inherit its metadata. They are
                # emitted as their own, clearly-tagged chunk instead.
                is_recap_table = any(
                    cell and re.search(r"cr[ée]dits?", cell, re.I)
                    for row in rows[:2] for cell in row if cell
                )

                if is_recap_table:
                    sem = semestre_for_y(tab.bbox[1])
                    if cleaned_rows:
                        chunks.append(Chunk(
                            text=(
                                f"{(niveau or '').upper()} {formation} > {sem or '?'} > "
                                f"Organisation semestrielle des enseignements\n"
                                + "\n".join(cleaned_rows)
                            ),
                            metadata=build_metadata(
                                document_name=clean_title,
                                family_type="B",
                                formation=formation,
                                page=idx + 1,
                                semestre=sem,
                            ),
                        ))
                else:
                    fiche_buffer.extend(cleaned_rows)

            # ---------------------------------------------------------------
            # 3. EXTRACTION DU TEXTE AVEC TRI SPATIAL (Gère les colonnes)
            # (`blocks` / `text_blocks` were already fetched above.)
            # ---------------------------------------------------------------
            sorted_blocks = sorted(
                text_blocks,
                key=lambda b: (round(b["bbox"][1], 1), round(b["bbox"][0], 1)),
            )

            for block in sorted_blocks:
                bx0, by0, bx1, by1 = block["bbox"]

                # FIX: original compared against undefined `py0`/`py1`
                # (should have been `by0`/`by1`) — a guaranteed NameError
                # crash on every page that contains at least one table
                # *and* a text block outside it (i.e. almost every real page).
                is_inside_table = any(
                    bx0 >= tx0 and by0 >= ty0 and bx1 <= tx1 and by1 <= ty1
                    for tx0, ty0, tx1, ty1 in table_bboxes
                )
                if is_inside_table:
                    continue  # déjà extrait via find_tables()

                for line in block["lines"]:
                    # FIX: iterate per LINE, not per span. Anchors and even
                    # ordinary sentences are routinely split across spans
                    # (e.g. bold "Semestre :" + plain " S3" as two spans on
                    # one line) — matching per span silently lost data (the
                    # semester number vanished into an un-matched trailing
                    # span) and produced one buffer entry per span instead of
                    # per visual line, fragmenting the chunk text.
                    line_text = "".join(span["text"] for span in line["spans"]).strip()
                    line_text = strip_arabic(line_text).strip()
                    if not line_text:
                        continue
                    max_size = max((span["size"] for span in line["spans"]), default=0)

                    # Table-of-contents lines ("1- Semestre 1 ----- 18") match
                    # the same boundary pattern as real fiche headers; the
                    # dot/dash leader is the tell that this is a TOC entry,
                    # not an actual "Semestre :" anchor.
                    is_toc_line = bool(re.search(r"[\-.]{4,}", line_text))
                    sem_boundary = None if is_toc_line else SEMESTRE_BOUNDARY_RE.match(line_text)
                    sem_val = normalize_semestre(line_text) if sem_boundary else None
                    is_new_matiere = bool(MATIERE_LINE_RE.match(line_text))

                    # Close the fiche in progress *before* touching any
                    # tracked heading, so it is closed under its own metadata.
                    if (sem_boundary and sem_val) or is_new_matiere:
                        flush(idx + 1)

                    if max_size > self.H1_FONT_MIN_SIZE:
                        current_h1 = line_text

                    if sem_boundary and sem_val:
                        current_semestre = sem_val
                        current_ue = ""
                        current_matiere = ""

                    m_ue = UE_LINE_RE.match(line_text)
                    if m_ue:
                        current_ue = m_ue.group(1).strip()

                    if is_new_matiere:
                        current_matiere = MATIERE_LINE_RE.match(line_text).group(1).strip()

                    fiche_buffer.append(line_text)

        # ---------------------------------------------------------------
        # 4. Traitement du dernier buffer en fin de document
        # FIX: previously this final chunk omitted `matiere=` (and semestre)
        # while every other chunk included it — inconsistent schema for the
        # very last fiche of the document.
        # ---------------------------------------------------------------
        flush(len(doc))

        doc.close()
        return chunks