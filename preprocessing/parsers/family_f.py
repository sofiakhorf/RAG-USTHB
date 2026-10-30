"""
Parser "Famille F" — Textes juridiques algériens (décrets, arrêtés, décisions, lois)
=====================================================================================

Ce module reprend le parser d'origine et corrige plusieurs limites observées en
le testant mentalement sur les 3 documents PDF fournis en exemple
(arrete71403nov2011.pdf, 994.pdf, decret_2001_tache_accessoire-1.pdf) :

1. EXTRACTION NATIVE EN PRIORITÉ, OCR EN SECOURS
   L'ancienne version passait TOUJOURS par l'OCR (rendu image à 300 dpi puis
   pytesseract), même quand le PDF contient déjà un vrai calque de texte
   (cas probable de arrete71403nov2011.pdf : texte net, un simple sceau en
   image). Refaire de l'OCR sur du texte déjà numérique est plus lent ET
   moins fiable que de lire directement `page.get_text()`. On ne bascule en
   OCR que si la page ne contient quasiment aucun texte natif (page
   réellement scannée, ex. 994.pdf, decret_2001_tache_accessoire-1.pdf).

2. OCR CONSCIENT DES COLONNES
   Le Journal Officiel (decret_2001_tache_accessoire-1.pdf) est imprimé sur
   2 colonnes. OCRiser la page entière en une seule passe fait lire le
   texte ligne par ligne de gauche à droite en mélangeant les 2 colonnes.
   On détecte la "gouttière" verticale blanche entre les colonnes et on
   OCRise chaque colonne séparément, dans l'ordre de lecture.

3. NETTOYAGE DES EN-TÊTES/PIEDS DE PAGE RÉPÉTÉS
   "JOURNAL OFFICIEL DE LA REPUBLIQUE ALGERIENNE N°57", les numéros de page,
   les dates hégiriennes d'en-tête, etc. sont retirés PAGE PAR PAGE (et non
   plus via une simple troncature des N premières lignes du fichier entier,
   qui ne traitait que la première page).

4. SEGMENTATION EN SOUS-DOCUMENTS (correction d'un bug important)
   decret_2001_tache_accessoire-1.pdf contient en réalité 4 décrets
   DISTINCTS (01-293, 01-294, 01-295, 01-296) dans un seul fichier PDF.
   L'ancien parser traitait tout le fichier comme UN SEUL texte : les
   "Art. 1" des 4 décrets étaient mélangés sous un même `procedure_meta`
   (celui du premier décret trouvé). On détecte maintenant les frontières
   entre textes juridiques et chaque décret est parsé indépendamment, avec
   son propre préambule et son propre numéro de procédure.
   ATTENTION : un même texte cite très souvent d'autres décrets dans ses
   visas ("Vu le décret exécutif n°94-260 du...") — ce ne sont PAS des
   frontières de nouveau document. La détection filtre ces citations (cf.
   `_looks_like_new_document`).

5. REGEX D'ARTICLES PLUS ROBUSTE
   - FR : "Article 1er", "Art. 2", "Art 3" (sans point), "Art.2" (sans
     espace) sont tous reconnus. L'ancienne regex perdait le suffixe "er"
     de "Article 1er" (bug visible sur arrete71403nov2011.pdf : le corps du
     1er article commençait par "er : Le présent arrêté...").
   - AR : "المادة الأولى" ainsi que "المادة الثانية", "الثالثة"... en plus
     des formes numériques "المادة 2".
   - Un numéro d'article normalisé (entier) est extrait quand c'est
     possible.

6. DÉTECTION (BEST-EFFORT) DES CHAPITRES/TITRES
   "Chapitre 2", "TITRE I", "الفصل الأول"... apparaissent dans les arrêtés
   sur les diplômes. Avec un simple split par article, ces titres se
   retrouvaient collés à la fin du corps de l'article PRÉCÉDENT (puisqu'ils
   apparaissent juste avant l'article suivant). On les détecte et on les
   rattache au bon article, comme métadonnée de contexte.

7. TABLEAUX NATIFS
   Les barèmes/taux horaires et les tableaux de crédits budgétaires sont
   extraits via `page.find_tables()` quand la page n'est pas scannée, pour
   éviter que l'OCR ne détruise leur structure en lignes/colonnes.

8. NETTOYAGE POST-EXTRACTION
   Dé-hyphénation ("occupa-\ntion" -> "occupation"), normalisation Unicode
   (NFKC) et des espaces, détection sommaire de la langue dominante par
   chunk (fr / ar / mixed).


"""

