"""
Parser famille G : PV de délibération (jury) de la Faculté d'Informatique.

Deux sous-formats rencontrés (mais le code ne dépend pas d'un format « en dur » :
il classe les COLONNES par rôle, puis génère un chunk par étudiant) :

  1) « PV de délibération global »
     N° | Matricule | Nom et prénom | S1 (Moy/Créd) | S2 (Moy/Créd) | Annuel (Moy/Créd) | Décision

  2) « PV de délibération dette - Semestre X »
     "N° - NOM Prénom" | Matricule | [UE : matières + Moyenne UE + Crédit UE]* | Crédits/Moyenne du semestre
     (en-têtes de matières écrits en vertical dans le PDF, pas de décision individuelle,
      bilan global en pied de page)

Ce qui est produit pour le RAG :
  - 1 chunk « fiche du PV » (contexte, structure, effectifs, répartition des décisions) ;
  - 1 chunk par étudiant, AUTONOME (contexte du PV + identité + résultats en français
    + décision), donc retrouvable par nom, matricule, niveau, année ou semestre.

Principes anti sur-/sous-ajustement :
  - rôle des colonnes déduit du texte d'en-tête (insensible à l'ordre des mots), avec
    repli sur la structure (UE = matières + Moyenne UE + Crédit UE) puis sur le contenu
    des cellules (identité) ;
  - aucune valeur métier inventée : une case vide reste « non renseignée » ;
  - contrôles de cohérence (numérotation, effectif du pied de page) journalisés.
"""
import inspect
import logging
import os
import re
import unicodedata
from collections import Counter, OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

import pdfplumber

from core import Chunk, ChunkMetadata, BaseFamilyParser, ParserRegistry
from core.utils import SystemUtils, AcademicMetadataExtractor  # noqa: F401
from parsers.fallback import FallbackParser

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Rôles de colonnes
# ----------------------------------------------------------------------------
R_NUMERO, R_NUMERO_NOM, R_MATRICULE, R_NOM, R_DECISION = (
    "numero", "numero_nom", "matricule", "nom", "decision")
R_MOY, R_CRED = "moyenne", "credit"
R_MOY_UE, R_CRED_UE = "moyenne_ue", "credit_ue"
R_MOY_SEM, R_CRED_SEM = "moyenne_semestre", "credits_semestre"
R_MATIERE, R_OTHER = "matiere", "autre"

IDENTITY_ROLES = {R_NUMERO, R_NUMERO_NOM, R_MATRICULE, R_NOM, R_DECISION}
SEMESTER_ROLES = {R_MOY_SEM, R_CRED_SEM}
ROLE_WORDING = {
    R_MOY: "moyenne",
    R_CRED: "crédits",
    R_MOY_UE: "moyenne de l'UE",
    R_CRED_UE: "crédits de l'UE",
    R_MOY_SEM: "moyenne du semestre",
    R_CRED_SEM: "crédits du semestre",
}

NUM_NOM_RE = re.compile(r"^(\d{1,4})\s*[-–]\s*(.+)$")
NUMERO_RE = re.compile(r"^\d{1,4}$")
# Matricules vus : 232331592806, 23238PSE2069, 22229DZA107 -> alphanumérique majuscule, ≥1 chiffre
MATRICULE_RE = re.compile(r"^(?=.*\d)[0-9A-Z]{9,14}$")
GRADE_RE = re.compile(r"^\d{1,2}(?:[.,]\d{1,2})?$")
UE_CODE_RE = re.compile(r"^(?=.*\d)[A-Z0-9]{6,}$")

# Décisions parfois tronquées dans la cellule PDF -> forme complète (sinon valeur brute conservée)
DECISION_COMPLETIONS = (
    (re.compile(r"^admis\(e\)\s+avec\s*$", re.I), "Admis(e) avec dettes"),
    (re.compile(r"^admis\(e\)\s+\(session\s+r\w*\)?$", re.I), "Admis(e) (session rattrapage)"),
    (re.compile(r"^admis\(e\)\s+\(session\s+n\w*\)?$", re.I), "Admis(e) (session normale)"),
)

