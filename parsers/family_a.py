import os
import re
import logging
from typing import List, Optional, Tuple

import pdfplumber
from docx import Document
from docx.text.paragraph import Paragraph
from docx.table import Table

from core import Chunk, ChunkMetadata, BaseFamilyParser, ParserRegistry
from parsers.fallback import FallbackParser

logger = logging.getLogger(__name__)

# Expressions régulières globales
_FILLER_RUN_RE = re.compile(r'[.\u2026_]{4,}')
_CHECKBOX_RE = re.compile(r'[\u2610\u2611\u2612\u25a2\u25a1]')
_HTML_TAG_RE = re.compile(r'<[^>]+>')


def _dedupe_consecutive(items: List[str]) -> List[str]:
    """Évite la répétition des cellules fusionnées horizontalement."""
    out = []
    for item in items:
        if not out or out[-1] != item:
            out.append(item)
    return out


def _clean_line(text: str) -> str:
    """Supprime les balises HTML/XML résiduelles et normalise les espaces."""
    text = _HTML_TAG_RE.sub('', text)
    return re.sub(r'\s+', ' ', text).strip()


def _is_valid_label(label: str) -> bool:
    """
    Vérifie si une chaîne est un nom de champ/label valide.
    Rejette les phrases longues, paragraphes et textes juridiques/d'attestation.
    """
    clean = label.strip()
    if not clean:
        return False

    # Un label de formulaire dépasse rarement 60 caractères ou 20 mots
    if len(clean) > 60 or len(clean.split()) > 20:
        return False

    # Doit démarrer par une lettre
    clean_start = re.sub(r'^[\*\-\u2022\d\.\s]+', '', clean).strip()
    if not clean_start or not re.match(r'^[A-Za-zÀ-ÿ]', clean_start):
        return False

    # Termes exclus (textes explicatifs / juridiques / attestations)
    lower = clean.lower()
    attestation_keywords = [
        "j'atteste", "je déclare", "je soussigné", "je reconnais",
        "conformément", "article", "arrêté", "reglementation",
        "accusé de réception", "prends connaissance", "n'ouvre plus droit"
    ]
    if any(kw in lower for kw in attestation_keywords):
        return False

    return True


def _split_value_and_label(text_between: str) -> Tuple[str, str]:
    """
    Sépare le texte situé entre deux délimiteurs en (Valeur_Du_Champ_Précédent, Label_Du_Champ_Suivant).
    Gère les options (OUI/NON), cases à cocher, dates et marqueurs de remplissage '____'.
    """
    text = text_between.strip()
    if not text:
        return "", ""

    # Motif pour détecter les options/fillers au début du segment.
    # IMPORTANT : la classe générique [A-Z0-9]{1,4} doit rester
    # SENSIBLE à la casse (pas de re.IGNORECASE) : elle sert à repérer de
    # vrais codes d'option toujours écrits en majuscules dans les
    # formulaires (M1, L1, ING1, ING2...). Avec IGNORECASE, elle avalait
    # aussi des mots ordinaires comme "Date" ou "de" (ex: "Date de départ"
    # perdait "Date de" et ne gardait que "départ" comme label). OUI/NON
    # restent tolérés dans plusieurs casses via une alternative dédiée.
    opt_pattern = r'^(?:\s*(?:____|[Oo][Uu][Ii]|[Nn][Oo][Nn]|\[\s*\]|\[[xX]\]|\d{2,4}[/.\-]\d{2,4}|[A-Z0-9]{2,4}(?=\s+[A-Z0-9]|$))\s*)+'

    match = re.match(opt_pattern, text)
    if match:
        val_end = match.end()
        val_part = text[:val_end].strip()
        label_part = text[val_end:].strip()
        return val_part, label_part

    # Détection explicite de '____' ou 'OUI NON' séparant la valeur du label suivant
    m_filler = re.match(r'^(.*?\b(?:____|OUI\s+NON|OUI/NON)\b)\s*(.*)$', text, re.IGNORECASE)
    if m_filler and m_filler.group(2):
        return m_filler.group(1).strip(), m_filler.group(2).strip()

    return "", text