import pymupdf
import os
import re
import unicodedata
import logging
from typing import List, Optional

from PIL import Image
import pytesseract

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

from core import Chunk, ChunkMetadata, BaseFamilyParser, ParserRegistry
from core.utils import SystemUtils, AcademicMetadataExtractor
from parsers.fallback import FallbackParser

logger = logging.getLogger("RAG_USTHB_OCR")


# ---------------------------------------------------------------------------
# Regex & constantes
# ---------------------------------------------------------------------------

# Lignes "bruit" typiques du Journal Officiel / en-têtes ministériels,
# répétées sur chaque page -> à retirer avant tout traitement.
_NOISE_LINE_RES = [
    re.compile(r'^\s*(?:JOURNAL\s+OFFICIEL|[A-Z\s]*ICIEL)\s+DE\s+LA\s+R[ÉE]PUBLIQUE\s+ALG[ÉE]RIENNE.*$', re.I),
    re.compile(r'^\s*JOURNAL\s+OFFIC[A-Z]*\s*$', re.I),
    re.compile(r'^\s*L\s+DE\s+LA\s+REPUBLIQUE\s+ALGERIENNE.*$', re.I),
    re.compile(r'^\s*\d{1,3}\s*$'),  # numéro de page seul sur sa ligne
    re.compile(r'^\s*(?:\d{1,3}\s+)?\d{1,2}\s+[A-Za-zÀ-ÿ\-]+\s+\d{3,4}\s*$'),  # "15 2 -3 octobre-2001"
    re.compile(r'^\s*\d{1,2}\s+Rajab\s*\d{0,4}', re.I),
    re.compile(r'^\s*الجمهورية\s+الجزائرية\s+الديمقراطية\s+الشعبية\s*$'),
]

# Début possible d'un nouveau texte juridique -> sert à découper un PDF
# contenant plusieurs décrets/arrêtés/décisions en sous-documents.
_NEW_DOC_RE = re.compile(
    r'(?:'
    r'D[ée]cret\s+(?:ex[ée]cutif|pr[ée]sidentiel)?\s*(?:n[°ºo]?[\s./\\-]*\d+[\s-]*\d*|\bdu\b|\bportant\b|\bfixant\b)'
    r'|Arr[êe]t[ée]\s*(?:n[°ºo]?[\s./\\_%*-]*\d*|\bdu\b|\bportant\b|\bfixant\b)'
    r'|D[ée]cision\s*n[°ºo]?[\s./\\-]*\d*'
    r'|Loi\s*n[°ºo]?[\s./\\-]*\d+[\s-]*\d*'
    r'|Ordonnance\s*n[°ºo]?[\s./\\-]*\d+[\s-]*\d*'
    r'|مرسوم\s+(?:تنفيذي|رئاسي)?\s*(?:رقم[\s./\\-]*[\d\-]+|\bمؤرخ\b)'
    r'|قانون\s*رقم[\s./\\-]*[\d\-]+'
    r'|قرار\s*(?:رقم[\s./\\-]*\d*|\bمؤرخ\b|\bيحدد\b|\bيتضمن\b)'
    r')',
    re.IGNORECASE
)

# Mots/particules qui, juste avant un match ci-dessus, trahissent une simple
# CITATION ("Vu le décret n°...", "...modifiant le décret exécutif n°...")
# plutôt qu'un véritable début de nouveau texte.
_CITATION_CONTEXT_RE = re.compile(
    r"(?:\bvu\b|\ble\b|\bla\b|\bles\b|\bdu\b|\bdes\b|\bau\b|\baux\b|\bet\b|"
    r"\bde\b|\bl['’]|\bd['’]|\bqu['’]|\bmodifiant\b|\bcompl[ée]tant\b|"
    r"\babrogeant\b|بمقتضى|وبمقتضى|وبمقتضي)\s*(?:le|la|les|l['’]|du|des|ال)?\s*$",
    re.IGNORECASE
)