# ----------------------------------------------------------------------------
# Métadonnées de l'en-tête (extraites du texte, indépendamment de l'ordre des lignes)
# ----------------------------------------------------------------------------
_LABEL_END = (
    r"(?=\s*(?:Niveau|Fili[èe]re|Sp[ée]cialit[ée]|Domaine|Ann[ée]e\s+Acad[ée]mique|Arr[êe]t[ée])\s*:"
    r"|\s*\n|\s*$)"
)


def _labelled(label: str) -> "re.Pattern":
    return re.compile(label + r"\s*:\s*(.*?)" + _LABEL_END, re.I)


LEVEL_RE = re.compile(
    r"\b((?:Licence|Master|Doctorat|Ing[ée]nieur)\s+\d+\s*(?:[èe]re|[èe]me|er|e|nde)?(?:\s+Ann[ée]e)?)", re.I)
YEAR_RE = re.compile(r"\b(\d{4}\s*/\s*\d{4})\b")
DATE_PV_RE = re.compile(r"\bLe\s*:\s*(\d{2}[-/.]\d{2}[-/.]\d{4})")
ARRETE_RE = re.compile(r"Arr[êe]t[ée][^:\n]*:\s*(N°\s*\d+\s+du\s+\d{2}/\d{2}/\d{4})", re.I)
DEPT_RE = re.compile(r"D[ée]partement\s+[A-Za-zÀ-ÿ'’\- ]+")
_DEPT_STOP_RE = re.compile(r"\s*(?:Facult[ée]|Universit[ée]|Minist[èe]re|R[ée]publique)", re.I)
TITLE_RE = re.compile(r"PV\s+de\s+d[ée]lib[ée]ration([^\n]*)", re.I)

FOOTER_RES = {
    "total": re.compile(r"Nombre\s+total\s+des\s+[ée]tudiants\s*:?\s*(\d+)", re.I),
    "admis": re.compile(r"Nombre\s+total\s+(?:des\s+)?[ée]tudiants\s+admis\s*:?\s*(\d+)", re.I),
    "non_valides": re.compile(r"n[’'`´]ayant\s+pas\s+valid[ée]s?\s*:?\s*(\d+)", re.I),
}


# ----------------------------------------------------------------------------
# Petits utilitaires
# ----------------------------------------------------------------------------
def _clean(value) -> str:
    """Normalise une cellule : NFC, retours à la ligne / espaces multiples -> un espace."""
    if value is None:
        return ""
    return " ".join(unicodedata.normalize("NFC", str(value)).split())


@lru_cache(maxsize=1)
def _accepted_metadata_fields() -> Optional[frozenset]:
    """Champs acceptés par ChunkMetadata (None = tout accepter). Évite de casser si le
    modèle n'a pas (encore) les champs annee/niveau/semestre..."""
    for attr in ("model_fields", "__dataclass_fields__", "__fields__"):
        fields = getattr(ChunkMetadata, attr, None)
        if fields:
            return frozenset(fields)
    try:
        params = list(inspect.signature(ChunkMetadata).parameters.values())
    except (TypeError, ValueError):
        return None
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params):
        return None
    names = frozenset(p.name for p in params)
    return names or None


def _looks_like_student_row(row) -> bool:
    cells = [_clean(c) for c in row]
    firsts = [c for c in cells[:3] if c]
    if not firsts:
        return False
    ident_ok = any(NUM_NOM_RE.match(c) or NUMERO_RE.match(c) for c in firsts[:2])
    grades = sum(1 for c in cells if GRADE_RE.match(c))
    return ident_ok and grades >= 2


@dataclass
class _Col:
    index: int
    group: str   # en-tête de niveau supérieur (S1, Annuel, code d'UE...) ou ""
    label: str   # libellé de la colonne
    role: str


@dataclass
class _Student:
    numero: str
    nom: str
    matricule: str
    decision: Optional[str]
    cells: List[str]


