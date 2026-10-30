import os
import re
import logging
from typing import List, Optional, Tuple

import pdfplumber
from docx import Document
from docx.text.paragraph import Paragraph
from docx.table import Table

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

from core import Chunk, ChunkMetadata, BaseFamilyParser, ParserRegistry
from core.utils import SystemUtils
from parsers.fallback import FallbackParser

logger = logging.getLogger(__name__)

# Expressions régulières globales
_FILLER_RUN_RE = re.compile(r'[.\u2026_]{4,}')
_CHECKBOX_RE = re.compile(r'[\u2610\u2611\u2612\u25a2\u25a1]')
_HTML_TAG_RE = re.compile(r'<[^>]+>')

# Noms de champs générés automatiquement par les éditeurs de formulaires
# AcroForm ("Liste déroulante4", "Texte7", "Case à cocher2"...). Ils ne
# décrivent pas une donnée métier : on conserve la valeur saisie mais on ne
# les présente pas comme des « champs requis » du formulaire.
_GENERIC_FORM_FIELD_RE = re.compile(
    r'^(?:Liste\s+d[ée]roulante|Zone\s+de\s+texte|Case\s+[àa]\s+cocher|'
    r'Bouton|Champ|Texte|Text|Check\s*Box|Combo\s*Box|Dropdown|Text\s*Field)'
    r'\s*\d*$',
    re.IGNORECASE,
)

# Marqueur (zone d'usage privé Unicode, ne peut jamais apparaître dans un
# texte réel) préfixé aux lignes déjà "aplaties sémantiquement" par
# _classify_and_flatten_table (voir plus bas). Ces lignes sont déjà des
# phrases finales "Label : Valeur, Label2 : Valeur2" — les repasser dans le
# formateur générique _format_kv_line les redécoupe et les abîme (il
# réinterprète les ":" et "," comme de nouveaux délimiteurs de champ). Le
# marqueur permet à parse() de les reconnaître et de les laisser intactes.
_SEMANTIC_MARK = '\uE000'

# Titre du formulaire lui-même (« DOCUMENT DESCRIPTIF ANNEXE AU DIPLOME
# MASTER »). Le routeur le classe comme en-tête (pattern
# `fr_document_descriptif_diplome`) car il sert au routage, mais pour la
# famille A c'est le titre réel du document : il doit rester dans le chunk.
_FORM_TITLE_RE = re.compile(
    r"DOCUMENT\s+DESCRIPTI(?:F|VE)\b.*\bDIPLOME", re.IGNORECASE
)

# Ligne d'adresse du destinataire (« A Monsieur le responsable de
# l'entreprise ») : le routeur la classe comme en-tête de politesse, mais pour
# un formulaire de demande de stage c'est une information de contenu (à qui
# s'adresse la demande). On arrête la coupe d'en-tête sur cette ligne.
_ADDRESSEE_RE = re.compile(r"^\s*[ÀA]\s+(?:Monsieur|Madame)\b", re.IGNORECASE)


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


def _looks_like_option_list(text: str) -> bool:
    """
    Détecte une liste d'options/cases à cocher (ex: "L1 ING1 L2 ING2 L3 ING3
    M1 M2", "OUI NON") : uniquement des jetons courts, tout en majuscules
    (codes de filière, sigles), pas de mots de phrase ordinaire en minuscule.
    Sert à rattacher une telle ligne à l'intitulé/question qui la précède,
    même quand cet intitulé est trop long pour être un "label" de champ.
    """
    tokens = text.split()
    if not tokens:
        return False
    if all(re.fullmatch(r'[A-Z0-9]{1,6}', tok) for tok in tokens):
        return True
    # Options à plusieurs mots séparées par "|" — notre propre marqueur
    # interne de colonnes (jamais présent dans une phrase normale), ex:
    # "Congé Académique | Abandon Dépassement du nombre d'années autorisées".
    if '|' in text and len(tokens) <= 20:
        return True
    # Options marquées par des cases à cocher dessinées détectées en amont
    # (voir _mark_drawn_checkboxes) : "[ ] Congé Académique [ ] Abandon
    # [ ] Dépassement...". Au moins 2 marqueurs "[ ]" = liste d'options,
    # même si les libellés eux-mêmes sont de vrais mots de phrase.
    if text.count('[ ]') >= 2:
        return True
    return False