# Formule d'autorité qui suit typiquement un VRAI en-tête de texte juridique
# ("Le Chef du Gouvernement,", "Le Ministre de...", "إنّ وزير...").
_AUTHORITY_INTRO_RE = re.compile(
    r'(Le\s+Chef\s+du\s+Gouvernement|Le\s+Premier\s+Ministre|Le\s+Ministre\b|'
    r'إنّ?\s+وز[يـب]ر|إن\s+وز[يـب]ر|وز[يـب]ر\s+التعليم|'
    r'ARRETE|D[ée]cr[èe]te|يقرر\s+ما\s+يأتي)',
    re.IGNORECASE
)

# Articles FR/AR : tolère "Article 1er", "Art. 2", "Art 3", "Art.2",
# "المادة الأولى", "المادة 2"...
_ARABIC_ORDINALS = (
    r'(?:الأول[ىي]|الثانية|الثالثة|الرابعة|الخامسة|'
    r'السادسة|السابعة|الثامنة|التاسعة|العاشرة)'
)
# Un VRAI début d'article est en début de ligne et suivi d'un séparateur
# (":", ".", "—", "-"). Cela écarte les renvois dans le corps du texte
# ("l'article 5 ci-dessus", "المادة 11 أعلاه", "notamment son article 56")
# et les citations entre guillemets ("Art. 8. — ..." dans le décret 01-296).
# FIX: tolère aussi des guillemets/° parasites de l'OCR juste après le
# numéro (ex: "Article 1°\"" sur arrete714) et avant le séparateur, et
# permet des guillemets/virgule/tiret ouvrants avant l'article.
_ARTICLE_RE = re.compile(
    r'^[ \t]*(?:[,‘“"\'»\-*~][ \t]*)?('
    r'(?:Art(?:icle)?\.?)[ \t]*\d+[ \t]*(?:er|ère)?[°"\x27]?(?=[ \t]*[:.\u2014\u2013\-"\'\x27])'
    r'|المادة[ \t]*(?:\d+|' + _ARABIC_ORDINALS + r')(?=[ \t]*[:：.؛\u2014\u2013\-])'
    r')',
    re.IGNORECASE | re.MULTILINE
)

# Titres de chapitre/section qui peuvent s'être "collés" à la fin du corps
# de l'article précédent (best effort — n'échoue jamais silencieusement).
_CHAPTER_RE = re.compile(
    r'((?:Chapitre\s+\d+|TITRE\s+[IVXLC]+|الفصل\s+' + _ARABIC_ORDINALS + r')'
    r'\s*[\r\n]{1,2}[^\n]{0,120})',
    re.IGNORECASE
)

_ARABIC_ORDINAL_MAP = {
    'الأولى': 1, 'الاولى': 1, 'الأولي': 1,
    'الثانية': 2, 'الثالثة': 3, 'الرابعة': 4, 'الخامسة': 5,
    'السادسة': 6, 'السابعة': 7, 'الثامنة': 8, 'التاسعة': 9, 'العاشرة': 10,
}

_KEYWORDS_BAREMES = ["taux", "barème", "rétribution", "montant", "indemnité", " da ", "دينار"]

_PROCEDURE_RE = re.compile(
    r'((?:décret|arrêté|décision|loi|ordonnance|مرسوم|قرار|قانون)'
    r'.{0,40}?(?:n[°ºo]|رقم)[\s./\\-]*\d+(?:[-–]\d+)?)',
    re.IGNORECASE
)

# Minimum ratio of structured text (letters+digits) vs total chars
# to consider a page as having real content (vs diploma specimens).
_MIN_STRUCTURED_RATIO = 0.3
_MIN_PAGE_TEXT_LEN = 60