@ParserRegistry.register("G")
class FamilyGParser(BaseFamilyParser):
    """Famille G : PV de délibération (résultats de jury), tous sous-formats."""

    _LABELLED = {
        "specialite": _labelled(r"Sp[ée]cialit[ée]"),
        "filiere": _labelled(r"Fili[èe]re"),
        "domaine": _labelled(r"Domaine"),
    }

    # ------------------------------------------------------------------ parse
    def parse(
        self,
        file_path: str,
        document_title: Optional[str] = None,
        effective_start_line: int = 0,
    ) -> List[Chunk]:
        clean_title = document_title if document_title else os.path.basename(file_path)
        chunks: List[Chunk] = []
        try:
            with pdfplumber.open(file_path) as pdf:
                raw_pages = [p.extract_text() or "" for p in pdf.pages]
                # effective_start_line ne sert qu'au texte libre (pied de page). Les métadonnées
                # sont lues sur le texte NON tronqué : c'est justement l'en-tête qu'on y cherche.
                footer_text = _clean_keep_lines(self._trim_lines(raw_pages, effective_start_line))
                page_metas = [self._extract_meta(t) for t in raw_pages]
                doc_meta: Dict[str, str] = {}
                for m in page_metas:
                    for k, v in m.items():
                        doc_meta.setdefault(k, v)

                cols: Optional[List[_Col]] = None
                legend_cols: Optional[List[_Col]] = None
                decisions: List[Optional[str]] = []
                numeros: List[int] = []
                student_chunks: List[Chunk] = []

                for idx, page in enumerate(pdf.pages):
                    try:
                        meta = {**doc_meta, **page_metas[idx]}
                        for tb in page.find_tables():
                            table = tb.extract()
                            if not table:
                                continue
                            header_rows, data_rows = self._split_header(table)
                            if header_rows:
                                self._repair_rotated_headers(page, tb, header_rows)
                                cols = self._classify_columns(self._header_labels(header_rows), data_rows)
                                legend_cols = legend_cols or cols
                                logger.debug("PV G p.%d colonnes : %s", idx + 1,
                                             [(c.index, c.group, c.label, c.role) for c in cols])
                            if cols is None:
                                continue  # tableau sans en-tête connu (rien à réutiliser)
                            has_decision = any(c.role == R_DECISION for c in cols)
                            for row in data_rows:
                                student = self._parse_student(row, cols)
                                if student is None:
                                    continue
                                if student.numero.isdigit():
                                    numeros.append(int(student.numero))
                                if has_decision:
                                    decisions.append(student.decision)
                                student_chunks.append(
                                    self._student_chunk(student, cols, meta, clean_title, idx + 1, has_decision))
                    except Exception as e:  # une page défaillante ne doit pas faire perdre les autres
                        logger.error("PV famille G : page %d ignorée dans %s : %s", idx + 1, file_path, e)

                if student_chunks:
                    footer = self._extract_footer(footer_text)
                    self._sanity_check(numeros, footer, len(student_chunks), clean_title)
                    overview = self._overview_chunk(
                        clean_title, doc_meta, legend_cols or [], decisions,
                        any(c.role == R_DECISION for c in (legend_cols or [])), numeros, footer)
                    chunks = [overview] + student_chunks
        except Exception as e:
            logger.error(f"Erreur d'extraction sémantique G sur {file_path}: {e}")

        return chunks if chunks else FallbackParser.parse_safe(file_path, "G")

    # ------------------------------------------------------- métadonnées PV
    @staticmethod
    def _trim_lines(pages: List[str], n: int) -> List[str]:
        if n <= 0:
            return pages
        out = []
        for text in pages:
            lines = text.split("\n")
            out.append("\n".join(lines[n:]) if n < len(lines) else "")
        return out

    def _extract_meta(self, text: str) -> Dict[str, str]:
        """Extraction par motifs, robuste au mélange des lignes de l'en-tête
        (« ...logicielsNiveau:Filière: Informatique... » ou « Année Académique:Niveau:Spécialité: ... »)."""
        text = unicodedata.normalize("NFC", text)
        meta: Dict[str, str] = {}
        for key, rx in self._LABELLED.items():
            m = rx.search(text)
            if m and _clean(m.group(1)):
                meta[key] = _clean(m.group(1))
        m = LEVEL_RE.search(text) or _labelled(r"Niveau").search(text)
        if m and _clean(m.group(1)):
            meta["niveau"] = _clean(m.group(1))
        for key, rx in (("annee", YEAR_RE), ("date_pv", DATE_PV_RE), ("arrete", ARRETE_RE)):
            m = rx.search(text)
            if m:
                meta[key] = _clean(m.group(1)).replace(" / ", "/")
        m = DEPT_RE.search(text)
        if m:
            meta["departement"] = _clean(_DEPT_STOP_RE.split(m.group(0))[0])
        t = TITLE_RE.search(text)
        if t:
            tail = t.group(1)
            kind = re.match(r"\s*[-–]?\s*([^\s\-–]+)", tail)
            if kind:
                meta["pv_type"] = kind.group(1).lower()
            sem = re.search(r"Semestre\s*(\d+)", tail, re.I)
            if sem:
                meta["semestre"] = sem.group(1)
        return meta

    @staticmethod
    def _extract_footer(text: str) -> Dict[str, str]:
        found = {}
        for key, rx in FOOTER_RES.items():
            m = rx.search(text)
            if m:
                found[key] = m.group(1)
        return found

    # ---------------------------------------------- en-têtes multi-lignes
    @staticmethod
    def _split_header(table: List[List[Optional[str]]]):
        """Les lignes d'en-tête sont celles qui précèdent la 1ère ligne « étudiant » (max. 4)."""
        for i in range(min(len(table), 4)):
            if _looks_like_student_row(table[i]):
                return table[:i], table[i:]
        return [], table  # page de continuation : pas d'en-tête, on réutilisera le précédent

    @staticmethod
    def _rotated_text(page, bbox) -> Optional[str]:
        """Reconstruit un texte écrit à la verticale dans une cellule d'en-tête. L'extraction
        native mélange les mots de ces cellules ; on suit l'ordre du flux PDF, qui est l'ordre
        de lecture (indépendant du sens de rotation)."""
        try:
            chars = page.crop(bbox).chars
        except Exception:
            return None
        rotated = [c for c in chars if not c.get("upright", True)]
        if not chars or len(rotated) < 0.5 * len(chars):
            return None
        lines: "OrderedDict[float, list]" = OrderedDict()
        for c in rotated:
            lines.setdefault(round(c["x0"]), []).append(c["text"])
        text = _clean(" ".join("".join(chs) for chs in lines.values()))
        return text or None

    def _repair_rotated_headers(self, page, table_obj, header_rows) -> None:
        for i, row in enumerate(header_rows):
            if i >= len(table_obj.rows):
                break
            for j, bbox in enumerate(table_obj.rows[i].cells):
                if bbox is None or j >= len(row):
                    continue
                text = self._rotated_text(page, bbox)
                if text:
                    row[j] = text

    @staticmethod
    def _header_labels(header_rows) -> List[Tuple[str, str]]:
        """-> [(groupe, libellé)] par colonne. Ligne du haut : None = cellule fusionnée (hérite du
        groupe de gauche), "" = cellule vide non fusionnée (pas d'héritage)."""
        ncols = max(len(r) for r in header_rows)
        rows = [list(r) + [None] * (ncols - len(r)) for r in header_rows]
        top, last = [], ""
        for v in rows[0]:
            if v is not None:
                last = _clean(v)
            top.append(last)
        bottom = rows[-1] if len(rows) > 1 else None
        labels = []
        for j in range(ncols):
            sub = _clean(bottom[j]) if bottom is not None else ""
            labels.append((top[j], sub) if sub else ("", top[j]))
        return labels

    # -------------------------------------------------- rôle des colonnes
    @staticmethod
    def _role_of(group: str, label: str) -> str:
        tokens = set(re.findall(r"\w+", f"{group} {label}".lower()))
        has = lambda prefix: any(t.startswith(prefix) for t in tokens)  # noqa: E731
        cred, moy = has("cr\u00e9d") or has("cred"), has("moy")
        if "matricule" in tokens:
            return R_MATRICULE
        if has("d\u00e9cision") or has("decision"):
            return R_DECISION
        if cred and "semestre" in tokens:
            return R_CRED_SEM
        if moy and "semestre" in tokens:
            return R_MOY_SEM
        if cred and "ue" in tokens:
            return R_CRED_UE
        if moy and "ue" in tokens:
            return R_MOY_UE
        first = (re.findall(r"\w+", label.lower()) or [""])[0]
        if first.startswith("moy"):
            return R_MOY
        if first.startswith("cr\u00e9d") or first.startswith("cred"):
            return R_CRED
        if "nom" in tokens or has("pr\u00e9nom") or has("prenom"):
            return R_NOM
        if label.strip().lower() in {"n°", "n", "no", "num", "numéro", "numero", "#"}:
            return R_NUMERO
        return R_MATIERE if group else R_OTHER

    def _classify_columns(self, labels: List[Tuple[str, str]], data_rows) -> List[_Col]:
        cols = [_Col(j, g, l, self._role_of(g, l)) for j, (g, l) in enumerate(labels)]
        self._positional_fallback(cols)
        self._infer_identity_from_content(cols, data_rows)
        return cols

    @staticmethod
    def _positional_fallback(cols: List[_Col]) -> None:
        """Groupe de ≥3 colonnes sans aucun agrégat reconnu = UE : matières puis Moyenne UE, Crédit UE."""
        groups: "OrderedDict[str, List[_Col]]" = OrderedDict()
        for c in cols:
            if c.group:
                groups.setdefault(c.group, []).append(c)
        for members in groups.values():
            if len(members) >= 3 and all(m.role in (R_MATIERE, R_OTHER) for m in members):
                for m in members[:-2]:
                    m.role = R_MATIERE
                members[-2].role, members[-1].role = R_MOY_UE, R_CRED_UE

    @staticmethod
    def _infer_identity_from_content(cols: List[_Col], data_rows) -> None:
        """En-têtes d'identité vides (cas « dette ») : on regarde le contenu des premières colonnes."""
        have = {c.role for c in cols}
        sample = data_rows[:15]
        for c in cols[:3]:
            if c.role != R_OTHER:
                continue
            vals = [_clean(r[c.index]) for r in sample if c.index < len(r)]
            vals = [v for v in vals if v]
            if not vals:
                continue

            def share(rx):
                return sum(1 for v in vals if rx.match(v)) / len(vals)

            if R_NUMERO_NOM not in have and share(NUM_NOM_RE) >= 0.6:
                c.role = R_NUMERO_NOM
            elif R_NUMERO not in have and R_NUMERO_NOM not in have and share(NUMERO_RE) >= 0.6:
                c.role = R_NUMERO
            elif R_MATRICULE not in have and share(MATRICULE_RE) >= 0.6:
                c.role = R_MATRICULE
            have.add(c.role)

    # ---------------------------------------------------- lignes d'étudiants
    @staticmethod
    def _canonical_decision(raw: str) -> Optional[str]:
        d = _clean(raw)
        if not d:
            return None
        for rx, full in DECISION_COMPLETIONS:
            if rx.match(d):
                return full
        return d

    def _parse_student(self, row, cols: List[_Col]) -> Optional[_Student]:
        cells = [_clean(c) for c in row]
        cells += [""] * (len(cols) - len(cells))
        numero = nom = matricule = decision = ""
        for c in cols:
            v = cells[c.index]
            if c.role == R_NUMERO_NOM:
                m = NUM_NOM_RE.match(v)
                if m:
                    numero, nom = m.group(1), m.group(2)
            elif c.role == R_NUMERO:
                numero = v
            elif c.role == R_NOM:
                nom = v
            elif c.role == R_MATRICULE:
                matricule = v
            elif c.role == R_DECISION:
                decision = v
        has_num = any(c.role in (R_NUMERO, R_NUMERO_NOM) for c in cols)
        if has_num and not NUMERO_RE.match(numero):
            return None  # ligne résiduelle (en-tête répété, pied de tableau...)
        if not nom and not matricule:
            return None
        # Le matricule peut être vide dans le PV : on garde quand même l'étudiant.
        return _Student(numero, nom, matricule, self._canonical_decision(decision), cells)

    # ------------------------------------------------------ rendu en texte
    @staticmethod
    def _split_label(label: str) -> Tuple[str, str]:
        m = re.match(r"^([^:]{1,40}?)\s*:\s*(.*)$", label)
        return (m.group(1).strip(), m.group(2).strip()) if m else (label.strip(), "")

    @staticmethod
    def _group_title(group: str) -> str:
        if not group:
            return "Autres informations"
        m = re.fullmatch(r"S\s*(\d+)", group, re.I) or re.fullmatch(r"Semestre\s*(\d+)", group, re.I)
        if m:
            return f"Semestre {m.group(1)}"
        if re.fullmatch(r"annuel(?:le)?", group, re.I):
            return "Résultat annuel"
        if UE_CODE_RE.match(group):
            return f"UE {group}"
        return group

    def _part(self, col: _Col, value: str) -> str:
        if col.role in ROLE_WORDING:
            return f"{ROLE_WORDING[col.role]} = {value}"
        name = self._split_label(col.label)[0] if col.label else f"colonne {col.index + 1}"
        return f"{name} = {value}"

    def _render_results(self, cols: List[_Col], cells: List[str]) -> List[str]:
        groups: "OrderedDict[str, List[str]]" = OrderedDict()
        bilan: List[str] = []
        for c in cols:
            v = cells[c.index] if c.index < len(cells) else ""
            if not v or c.role in IDENTITY_ROLES:
                continue
            if c.role in SEMESTER_ROLES:
                bilan.append(self._part(c, v))
            else:
                groups.setdefault(c.group, []).append(self._part(c, v))
        lines = [f"{self._group_title(g)} : {' ; '.join(parts)}." for g, parts in groups.items()]
        if bilan:
            lines.append(f"Bilan du semestre : {' ; '.join(bilan)}.")
        return lines

    @staticmethod
    def _context_line(meta: Dict[str, str]) -> str:
        pv = "PV de délibération"
        if meta.get("pv_type"):
            pv += f" {meta['pv_type']}"
        if meta.get("semestre"):
            pv += f" (semestre {meta['semestre']})"
        parts = [pv]
        for key, fmt in (("niveau", "{}"), ("filiere", "filière {}"),
                         ("specialite", "spécialité {}"), ("annee", "année académique {}")):
            if meta.get(key):
                parts.append(fmt.format(meta[key]))
        return " — ".join(parts) + "."

    # ------------------------------------------------------------ chunks
    def _make_metadata(self, **kwargs) -> ChunkMetadata:
        accepted = _accepted_metadata_fields()
        if accepted is not None:
            # Pass only declared fields to constructor; keep extras for models that accept them
            declared = {k: v for k, v in kwargs.items() if k in accepted}
            extras = {k: v for k, v in kwargs.items() if k not in accepted}
            try:
                m = ChunkMetadata(**declared)
                for k, v in extras.items():
                    try:
                        setattr(m, k, v)
                    except Exception:
                        try:
                            if m.model_extra is None:
                                object.__setattr__(m, 'model_extra', {})
                            m.model_extra[k] = v
                        except Exception:
                            pass
                return m
            except Exception:
                return ChunkMetadata.model_validate(kwargs)
        try:
            return ChunkMetadata(**kwargs)
        except Exception:
            return ChunkMetadata.model_validate(kwargs)

    def _student_chunk(self, s: _Student, cols, meta, title, page_no, has_decision) -> Chunk:
        ident = f"Étudiant : {s.nom or 'N/A'} — matricule {s.matricule or 'N/A'}"
        if s.numero:
            ident += f" — n° {s.numero} dans le PV"
        lines = [self._context_line(meta), ident + "."]
        lines += self._render_results(cols, s.cells)
        if has_decision:
            lines.append(f"Décision du jury : {s.decision or 'non renseignée (case vide dans le PV)'}.")
        return Chunk(
            text="\n".join(lines),
            metadata=self._make_metadata(
                document_name=title,
                family_type="G",
                matricule=s.matricule or None,
                decision=(s.decision or "Non renseignée") if has_decision else None,
                page=page_no,
                annee=meta.get("annee"),
                niveau=meta.get("niveau"),
                specialite=meta.get("specialite"),
                semestre=meta.get("semestre"),
                pv_type=meta.get("pv_type"),
                numero=s.numero or None,
            ),
        )

    def _describe_structure(self, cols: List[_Col]) -> List[str]:
        groups: "OrderedDict[str, List[_Col]]" = OrderedDict()
        for c in cols:
            if c.role in IDENTITY_ROLES or c.role in SEMESTER_ROLES or not c.group:
                continue
            groups.setdefault(c.group, [])
            if c.role == R_MATIERE:
                groups[c.group].append(c)
        lines = []
        for g, mats in groups.items():
            if not mats:
                continue
            items = []
            for m in mats:
                short, desc = self._split_label(m.label)
                items.append(f"{short} ({desc})" if desc else short)
            lines.append(f"{self._group_title(g)} : {', '.join(items)}.")
        return lines

    def _overview_chunk(self, title, meta, cols, decisions, has_decision, numeros, footer) -> Chunk:
        lines = [f"Présentation du PV : {self._context_line(meta)}"]
        extra = []
        if meta.get("departement"):
            extra.append(meta["departement"])
        if meta.get("domaine"):
            extra.append(f"domaine {meta['domaine']}")
        if meta.get("arrete"):
            extra.append(f"arrêté d'habilitation {meta['arrete']}")
        if meta.get("date_pv"):
            extra.append(f"PV daté du {meta['date_pv']}")
        if extra:
            lines.append(" ; ".join(extra) + ".")
        structure = self._describe_structure(cols)
        if structure:
            lines.append("Structure du PV (unités d'enseignement et matières) :")
            lines += structure
        if numeros:
            lines.append(f"Étudiants listés dans le PV : {len(numeros)} (n° {min(numeros)} à {max(numeros)}).")
        if has_decision and decisions:
            counts = Counter(d or "sans décision renseignée" for d in decisions)
            detail = " ; ".join(f"{k} : {v}" for k, v in counts.most_common())
            lines.append(f"Répartition des décisions du jury (comptage automatique des lignes du PV) : {detail}.")
        if footer:
            labels = (("total", "total des étudiants"), ("admis", "admis"),
                      ("non_valides", "n'ayant pas validé"))
            parts = [f"{lab} {footer[k]}" for k, lab in labels if k in footer]
            lines.append(f"Bilan indiqué en pied de PV : {', '.join(parts)}.")
        return Chunk(
            text="\n".join(lines),
            metadata=self._make_metadata(
                document_name=title,
                family_type="G",
                matricule=None,
                decision=None,
                page=-1,
                annee=meta.get("annee"),
                niveau=meta.get("niveau"),
                specialite=meta.get("specialite"),
                semestre=meta.get("semestre"),
                pv_type=meta.get("pv_type"),
                numero=None,
            ),
        )

    # ------------------------------------------------------ cohérence
    @staticmethod
    def _sanity_check(numeros: List[int], footer: Dict[str, str], n_students: int, title: str) -> None:
        if numeros:
            missing = sorted(set(range(min(numeros), max(numeros) + 1)) - set(numeros))
            if missing:
                logger.warning("PV G %s : numéros manquants (lignes perdues ?) : %s", title, missing[:30])
            dups = [n for n, c in Counter(numeros).items() if c > 1]
            if dups:
                logger.warning("PV G %s : numéros en double : %s", title, dups[:30])
        if footer.get("total") and int(footer["total"]) != n_students:
            logger.warning("PV G %s : %d étudiants extraits, le pied de page en annonce %s",
                           title, n_students, footer["total"])
        logger.info("PV G %s : %d étudiants extraits", title, n_students)


def _clean_keep_lines(pages: List[str]) -> str:
    """Texte multi-pages en NFC, en conservant les retours à la ligne (utile aux regex de pied de page)."""
    return unicodedata.normalize("NFC", "\n".join(pages))