# --- Cases à cocher dessinées (VML / DrawingML) -----------------------------
# Certains formulaires (convertis depuis un .doc ancien) ne codent pas leurs
# cases à cocher en caractères Unicode (☐/☑) mais en petites FORMES dessinées
# (rectangles arrondis VML, ou images DrawingML) positionnées par-dessus le
# texte. python-docx ignore totalement ces objets dans Paragraph.text : la
# case est invisible, seul le libellé de l'option ("OUI", "L1"...) reste,
# sans aucun signe qu'il s'agit d'un choix à cocher.
_W_NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
_V_NS = '{urn:schemas-microsoft-com:vml}'
_WP_NS = '{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}'
_VML_SIZE_RE = re.compile(r'width:\s*([\d.]+)pt;\s*height:\s*([\d.]+)pt')
_EMU_PER_PT = 12700  # 12700 EMU = 1 point


def _is_checkbox_sized(width_pt: float, height_pt: float) -> bool:
    """Une vraie case à cocher est petite et à peu près carrée — pas un logo,
    une photo, ou une zone de texte (souvent >50-100pt de large)."""
    if width_pt <= 0 or height_pt <= 0 or width_pt > 30 or height_pt > 30:
        return False
    ratio = width_pt / height_pt
    return 0.4 <= ratio <= 2.5


def _paragraph_has_checkbox_drawing(p_element) -> bool:
    """
    Repère, dans le XML d'un paragraphe, une forme VML (w:pict > v:rect /
    v:roundrect / v:oval / v:shape) ou DrawingML (w:drawing > wp:extent) dont
    la taille correspond à une case à cocher.
    """
    for shape_tag in ('rect', 'roundrect', 'oval', 'shape'):
        for shape in p_element.findall(f'.//{_V_NS}{shape_tag}'):
            style = shape.get('style', '') or ''
            m = _VML_SIZE_RE.search(style)
            if m and _is_checkbox_sized(float(m.group(1)), float(m.group(2))):
                return True

    for extent in p_element.findall(f'.//{_WP_NS}extent'):
        try:
            cx, cy = float(extent.get('cx', 0)), float(extent.get('cy', 0))
        except (TypeError, ValueError):
            continue
        if _is_checkbox_sized(cx / _EMU_PER_PT, cy / _EMU_PER_PT):
            return True

    return False


def _mark_drawn_checkboxes(text: str) -> str:
    """
    Insère un marqueur "[ ]" devant chaque option d'une ligne détectée comme
    porteuse de cases à cocher dessinées (voir _paragraph_has_checkbox_drawing).

    On se limite volontairement aux paragraphes qui ressemblent déjà à une
    LISTE D'OPTIONS (ne se terminent pas par ':' ou '?') : les formes VML de
    ces formulaires sont positionnées en absolu ("position:absolute"), donc
    rattachées dans le XML au paragraphe le plus proche mais pas forcément au
    bon — les rattacher malgré tout à une phrase/question ("Je sollicite...
    à l'année d'étude :") produirait un "[ ]" placé n'importe où, trompeur.
    Sur une ligne d'options courtes, en revanche, préfixer CHAQUE groupe
    séparé par un grand espace reste correct même sans correspondance
    exacte case-par-case.
    """
    stripped = text.strip()
    if not stripped or stripped.rstrip().endswith((':', '?')):
        return text

    groups = [g for g in re.split(r'[ \t]{2,}', stripped) if g.strip()]
    if len(groups) < 2:
        return text

    return ' '.join(f'[ ] {g.strip()}' for g in groups)