@ParserRegistry.register("A")
class FamilyAParser(BaseFamilyParser):

    def parse(
        self,
        file_path: str,
        document_title: Optional[str] = None,
        effective_start_line: int = 0
    ) -> List[Chunk]:
        ext = os.path.splitext(file_path)[1].lower()
        clean_title = document_title if document_title else os.path.basename(file_path).rsplit(".", 1)[0].replace("_", " ")

        try:
            raw_lines = self._extract_raw_lines(file_path, ext)
        except Exception as exc:
            logger.warning(
                "FamilyAParser: extraction failed for %s (%s: %s) — falling back to FallbackParser",
                file_path, type(exc).__name__, exc
            )
            return FallbackParser().parse(
                file_path,
                document_title=document_title,
                effective_start_line=effective_start_line
            )

        if effective_start_line > 0 and effective_start_line < len(raw_lines):
            raw_lines = raw_lines[effective_start_line:]

        # Fusion des blocs multi-lignes
        raw_lines = self._merge_multiline_blocks(raw_lines)

        # Nettoyage global préliminaire et filtrage des lignes de pointillés isolées
        cleaned_raw_lines = []
        for line in raw_lines:
            c_line = _clean_line(line)
            # Ignorer les lignes composées uniquement de pointillés ou vides
            if c_line and not re.fullmatch(r'[.\u2026_\s]{4,}', c_line):
                cleaned_raw_lines.append(c_line)

        

        # Post-traitement des couples Label/Valeur
        final_lines = []
        i = 0
        while i < len(raw_lines):
            line = raw_lines[i]
            next_line = raw_lines[i + 1] if (i + 1) < len(raw_lines) else None

            formatted_line, consumed_next = self._format_kv_line(line, next_line)
            if formatted_line.strip():
                final_lines.append(formatted_line)

            if consumed_next:
                i += 2
            else:
                i += 1

        raw_text = "\n".join(final_lines)

        # Extraction propre des labels pour le header LLM
        labels = re.findall(r'([A-Za-zÀ-ÿ][^:?|\n]{1,60}?)\s*[:?]', raw_text)
        clean_labels = []
        for l in labels:
            lbl = l.strip()
            if _is_valid_label(lbl) and lbl not in clean_labels:
                clean_labels.append(lbl)
        clean_labels = clean_labels[:15]

        header = f"Formulaire : {clean_title}.\nChamps requis : {', '.join(clean_labels) if clean_labels else 'Procédure'}.\n=========================\n"

        return [Chunk(
            text=header + raw_text,
            metadata=ChunkMetadata(
                document_name=clean_title,
                family_type="A",
                procedure=clean_title.lower()
            )
        )]

    # =========================================================================
    # EXTRACTION BRUTE
    # =========================================================================

    def _extract_raw_lines(self, file_path: str, ext: str) -> List[str]:
        if ext == '.docx':
            return self._extract_from_docx(file_path)
        else:
            return self._extract_from_pdf(file_path)

    def _extract_from_docx(self, file_path: str) -> List[str]:
        raw_lines = []
        doc = Document(file_path)

        for element in doc.element.body:
            if element.tag.endswith('p'):
                p = Paragraph(element, doc)
                txt = p.text
                if txt:
                    raw_lines.append(txt)
            elif element.tag.endswith('tbl'):
                table = Table(element, doc)
                for row in table.rows:
                    cells = [_clean_line(cell.text) for cell in row.cells if _clean_line(cell.text)]
                    cells = _dedupe_consecutive(cells)
                    if cells:
                        raw_lines.append(" | ".join(cells))

        for node in doc.element.xpath('//*[local-name()="txbxContent"]'):
            for p_node in node.xpath('.//*[local-name()="p"]'):
                p = Paragraph(p_node, doc)
                txt = _clean_line(p.text)
                if txt:
                    raw_lines.append(txt)

        return raw_lines

    def _extract_from_pdf(self, file_path: str) -> List[str]:
        raw_lines = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                try:
                    annots = page.annots
                except Exception as exc:
                    logger.debug("Annotations illisibles p.%s de %s (%s) — ignorées", page.page_number, file_path, exc)
                    annots = None

                if annots:
                    for annot in annots:
                        if annot.get('V') and isinstance(annot['V'], str):
                            raw_lines.append(_clean_line(annot['V']))
                        elif annot.get('Contents') and isinstance(annot['Contents'], str):
                            raw_lines.append(_clean_line(annot['Contents']))

                tables_objs = page.find_tables()
                if tables_objs:
                    for table_obj in tables_objs:
                        for row in table_obj.extract():
                            cells = [_clean_line(cell) for cell in row if cell and _clean_line(cell)]
                            cells = _dedupe_consecutive(cells)
                            if cells:
                                raw_lines.append(" | ".join(cells))

                    def not_in_table(obj, _tables=tables_objs):
                        px0, py0, px1, py1 = obj["x0"], obj["top"], obj["x1"], obj["bottom"]
                        for t in _tables:
                            tx0, ty0, tx1, ty1 = t.bbox
                            if px0 >= tx0 and py0 >= ty0 and px1 <= tx1 and py1 <= ty1:
                                return False
                        return True

                    clean_page = page.filter(not_in_table)
                    text_outside = clean_page.extract_text(layout=True) or ""
                else:
                    text_outside = page.extract_text(layout=True) or ""

                if text_outside.strip():
                    text_outside = re.sub(r'[\uf06f\uf0fe\uf0a8\u25a1\u25a2]', '[ ]', text_outside)
                    for line in text_outside.split('\n'):
                        # extract_text(layout=True) pave la page en largeur fixe :
                        # une ligne "vide" visuellement est en réalité une chaîne
                        # de dizaines d'espaces, non vide au sens Python. Sans ce
                        # .strip(), ces lignes-espaces passent le filtre et
                        # maintiennent artificiellement un bloc multi-lignes actif
                        # dans _merge_multiline_blocks (voir plus bas).
                        if line.strip():
                            raw_lines.append(line)

        return raw_lines

    # =========================================================================
    # FUSION MULTI-LIGNES
    # =========================================================================

    def _merge_multiline_blocks(self, lines: List[str]) -> List[str]:
        """
        Convertit une ligne présentant un VRAI grand espace 2-colonnes
        (ex: "NOM :          Prénom :") en "NOM : | Prénom :".

        Chaque ligne est traitée indépendamment — on ne tente plus
        d'accumuler plusieurs lignes consécutives dans un même bloc. Dans
        les documents réels traités ici, chaque ligne avec un grand espace
        interne est déjà une rangée complète en elle-même (ex: la rangée
        "NOM / Prénom" suivie de la rangée "Grade / Fonction" juste après) :
        les accumuler ensemble fusionnait à tort deux rangées différentes
        ("NOM : Grade : | Prénom : Fonction :"). Traiter ligne par ligne
        évite ce problème sans rien perdre, puisqu'aucun cas de paragraphe
        réellement réparti sur plusieurs lignes physiques n'apparaît dans
        ces formulaires.

        Deux garde-fous restent nécessaires :

        1. Un grand espace d'un seul côté (texte centré ou aligné à droite,
           ex: "                    Alger le ………..") n'est PAS une colonne :
           il n'y a alors qu'une seule information sur la ligne. On ne
           transforme donc en "gauche | droite" que si LES DEUX côtés
           contiennent du texte.
        2. Le padding de fin de ligne ajouté par extract_text(layout=True)
           forme souvent un espace plus long que le véritable espace entre
           les deux colonnes ; il faut le retirer (rstrip) avant de chercher
           le grand espace, sinon find_main_gap choisit le mauvais espace.
        """
        merged_lines = []

        def find_main_gap(text: str):
            matches = list(re.finditer(r'\s{15,}', text))
            if not matches:
                return None
            return max(matches, key=lambda m: m.end() - m.start())

        for raw_line in lines:
            if not raw_line.strip():
                continue

            line = raw_line.rstrip()
            gap = find_main_gap(line)

            if gap:
                left = line[:gap.start()].strip()
                right = line[gap.end():].strip()
                if left and right:
                    merged_lines.append(f"{left} | {right}")
                    continue

            merged_lines.append(line.strip())

        return merged_lines

    # =========================================================================
    # FORMATAGE DES COUPLES LABELS / VALEURS
    # =========================================================================

    def _format_kv_line(self, line: str, next_line: Optional[str] = None) -> Tuple[str, bool]:
        segments = line.split(" | ") if " | " in line else [line]
        multi = len(segments) > 1

        formatted_segments = []
        consumed_next = False

        for idx, segment in enumerate(segments):
            is_last_segment = (idx == len(segments) - 1)
            f_segment, seg_consumed = self._format_kv_segment(
                segment, next_line if is_last_segment else None
            )
            if seg_consumed:
                consumed_next = True
            formatted_segments.append(f_segment)

        joined = " | ".join(formatted_segments) if multi else formatted_segments[0]
        return joined, consumed_next

    def _format_kv_segment(self, segment: str, next_line: Optional[str] = None) -> Tuple[str, bool]:
        # Normalisation des cases à cocher et des pointillés
        segment = _CHECKBOX_RE.sub('[ ]', segment)
        segment = _FILLER_RUN_RE.sub(' ____ ', segment)
        segment = _clean_line(segment)

        if not segment:
            return "", False

        # Recherche des délimiteurs ':' et '?'
        matches = list(re.finditer(r'[:?]', segment))
        if not matches:
            return segment, False

        pairs = []
        consumed_next = False
        last_end = 0

        current_label = None
        current_delim = None

        for match_idx, match in enumerate(matches):
            delim_pos = match.start()
            delim_char = match.group(0)
            text_between = segment[last_end:delim_pos]

            if match_idx == 0:
                # Avant le tout premier délimiteur du segment, il n'existe
                # par définition aucun champ précédent dont ce texte
                # pourrait être la valeur : tout text_between est le label
                # candidat tel quel. Appeler _split_value_and_label ici
                # revient à essayer de deviner une "valeur" fantôme et peut
                # ronger le début du label (ex: "Date de départ" amputé en
                # "départ" parce que "Date de" ressemblait à un code
                # d'option) — donc on ne le fait que pour les délimiteurs
                # suivants, où un champ précédent existe réellement.
                val_prev, label_cand = "", text_between.strip()
            else:
                val_prev, label_cand = _split_value_and_label(text_between)

            if _is_valid_label(label_cand):
                if current_label is not None:
                    pairs.append((current_label, current_delim, val_prev))

                current_label = label_cand
                current_delim = delim_char
                last_end = match.end()

        if current_label is not None:
            trailing_val = segment[last_end:].strip()

            # Remplacement de la valeur sur la ligne suivante si le champ est vide
            if not trailing_val and next_line:
                clean_next = _clean_line(next_line)
                clean_next = _FILLER_RUN_RE.sub(' ____ ', clean_next)
                is_fillerish = bool(re.fullmatch(r'[.\u2026_\s\[\]]{3,}', clean_next)) or clean_next == '____'
                is_short_value = len(clean_next.split()) <= 7
                if clean_next and (is_fillerish or is_short_value):
                    trailing_val = f"[ {clean_next} ]"
                    consumed_next = True

            pairs.append((current_label, current_delim, trailing_val))

        if not pairs:
            return segment, False

        reconstructed_parts = []
        for lbl, dlm, val in pairs:
            if val:
                reconstructed_parts.append(f"{lbl} {dlm} {val}")
            else:
                reconstructed_parts.append(f"{lbl} {dlm}")

        return " || ".join(reconstructed_parts), consumed_next