@ParserRegistry.register("F")
class FamilyFParser(BaseFamilyParser):
    """Parser pour les textes juridiques algériens (décrets, arrêtés,
    décisions, lois) FR/AR, qu'ils soient numériques ou scannés, et qu'un
    même fichier contienne un seul texte ou plusieurs (cas du Journal
    Officiel)."""

    # ------------------------------------------------------------------
    # Point d'entrée
    # ------------------------------------------------------------------
    def parse(
        self,
        file_path: str,
        document_title: Optional[str] = None,
        effective_start_line: int = 0
    ) -> List[Chunk]:
        clean_title = document_title if document_title else os.path.basename(file_path)

        try:
            pages_text = self._extract_pages(file_path)
        except Exception as e:
            logger.error(f"Échec de l'extraction/OCR sur {file_path} : {e}")
            return FallbackParser.parse_safe(file_path, "F")

        # Troncature de l'en-tête institutionnel de la 1ère page (comportement
        # historique conservé pour compatibilité ascendante). Les en-têtes
        # répétés sur les pages suivantes sont désormais retirés par
        # `_strip_noise_lines` dans `_extract_pages`.
        if effective_start_line > 0 and pages_text:
            lines = pages_text[0].split('\n')
            if effective_start_line < len(lines):
                pages_text[0] = "\n".join(lines[effective_start_line:])

        full_text = "\n".join(pages_text)
        full_text = self._clean_text(full_text)

        if not full_text.strip():
            logger.warning(f"Aucun texte exploitable extrait de {file_path}")
            return FallbackParser.parse_safe(file_path, "F")

        # Un même fichier PDF peut contenir PLUSIEURS textes juridiques
        # (ex. un numéro du Journal Officiel avec 4 décrets) : on les
        # sépare avant de chercher les articles, pour ne pas mélanger les
        # "Art. 1" de textes différents.
        sub_documents = self._split_into_subdocuments(full_text)
        logger.info(f"{file_path} : {len(sub_documents)} sous-document(s) juridique(s) détecté(s)")

        chunks: List[Chunk] = []
        for sub_text in sub_documents:
            chunks.extend(self._parse_single_document(sub_text, clean_title))

        return chunks

    # ------------------------------------------------------------------
    # Extraction page par page : texte natif si possible, OCR sinon
    # ------------------------------------------------------------------
    def _extract_pages(self, file_path: str) -> List[str]:
        pages_text: List[str] = []
        # Detect dominant language on first scanned page to choose OCR lang.
        # This avoids Arabic ghost characters in purely French documents.
        ocr_lang = self._detect_ocr_language(file_path)
        logger.info(f"OCR language chosen for {file_path}: {ocr_lang}")

        with pymupdf.open(file_path) as doc:
            for page_num, page in enumerate(doc):
                native = page.get_text("text") or ""
                if len(native.strip()) >= 40:
                    text = native + self._extract_tables_as_text(page)
                else:
                    text = self._ocr_page(page, tesseract_langs=ocr_lang)

                # Filter out specimen/diploma pages with very little
                # structured text (images of diplomas, rotated pages).
                if self._is_specimen_page(text):
                    logger.info(f"Page {page_num+1} filtered as specimen/noise")
                    continue

                text = self._strip_noise_lines(text)
                pages_text.append(text)
        return pages_text

    def _detect_ocr_language(self, file_path: str) -> str:
        """Sample the first non-empty scanned page to decide whether to use
        'fra' only or 'fra+ara'. Using fra+ara on purely French documents
        injects Arabic ghost characters (e.g. ‏عل‎ instead of 'de')."""
        try:
            with pymupdf.open(file_path) as doc:
                for page in doc:
                    native = page.get_text("text") or ""
                    if len(native.strip()) >= 40:
                        # Native text page, use it to detect language
                        return self._lang_from_text(native)
                    # Quick low-res OCR to detect language
                    pix = page.get_pixmap(dpi=150)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    sample = pytesseract.image_to_string(img, lang="fra+ara", config="--psm 6")
                    if len(sample.strip()) > 30:
                        return self._lang_from_text(sample)
        except Exception:
            pass
        return "fra+ara"  # default

    @staticmethod
    def _lang_from_text(text: str) -> str:
        """Return 'fra' if text is predominantly French/Latin, 'fra+ara'
        if it contains significant Arabic content."""
        arabic_chars = len(re.findall(r'[\u0600-\u06FF]', text))
        latin_chars = len(re.findall(r'[A-Za-zÀ-ÿ]', text))
        if arabic_chars > latin_chars * 0.15:
            return "fra+ara"
        return "fra"

    @staticmethod
    def _is_specimen_page(text: str) -> bool:
        """Detect diploma specimen pages that produce OCR noise.
        These pages have very little structured text relative to their
        total character count, or very short text overall."""
        clean = text.strip()
        if len(clean) < _MIN_PAGE_TEXT_LEN:
            return True
        # Count alphanumeric characters vs total
        alnum = len(re.findall(r'[\w]', clean, re.UNICODE))
        if alnum == 0:
            return True
        # High ratio of non-word chars = likely noise
        ratio = alnum / len(clean)
        if ratio < _MIN_STRUCTURED_RATIO:
            return True
        return False

    def _extract_tables_as_text(self, page) -> str:
        """Extrait les tableaux natifs (barèmes, taux horaires, crédits...)
        sous une forme lisible ligne par ligne, pour ne pas les laisser noyés
        dans le flux de texte brut."""
        out = ""
        try:
            tabs = page.find_tables()
        except Exception:
            return out
        table_list = getattr(tabs, "tables", tabs)
        for tab in table_list:
            try:
                rows = tab.extract()
            except Exception:
                continue
            if not rows:
                continue
            out += "\n[TABLEAU]\n"
            for row in rows:
                cells = [str(c).strip() if c is not None else "" for c in row]
                out += " | ".join(cells) + "\n"
            out += "[/TABLEAU]\n"
        return out

    def _ocr_page(self, page, tesseract_langs: str = "fra+ara") -> str:
        pix = page.get_pixmap(dpi=300)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        try:
            columns = self._split_columns(img)
        except Exception:
            columns = [img]

        texts = []
        for col_img in columns:
            texts.append(
                pytesseract.image_to_string(col_img, lang=tesseract_langs, config="--psm 4")
            )
        return "\n".join(texts)

    def _split_columns(self, img: "Image.Image") -> List["Image.Image"]:
        """Détecte une mise en page à 2 colonnes (typique du Journal
        Officiel) et renvoie les images à OCRiser dans l'ordre de lecture
        (colonne gauche puis colonne droite). Si aucune gouttière nette
        n'est détectée (page à 1 colonne), renvoie la page entière."""
        if not _HAS_NUMPY:
            return [img]

        gray = np.asarray(img.convert("L"))
        h, w = gray.shape
        col_brightness = gray.mean(axis=0)  # + clair = + de blanc = moins d'encre

        # On ne cherche la gouttière que dans la bande centrale (30%-70% de
        # la largeur), pour éviter de "couper" sur une marge latérale.
        lo, hi = int(w * 0.30), int(w * 0.70)
        band = col_brightness[lo:hi]
        if band.size == 0:
            return [img]

        gutter_x = lo + int(np.argmax(band))

        # La gouttière doit être nettement plus claire que la moyenne de la
        # page pour qu'on soit sûr qu'il s'agit bien d'un espace blanc entre
        # 2 colonnes ; seuil abaissé à +10 pour fiabiliser les scans âgés.
        if col_brightness[gutter_x] < col_brightness.mean() + 10:
            return [img]

        left = img.crop((0, 0, gutter_x, h))
        right = img.crop((gutter_x, 0, w, h))
        return [left, right]

    def _strip_noise_lines(self, text: str) -> str:
        lines = text.split('\n')
        kept = [ln for ln in lines if not any(rx.match(ln) for rx in _NOISE_LINE_RES)]
        return "\n".join(kept)

    # ------------------------------------------------------------------
    # Nettoyage texte
    # ------------------------------------------------------------------
    def _clean_text(self, text: str) -> str:
        text = unicodedata.normalize("NFKC", text)
        # Nettoyage des marqueurs directionnels Unicode invisibles
        text = re.sub(r'[\u200e\u200f\u202a-\u202e]', '', text)
        # Dé-hyphénation simple (mot coupé en fin de ligne par l'OCR)
        text = re.sub(r'(\w)-\n(\w)', r'\1\2', text)
        # Normalisation des espaces multiples
        text = re.sub(r'[ \t]+', ' ', text)
        # Pas plus de 2 sauts de ligne consécutifs
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    # ------------------------------------------------------------------
    # Segmentation multi-documents
    # ------------------------------------------------------------------
    def _split_into_subdocuments(self, full_text: str) -> List[str]:
        boundaries = []
        for m in _NEW_DOC_RE.finditer(full_text):
            if self._looks_like_new_document(full_text, m):
                boundaries.append(m.start())

        if len(boundaries) <= 1:
            return [full_text]

        sub_docs = []
        # Texte situé AVANT la 1re frontière (ex. "ETAT ANNEXE" budgétaire en
        # tête de page) : conservé comme sous-document à part, pas perdu.
        if len(full_text[:boundaries[0]].strip()) > 50:
            sub_docs.append(full_text[:boundaries[0]])
        for i, start in enumerate(boundaries):
            end = boundaries[i + 1] if i + 1 < len(boundaries) else len(full_text)
            sub_docs.append(full_text[start:end])
        return sub_docs

    def _looks_like_new_document(self, text: str, match: re.Match) -> bool:
        # Exclut les simples citations ("Vu le décret n°...", "modifiant le
        # décret exécutif n°...", "بمقتضى القرار رقم...").
        prefix_tail = text[max(0, match.start() - 40):match.start()]
        if _CITATION_CONTEXT_RE.search(prefix_tail):
            return False
        # Un véritable en-tête de texte est suivi, à portée raisonnable (jusqu'à
        # 1200 caractères vu la longueur possible des intitulés), d'une formule
        # d'autorité ("Le Chef du Gouvernement,", "إنّ وزير...", "ARRETE").
        lookahead = text[match.end(): match.end() + 1200]
        return bool(_AUTHORITY_INTRO_RE.search(lookahead))

    # ------------------------------------------------------------------
    # Parsing d'un seul texte juridique (préambule + articles)
    # ------------------------------------------------------------------
    def _parse_single_document(self, full_text: str, clean_title: str) -> List[Chunk]:
        # Sépare "Décrète : Article 1er" ou "ARRETE : Article 1er" s'ils sont sur la même ligne
        full_text = re.sub(
            r'(D[ée]cr[èe]te\s*:?|ARRETE\s*:?|يقرر\s+ما\s+يأتي\s*:?)\s*([‘“"\'»\-*~]?[ \t]*Art(?:icle)?\.?\s*1|[‘“"\'»\-*~]?[ \t]*المادة\s*(?:1|الأول[ىي]))',
            r'\1\n\2',
            full_text,
            flags=re.IGNORECASE
        )
        splits = _ARTICLE_RE.split(full_text)
        chunks: List[Chunk] = []

        preambule = splits[0].strip()
        preambule = re.sub(r'(?<!\n)\n(?!\n)', ' ', preambule)

        procedure_meta = self._detect_procedure(preambule, clean_title) or "Texte Juridique / نص قانوني"

        if len(preambule) > 50:
            chunks.append(self._make_chunk(
                text=f"Préambule / Objet du {procedure_meta} :\n{preambule}",
                clean_title=clean_title,
                procedure_meta=procedure_meta,
                article_title=None,
                chapter=None,
            ))

        current_chapter = None
        for i in range(1, len(splits), 2):
            art_title = splits[i].strip()
            art_body = splits[i + 1].strip() if i + 1 < len(splits) else ""

            # Un titre de chapitre/section peut s'être retrouvé collé en fin
            # de corps d'article (il annonce en fait l'article SUIVANT) : on
            # l'extrait et on le mémorise pour le chunk suivant plutôt que de
            # le laisser polluer celui-ci.
            next_chapter = None
            chap_match = _CHAPTER_RE.search(art_body)
            if chap_match:
                next_chapter = chap_match.group(1).strip()
                art_body = (art_body[:chap_match.start()] + art_body[chap_match.end():]).strip()

            art_body = re.sub(r'(?<!\n)\n(?!\n)', ' ', art_body)

            if any(k in art_body.lower() for k in _KEYWORDS_BAREMES):
                art_body = f"=== BARÈMES ET TAUX / معدلات وأجور ===\n{art_body}"

            if len(art_body) > 15:
                chunks.append(self._make_chunk(
                    text=f"{procedure_meta} | {art_title} :\n{art_body}",
                    clean_title=clean_title,
                    procedure_meta=procedure_meta,
                    article_title=art_title,
                    chapter=current_chapter,
                ))

            if next_chapter:
                current_chapter = next_chapter

        return chunks

    def _detect_procedure(self, preambule: str, file_path_or_title: str = "") -> Optional[str]:
        clean_preambule = re.sub(r'[\u200e\u200f\u202a-\u202e]', '', preambule)
        # Détection ETAT ANNEXE
        if "ETAT ANNEXE" in clean_preambule.upper():
            return "ETAT ANNEXE (Crédits budgétaires)"

        # 1. Vérifie d'abord les premières lignes du préambule (où se trouve le vrai titre)
        first_lines = "\n".join(clean_preambule.split("\n")[:12])
        doc_match = _PROCEDURE_RE.search(first_lines)
        if doc_match:
            return doc_match.group(1).strip().capitalize()

        # 2. Recherche sur tout le préambule
        doc_match = _PROCEDURE_RE.search(clean_preambule)
        if doc_match:
            return doc_match.group(1).strip().capitalize()

        # 3. Fallback en-tête
        header_match = re.search(
            r'((?:Arrêté|Décret|Décision|Loi|Ordonnance|قرار|مرسوم|قانون)'
            r'[^\n]{0,80})',
            clean_preambule, re.IGNORECASE
        )
        if header_match:
            cand = header_match.group(1).strip()
            cand = re.sub(r'[\s._%*]{3,}', ' ', cand).strip()
            return cand[:80].capitalize()

        # 4. Fallback vers le numéro extrait du nom de fichier
        if file_path_or_title:
            m = re.search(r'(\d+)', file_path_or_title)
            if m:
                arabic_chars = len(re.findall(r'[\u0600-\u06FF]', clean_preambule))
                latin_chars = len(re.findall(r'[A-Za-zÀ-ÿ]', clean_preambule))
                if arabic_chars > latin_chars:
                    return f"قرار رقم {m.group(1)}"
                return f"Arrêté n° {m.group(1)}"
        return None

    # ------------------------------------------------------------------
    # Construction du Chunk + métadonnées
    # ------------------------------------------------------------------
    def _make_chunk(self, text, clean_title, procedure_meta, article_title, chapter) -> Chunk:
        meta = ChunkMetadata(
            document_name=clean_title,
            family_type="F",
            procedure=procedure_meta,
            chapter=chapter,
            article_title=article_title,
            article_number=self._article_number(article_title),
            language=self._detect_language(text),
        )
        return Chunk(text=text, metadata=meta)

    @staticmethod
    def _set_optional_meta(meta, **kwargs):
        """N'affecte que les attributs déjà déclarés sur ChunkMetadata, pour
        rester compatible même si votre schéma actuel ne les définit pas
        encore (voir la note en tête de fichier)."""
        for k, v in kwargs.items():
            if v is None or not hasattr(meta, k):
                continue
            try:
                setattr(meta, k, v)
            except Exception:
                pass

    @staticmethod
    def _article_number(art_title: Optional[str]) -> Optional[int]:
        if not art_title:
            return None
        m = re.search(r'\d+', art_title)
        if m:
            return int(m.group())
        for word, num in _ARABIC_ORDINAL_MAP.items():
            if word in art_title:
                return num
        return None

    @staticmethod
    def _detect_language(text: str) -> str:
        arabic_chars = len(re.findall(r'[\u0600-\u06FF]', text))
        latin_chars = len(re.findall(r'[A-Za-zÀ-ÿ]', text))
        if arabic_chars and latin_chars:
            ratio = arabic_chars / max(latin_chars, 1)
            if 0.2 < ratio < 5:
                return "mixed"
        return "ar" if arabic_chars > latin_chars else "fr"