def _classify_and_flatten_table(rows: List[List[str]]) -> List[str]:
    """
    Transforme les lignes brutes d'un tableau (cellules NON filtrées, y
    compris les vides, pour garder la correspondance de position) en lignes
    de texte, selon deux cas :

    1. TABLEAU DE DONNÉES (ex: relevé de notes avec colonnes "Code / Intitulé
       / Crédits / Grade / Date" répétées sur de nombreuses lignes) :
       "aplatissement sémantique" — chaque cellule non vide est associée au
       nom de sa colonne d'en-tête plutôt que simplement juxtaposée par des
       "|", ce qui est bien plus exploitable pour la recherche RAG qu'un
       "A | 10% premiers" où l'on ne sait plus quelle valeur va avec quelle
       colonne dès qu'une cellule vide a été supprimée.
    2. FORMULAIRE LABEL/VALEUR (immense majorité des tableaux de ces
       documents : chaque ligne est UN SEUL champ, souvent étalé sur
       plusieurs cellules fusionnées horizontalement) : comportement
       classique conservé (dédoublonnage + jointure "|" des cellules non
       vides).

    La distinction entre les deux repose sur la variation colonne par
    colonne : dans un vrai tableau de données, chaque ligne combine
    PLUSIEURS valeurs différentes ; dans un formulaire label/valeur, chaque
    ligne ne porte qu'UNE seule information répétée par fusion de cellules
    (gridSpan) — ratio valeurs-distinctes/valeurs-non-vides proche de 0.
    """
    if not rows:
        return []

    n_cols = max((len(r) for r in rows), default=0)
    padded = [r + [''] * (n_cols - len(r)) for r in rows]
    header, data_rows = padded[0], padded[1:]

    def non_empty(row):
        return [_clean_line(c) for c in row if _clean_line(c)]

    def distinct_ratio(row):
        ne = non_empty(row)
        return (len(set(ne)) / len(ne)) if ne else 0.0

    header_values = non_empty(header)
    is_header_candidate = (
        n_cols >= 3
        and len(data_rows) >= 2
        and len(header_values) >= max(2, n_cols // 2)
        and len(set(header_values)) >= 2
        and all(len(_clean_line(c)) <= 80 for c in header)
    )

    if is_header_candidate:
        well_varied = sum(1 for r in data_rows if distinct_ratio(r) >= 0.5)
        is_header_candidate = well_varied >= max(2, len(data_rows) // 2)

    if not is_header_candidate:
        lines = []
        for row in padded:
            cells = _dedupe_consecutive([_clean_line(c) for c in row if _clean_line(c)])
            if cells:
                lines.append(" | ".join(cells))
        return lines

    lines = []
    for row in data_rows:
        ne = non_empty(row)
        # Ligne "diviseur de section" (ex: "Premier semestre / Deuxième
        # semestre" fusionnée sur toute la largeur) : peu de valeurs
        # DISTINCTES pour beaucoup de cellules non vides -> ce n'est pas un
        # enregistrement à apparier avec l'en-tête, mais un simple titre.
        if ne and (len(set(ne)) / len(ne)) < 0.5:
            distinct_vals = list(dict.fromkeys(ne))
            lines.append(_SEMANTIC_MARK + " / ".join(distinct_vals))
            continue

        pairs = []
        prev_value = None
        for idx, cell in enumerate(row):
            cell = _clean_line(cell)
            if not cell:
                continue
            if prev_value is not None and cell == prev_value:
                # Cellule fusionnée horizontalement (gridSpan) : python-docx
                # répète son texte sur chaque position de grille qu'elle
                # couvre. Sans ce filtre, la cellule "U.E.F1.1" fusionnée sur
                # deux colonnes était appariée à DEUX en-têtes différents :
                # "Code : U.E.F1.1, Intitulé de l'UE : U.E.F1.1, Intitulé de
                # l'UE : ALGORITHMIQUE..." (cellule dupliquée, cf. A5).
                continue
            head = _clean_line(header[idx]) if idx < len(header) else ""
            pairs.append((head, cell))
            prev_value = cell

        pairs = _dedupe_row_units(pairs)
        if pairs:
            lines.append(_SEMANTIC_MARK + ", ".join(f"{h} : {v}" if h else v for h, v in pairs))

    return lines


def _dedupe_row_units(pairs: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """
    Dédoublonne les paires (en-tête, valeur) consécutives strictement
    identiques au sein d'une même ligne de données déjà appariée à son
    en-tête. Nécessaire car une cellule fusionnée horizontalement (gridSpan)
    répète la MÊME valeur sur chaque position de grille sous-jacente : sans
    ceci, une ligne comme celle du relevé de notes produirait "Code : U.E.F1.1,
    Code : U.E.F1.1, Intitulé de l'UE : ..." au lieu de "Code : U.E.F1.1,
    Intitulé de l'UE : ...".

    Différent de _dedupe_consecutive : celui-ci opère sur des cellules brutes
    AVANT tout appariement positionnel (utilisé pour le repli formulaire
    label/valeur), alors que celui-ci opère APRÈS appariement, sur les
    couples (en-tête, valeur) déjà formés, pour ne jamais décaler les
    positions pendant l'appariement lui-même.
    """
    out = []
    for pair in pairs:
        if not out or out[-1] != pair:
            out.append(pair)
    return out


def _looks_like_parenthetical_continuation(text: str) -> bool:
    """
    Vrai pour une ligne qui n'est que la fin d'un libellé entre parenthèses,
    ex. « (USTHB) : » placé sous « VISA DU DOYEN DE LA FACULTE PROMOTEUR : ».

    Ce n'est pas une valeur : sans ce test, le parser produisait
    « VISA DU DOYEN DE LA FACULTE PROMOTEUR : [ (USTHB) : ] » (A1/A7).
    """
    return bool(
        re.fullmatch(r"\(\s*[A-Za-zÀ-ÿ0-9.\- ]{1,40}\s*\)\s*[:?]", _clean_line(text))
    )


def _looks_like_section_heading(text: str) -> bool:
    """
    Vrai si la ligne est un titre de section (« 1. Informations personnelles »,
    « [ 2. Bilan scientifique ] », « 3. Travaux réalisés… »).

    Sert de garde-fou avant de rattacher la ligne suivante comme valeur d'un
    champ vide : sans cela, « Intitulé : » suivi de « 2. Bilan scientifique »
    produisait « Intitulé : [ 2. Bilan scientifique ] » — le titre de section
    devenait la valeur du champ (A7) et disparaissait en tant que titre.
    """
    clean = _clean_line(text)
    if not clean:
        return False
    # Titre entre crochets : "[ 1. Informations personnelles ]"
    if re.fullmatch(r'\[\s*[^\]]+\s*\]', clean):
        return True
    # Titre numéroté : "1. Informations personnelles", "3-2 Résultats obtenus"
    return bool(re.match(r'^\d+(?:[.\-]\d+)*[.)]?\s+\S', clean))


def _looks_like_label_line(text: str) -> bool:
    """
    Vrai si la ligne ressemble elle-même à un champ de formulaire
    ("Prénom :", "Date de retour :", "Qualité du signataire ?").

    Sert de garde-fou avant de « consommer » la ligne suivante comme valeur
    du champ courant : sans ce test, une ligne "Nom :" suivie de "Prénom :"
    produisait "Nom : [ Prénom : ]" — le second champ disparaissait en tant
    que champ et devenait la valeur du premier (A6 : champs fusionnés).
    """
    clean = _clean_line(text)
    if not clean:
        return False
    match = re.match(r'^([^:?|]{1,60}?)\s*[:?]', clean)
    if not match:
        return False
    return _is_valid_label(match.group(1))


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

    # Fragment de parenthèse : la liste des libellés est découpée sur les
    # virgules, donc "Enseignements (Cours, TD, TP)" produit des fragments
    # "TD" et "TP)" — une parenthèse fermante orpheline trahit le fragment,
    # pas un vrai libellé de champ.
    if clean.count(')') > clean.count('('):
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

    # Extensions Word "binaires" historiques. Le pipeline d'ingestion est
    # censé déjà les convertir en .docx en amont — mais si cette conversion
    # externe échoue ou est court-circuitée pour un fichier donné (observé
    # en production), ce parser sait s'en charger lui-même plutôt que
    # d'échouer en essayant de lire un .doc comme s'il s'agissait d'un PDF.
    LEGACY_WORD_EXTENSIONS = {".doc", ".dot", ".rtf"}

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
            try:
                fallback = FallbackParser()
                if not hasattr(fallback, "parse"):
                    raise AttributeError(
                        f"FallbackParser ({type(fallback).__module__}.{type(fallback).__name__}) "
                        "n'expose pas de méthode .parse()"
                    )
                return fallback.parse(
                    file_path,
                    document_title=document_title,
                    effective_start_line=effective_start_line
                )
            except Exception as fallback_exc:
                # Le FallbackParser peut lui-même ne pas exposer la méthode
                # ou la signature attendue (observé en production :
                # "'FallbackParser' object has no attribute 'parse'"), ou
                # échouer à son tour sur un fichier réellement illisible.
                # Dans ce cas, on NE LAISSE PAS remonter une seconde
                # exception qui masquerait la cause réelle (ici, l'erreur
                # originale de python-docx/pdfplumber sur le fichier) et
                # compliquerait le diagnostic côté pipeline : on journalise
                # les deux échecs clairement et on renvoie une liste vide,
                # pour que seul CE fichier soit ignoré plutôt que de faire
                # planter toute l'ingestion.
                logger.error(
                    "FamilyAParser: le repli vers FallbackParser a lui aussi échoué pour %s "
                    "(%s: %s) — fichier ignoré. Cause originale : %s: %s",
                    file_path, type(fallback_exc).__name__, fallback_exc,
                    type(exc).__name__, exc
                )
                return []

        if effective_start_line > 0 and effective_start_line < len(raw_lines):
            raw_lines = raw_lines[self._safe_header_cut(raw_lines, effective_start_line):]

        # Fusion des blocs multi-lignes
        raw_lines = self._merge_multiline_blocks(raw_lines)

        # Nettoyage global préliminaire et filtrage des lignes de pointillés isolées
        cleaned_raw_lines = []
        for line in raw_lines:
            c_line = _clean_line(line)
            # Ignorer les lignes composées uniquement de pointillés ou vides
            if c_line and not re.fullmatch(r'[.\u2026_\s]{4,}', c_line):
                cleaned_raw_lines.append(c_line)

        raw_lines = cleaned_raw_lines

        # Post-traitement des couples Label/Valeur
        
        final_lines = []
        i = 0
        while i < len(raw_lines):
            line = raw_lines[i]

            # Lignes déjà aplaties sémantiquement (tableau de données) :
            # on les restitue telles quelles, sans repasser par le
            # formateur label/valeur générique qui les redécouperait à tort.
            if line.startswith(_SEMANTIC_MARK):
                final_lines.append(line[len(_SEMANTIC_MARK):])
                i += 1
                continue

            next_line = raw_lines[i + 1] if (i + 1) < len(raw_lines) else None
            if next_line is not None and next_line.startswith(_SEMANTIC_MARK):
                # Une ligne sémantique déjà finalisée n'est jamais une
                # simple valeur/option à "avaler" pour le champ précédent.
                next_line = None

            formatted_line, consumed_next = self._format_kv_line(line, next_line)
            if formatted_line.strip():
                final_lines.append(formatted_line)

            if consumed_next:
                i += 2
            else:
                i += 1

        raw_text = "\n".join(final_lines)

        # Extraction propre des labels pour le header LLM
        # NB : ',' est exclu de la classe de caractères en plus de ':?|\n' —
        # sans cela, sur une ligne aplatie sémantiquement ("Header1 : val1,
        # Header2 : val2"), le label capturé pour le second délimiteur
        # remontait jusqu'à englober "val1, Header2" au lieu de "Header2"
        # seul (la virgule sert justement de séparateur entre couples dans
        # ces lignes-là).
        labels = re.findall(r'([A-Za-zÀ-ÿ][^:?|\n,]{1,60}?)\s*[:?]', raw_text)
        clean_labels = []
        for l in labels:
            lbl = l.strip()
            if _GENERIC_FORM_FIELD_RE.match(lbl) or lbl.lower().startswith("champ de formulaire"):
                continue
            if _is_valid_label(lbl) and lbl not in clean_labels:
                clean_labels.append(lbl)
        clean_labels = clean_labels[:15]

        header_title = clean_title.rstrip(" .;:") or clean_title
        header = f"Formulaire : {header_title}.\nChamps requis : {', '.join(clean_labels) if clean_labels else 'Procédure'}.\n=========================\n"

        parts = self._split_long_body(raw_text)
        if len(parts) <= 1:
            return [Chunk(
                text=header + raw_text,
                metadata=ChunkMetadata(
                    document_name=clean_title,
                    family_type="A",
                    procedure=clean_title.lower()
                )
            )]

        return [Chunk(
            text=header + part,
            metadata=ChunkMetadata(
                document_name=clean_title,
                family_type="A",
                procedure=clean_title.lower()
            )
        ) for part in parts]

    # Taille maximale visée pour un chunk de formulaire. Le barème d'audit
    # considère un chunk de plus de 6000 caractères comme aberrant (C5) ;
    # l'annexe descriptive au diplôme (APCI) fait ~8500 caractères et doit
    # donc être scindée.
    MAX_CHUNK_CHARS = 4500

    # Début de section numérotée ("2. INFORMATIONS...", "3-2 Résultats...").
    _SECTION_HEADING_RE = re.compile(r'^\d+(?:[.\-]\d+)*[.)]?\s+[A-ZÀ-Ý]')

    def _split_long_body(self, body: str) -> List[str]:
        """
        Scinde un formulaire trop long en plusieurs blocs, aux frontières de
        lignes uniquement (jamais au milieu d'une ligne de tableau).

        Une ligne de titre de section est un point de coupe privilégié dès
        qu'au moins la moitié du budget est déjà consommée : les sections
        logiques (« 3-2 Résultats obtenus », « 4- PROJECTIONS... ») restent
        ainsi entières plutôt que d'être coupées au hasard.
        """
        if len(body) <= self.MAX_CHUNK_CHARS:
            return [body]

        budget = self.MAX_CHUNK_CHARS
        parts: List[str] = []
        buffer: List[str] = []
        size = 0

        def flush():
            nonlocal buffer, size
            text = "\n".join(buffer).strip()
            if text:
                parts.append(text)
            buffer, size = [], 0

        for line in body.split("\n"):
            line_len = len(line) + 1
            if buffer:
                too_long = size + line_len > budget
                section_break = (
                    size >= budget // 2 and self._SECTION_HEADING_RE.match(line)
                )
                if too_long or section_break:
                    flush()
            buffer.append(line)
            size += line_len
        flush()

        return parts or [body]

    # =========================================================================
    # EXTRACTION BRUTE
    # =========================================================================

    @staticmethod
    def _safe_header_cut(lines: List[str], requested: int) -> int:
        """
        Réduit si nécessaire l'index de démarrage fourni par le routeur.

        Le routeur compte ses lignes sur sa PROPRE extraction (paragraphes +
        une entrée par cellule de tableau), alors que ce parser aplatit
        chaque tableau en UNE ligne. Les deux index ne coïncident donc pas :
        sur « AnnMasAPCI.doc », le routeur renvoyait 4 alors que le parser
        n'a qu'une seule ligne d'en-tête institutionnel, si bien que le titre
        du document, son paragraphe d'introduction et le titre de section
        « 1. LE TITULAIRE DU DIPLOME » étaient supprimés (perte de contenu,
        C4). On ne coupe donc jamais au-delà du dernier en-tête institutionnel
        réellement présent dans NOS lignes.
        """
        if requested <= 0:
            return 0

        from pipeline.router import DocumentRouter  # import local (pas de cycle)

        i = 0
        while (
            i < len(lines)
            and i < requested
            and DocumentRouter._is_header_line(lines[i])
            and not _FORM_TITLE_RE.search(lines[i])
            and not _ADDRESSEE_RE.match(lines[i])
        ):
            i += 1
        return min(requested, i)

    def _extract_raw_lines(self, file_path: str, ext: str) -> List[str]:
        if ext == '.docx':
            return self._extract_from_docx(file_path)
        elif ext in self.LEGACY_WORD_EXTENSIONS:
            # Filet de sécurité : normalement déjà converti en amont du
            # pipeline, mais si ce fichier précis a échappé à cette étape
            # (conversion externe en échec, non déclenchée, etc.), on tente
            # de le convertir nous-mêmes plutôt que d'essayer de le lire
            # comme un PDF (ce qui échoue toujours et produit une erreur
            # confuse, sans rapport avec la cause réelle).
            # Le .docx produit est mis en cache par SystemUtils : il ne faut
            # surtout PAS le supprimer ici (il serait reconstruit à chaque
            # exécution) et il n'est jamais écrit dans le dossier source.
            converted_path = self._convert_legacy_word_to_docx(file_path)
            return self._extract_from_docx(converted_path)
        else:
            return self._extract_from_pdf(file_path)

    def _convert_legacy_word_to_docx(self, file_path: str, timeout: int = 180) -> str:
        """
        Convertit un .doc/.dot/.rtf binaire en .docx via LibreOffice headless.

        Délègue à `SystemUtils.convert_doc_to_docx` : résolution de
        l'exécutable (PATH puis emplacements d'installation standard),
        cache persistant hors de `data/` et second essai en cas de
        dépassement de délai. Lève une exception explicitement actionnable
        si la conversion échoue — l'appelant (parse()) délègue alors au
        FallbackParser.
        """
        return SystemUtils.convert_doc_to_docx(file_path, self.config, timeout=timeout)

    def _extract_from_docx(self, file_path: str) -> List[str]:
        raw_lines = []
        doc = Document(file_path)

        for element in doc.element.body:
            if element.tag.endswith('p'):
                p = Paragraph(element, doc)
                txt = p.text
                if txt:
                    # Cases à cocher dessinées (VML/DrawingML) : invisibles
                    # pour p.text, on les détecte via le XML brut du
                    # paragraphe et on marque les options concernées.
                    if _paragraph_has_checkbox_drawing(element):
                        txt = _mark_drawn_checkboxes(txt)
                    raw_lines.append(txt)
            elif element.tag.endswith('tbl'):
                table = Table(element, doc)
                raw_rows = [[cell.text for cell in row.cells] for row in table.rows]
                raw_lines.extend(_classify_and_flatten_table(raw_rows))

        for node in doc.element.xpath('//*[local-name()="txbxContent"]'):
            for p_node in node.xpath('.//*[local-name()="p"]'):
                p = Paragraph(p_node, doc)
                txt = _clean_line(p.text)
                if txt:
                    raw_lines.append(txt)

        return raw_lines

    def _extract_from_pdf(self, file_path: str) -> List[str]:
        raw_lines = []
        already_captured = set()

        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                try:
                    annots = page.annots
                except Exception as exc:
                    # pdfplumber peut faire planter SA PROPRE lecture des
                    # annotations à cause d'un encodage invalide sur UN SEUL
                    # champ de la page — ce qui, sans garde-fou, ferait
                    # perdre TOUTES les valeurs de champs de cette page, y
                    # compris celles, valides, saisies dans d'autres champs
                    # (ex: un menu déroulant "Année : 2023" à côté d'un champ
                    # texte mal encodé). _extract_acroform_field_values()
                    # (basé sur pypdf, plus tolérant) compense ce cas juste
                    # après la boucle de pages.
                    logger.debug("Annotations illisibles p.%s de %s (%s) — ignorées", page.page_number, file_path, exc)
                    annots = None

                if annots:
                    for annot in annots:
                        if annot.get('V') and isinstance(annot['V'], str):
                            value = _clean_line(annot['V'])
                            if value:
                                raw_lines.append(value)
                                already_captured.add(value)
                        elif annot.get('Contents') and isinstance(annot['Contents'], str):
                            value = _clean_line(annot['Contents'])
                            if value:
                                raw_lines.append(value)
                                already_captured.add(value)

                tables_objs = page.find_tables()
                if tables_objs:
                    for table_obj in tables_objs:
                        raw_rows = [[(c or '') for c in row] for row in table_obj.extract()]
                        raw_lines.extend(_classify_and_flatten_table(raw_rows))

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

        # Filet de sécurité pour les valeurs de champs de formulaire
        # interactif (AcroForm) qu'une page.annots défaillante aurait pu
        # faire perdre silencieusement (voir commentaire ci-dessus). On ne
        # rajoute que les valeurs pas déjà capturées, pour ne rien dupliquer
        # quand page.annots a fonctionné normalement.
        for line in self._extract_acroform_field_values(file_path):
            if line not in already_captured:
                raw_lines.append(line)
                already_captured.add(line)

        return raw_lines

    def _extract_acroform_field_values(self, file_path: str) -> List[str]:
        """
        Lit les valeurs des champs de formulaire interactif (texte, menus
        déroulants, cases à cocher) via pypdf, en complément de la lecture
        d'annotations de pdfplumber.

        Nécessaire car pdfplumber peut faire planter sa propre lecture de
        page.annots à cause d'un encodage invalide localisé sur UN SEUL
        champ de la page (observé en pratique) — perdant alors TOUTES les
        valeurs de cette page, y compris des champs par ailleurs valides
        (ex: deux menus déroulants "Année" tous deux remplis à "2023").
        pypdf s'est montré plus tolérant sur ce type de PDF.

        Les noms de champs (ex: "Liste déroulante4") sont générés par
        l'éditeur de formulaire et non descriptifs : on ne peut pas les
        relier de façon fiable au libellé humain affiché à côté sans
        comparer les positions (rect) de chaque widget avec le texte
        environnant, ce qui n'est pas fait ici. On restitue donc
        "nom_champ : valeur" tel quel — imparfait, mais très supérieur à la
        perte pure et simple de la donnée saisie.
        """
        if PdfReader is None:
            return []
        try:
            reader = PdfReader(file_path)
            fields = reader.get_fields() or {}
        except Exception as exc:
            logger.debug("Lecture AcroForm (pypdf) impossible pour %s (%s)", file_path, exc)
            return []

        lines = []
        for name, field in fields.items():
            value = field.get('/V')
            if value is None:
                continue
            value = _clean_line(str(value))
            if not value:
                continue
            clean_name = _clean_line(str(name))
            if _GENERIC_FORM_FIELD_RE.match(clean_name):
                # Nom technique non descriptif : la valeur reste restituée
                # (elle n'apparaît nulle part ailleurs dans le texte de la
                # page), mais présentée comme une valeur de champ interactif
                # et non comme un libellé métier.
                lines.append(f"Champ de formulaire « {clean_name} » : {value}")
            else:
                lines.append(f"{clean_name} : {value}")
        return lines

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
        évite ce problème sans rien perdre, 
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

            # Ligne déjà aplatie sémantiquement : à laisser telle quelle,
            # jamais découpée sur un grand espace interne (elle n'en a
            # normalement pas, mais mieux vaut ne pas en dépendre).
            if raw_line.startswith(_SEMANTIC_MARK):
                merged_lines.append(raw_line)
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
        # Plusieurs zones de remplissage consécutives dans une même cellule
        # ("Motif : ……… ……… ………") ne portent qu'une seule information :
        # une seule marque de remplissage suffit et évite le bruit C6.
        segment = re.sub(r'(?:____\s*){2,}', '____ ', segment)
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
                if _looks_like_parenthetical_continuation(clean_next):
                    # Fin d'un libellé sur la ligne suivante : on la recolle
                    # au libellé, jamais présentée comme une valeur de champ.
                    current_label = (
                        f"{current_label} {clean_next.rstrip().rstrip(':').strip()}"
                    )
                    consumed_next = True
                    clean_next = ""
                is_fillerish = bool(re.fullmatch(r'[.\u2026_\s\[\]]{3,}', clean_next)) or clean_next == '____'
                is_short_value = len(clean_next.split()) <= 3
                is_option_list = _looks_like_option_list(clean_next)
                is_next_label = _looks_like_label_line(clean_next)
                is_section_heading = _looks_like_section_heading(clean_next)
                if clean_next and not is_next_label and not is_section_heading and (is_fillerish or is_short_value or is_option_list):
                    # Une liste d'options est déjà une valeur "lisible" en
                    # tant que telle (surtout si elle porte ses propres
                    # marqueurs "[ ]" de cases à cocher) : l'envelopper à
                    # nouveau dans "[ ... ]" produirait un double crochet
                    # ("[ [ ] Congé Académique... ]"). On ne l'enveloppe
                    # donc que dans les cas filler/valeur courte.
                    trailing_val = clean_next if is_option_list else f"[ {clean_next} ]"
                    consumed_next = True

            pairs.append((current_label, current_delim, trailing_val))

        if not pairs:
            # Aucun label "court" valide trouvé dans ce segment — souvent le
            # cas d'une question/intitulé long ("Je sollicite... à l'année
            # d'étude :") qui n'est pas un vrai champ de formulaire mais se
            # termine tout de même par ':' ou '?'. Sans ce bloc, la liste
            # d'options qui suit sur la ligne suivante (ex: "L1 ING1 L2
            # ING2...") restait isolée, déconnectée visuellement de la
            # question à laquelle elle répond. On tente donc le même
            # rattachement de ligne suivante que pour un champ valide, mais
            # seulement si ça ressemble vraiment à des options/remplissage
            # (pas une phrase de suite, pour ne pas recoller du texte qui
            # n'a rien à voir).
            if segment.rstrip().endswith((':', '?')) and next_line:
                clean_next = _clean_line(next_line)
                clean_next = _FILLER_RUN_RE.sub(' ____ ', clean_next)
                is_fillerish = bool(re.fullmatch(r'[.\u2026_\s\[\]]{3,}', clean_next)) or clean_next == '____'
                is_short_value = len(clean_next.split()) <= 3
                is_option_list = _looks_like_option_list(clean_next)
                is_next_label = _looks_like_label_line(clean_next)
                is_section_heading = _looks_like_section_heading(clean_next)
                if clean_next and not is_next_label and not is_section_heading and (is_fillerish or is_short_value or is_option_list):
                    return f"{segment} {clean_next}", True
            return segment, False

        reconstructed_parts = []
        for lbl, dlm, val in pairs:
            if val:
                reconstructed_parts.append(f"{lbl} {dlm} {val}")
            else:
                reconstructed_parts.append(f"{lbl} {dlm}")

        result = " || ".join(reconstructed_parts)
        # Double séparateur dans la source (« Promoteur 2 : :…… ») : on ne
        # conserve qu'un seul « : », sinon le champ paraît avoir pour valeur
        # un second séparateur (A1). N'affecte pas les heures « 08:30:00 ».
        result = re.sub(r':\s*:\s*', ': ', result)
        return result, consumed_next