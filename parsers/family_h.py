import re
import os
import logging
import pdfplumber
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

from core import Chunk, ChunkMetadata, BaseFamilyParser, ParserRegistry
from core.utils import SystemUtils, AcademicMetadataExtractor
from parsers.fallback import FallbackParser


logger = logging.getLogger("RAG_USTHB")


class _ScheduleBlock:
    def __init__(self, metadata: Dict[str, str]):
        self.metadata = dict(metadata)
        self.sessions_by_day: "OrderedDict[str, List[dict]]" = OrderedDict()
        self.time_slots: List[str] = []
        self.last_day: Optional[str] = None


@ParserRegistry.register("H")
class FamilyHParser(BaseFamilyParser):
    """
    Famille H : Emplois du temps (grille Jour x Créneau).

    Stratégie :
      - segmentation multi-sections : un bloc d'emploi du temps par section/formation,
      - un chunk par jour (jours vides inclus : "Aucune séance programmée ce jour-là"),
      - séances triées par créneau, une ligne autonome par séance,
      - jours et modalités normalisés (FR + libellé d'origine) pour la recherche,
      - aucune perte d'information : ce qui n'est pas reconnu est conservé en brut.
    """

    # ------------------------------------------------------------------ regex
    # Marqueur de groupe : "G3:" ou "G1+G2:" / "G1,G2:"
    _GROUP = r"G\d+(?:\s*[,+&]\s*G\d+)*"

    # Séance TP/TD : "G3:TP.C6/Iden Acces -- PW, EL NAGGER" (groupe et enseignant optionnels)
    # Supporte "--", "––", ainsi que "- -" ou "– –"
    CELL_ENTRY_RE = re.compile(
        rf"^(?:(?P<groupe>{_GROUP})\s*:\s*)?"
        r"(?P<salle>[^/]+?)\s*/\s*"
        r"(?P<module>.+?)\s*(?:[-–]\s*[-–]|[-–]{2})\s*"
        r"(?P<modalite>[A-Za-z]+)\s*,?\s*(?P<enseignant>.*)$"
    )

    # Cours magistral : "Wir Mob Net Security course :DGUERROUMI"
    COURSE_RE = re.compile(
        r"^(?P<module>.+?)\s*\bcours(?:e)?\s*:\s*(?P<tail>.+)$", re.IGNORECASE
    )

    # Cours à distance : "TCE (à distance)", "BUR et WEB (à distance)", "Cours TIC (a distance)"
    REMOTE_RE = re.compile(
        r"^(?:Cours\s+)?(?P<module>.+?)\s*\((?:à|a)\s*distance\)$", re.IGNORECASE
    )

    # Dans un cours, salle et enseignant sont collés ("SCzeraoulia", "C203LAIDOUI",
    # "salle cours2EL NAGGER", "DGUERROUMI", "143TGueraichi", "en ligneBOUATROUS").
    # On reconnaît des formes de salle génériques, le reste est l'enseignant.
    COURSE_ROOM_RE = re.compile(
        r"^(?P<salle>"
        r"(?i:salle\s*(?:cours\s*|td\s*)?\d*)"      # salle cours2, salle TD
        r"|(?i:amphi\s*[A-Za-z]?\d*)"              # amphi, Amphi A, amphi 3
        r"|(?i:en\s+ligne)"                        # en ligne
        r"|\d{2,3}[A-Za-z]"                       # 143T, 117D, 244T
        r"|LABO"                                  # LABO
        r"|[A-Z]{1,2}\d+"                         # C203, D4, R4, E1, E8
        r"|SC"                                    # salle de cours
        r"|[A-Z](?=[A-Z]{3,}|[A-Z][a-z]{2,})"      # D + GUERROUMI, J + Benbaziz, S + Hafsi
        r"|T\."                                   # T.
        r")\s*(?P<enseignant>.*)$"
    )

    GROUP_SPLIT_RE = re.compile(rf"(?<![\w,+&])(?<![,+&] )(?={_GROUP}\s*:)")
    TIME_RE = re.compile(r"\d{1,2}\s*[:hH]\s*\d{2}\s*[-–]\s*\d{1,2}\s*[:hH]\s*\d{2}")

    META_RE = {
        "formation": re.compile(r"(?:Schedules?\s+of|Emploi\s+du\s+temps(?:\s+de)?)\s*:?\s*(.+)", re.I),
        "annee_universitaire": re.compile(r"(?:College\s+year|Ann[ée]e\s+universitaire)\s*:\s*([\d/\-]+)", re.I),
        "niveau": re.compile(r"(?:Semester|Semestre)\s*:\s*(\d+)", re.I),
        "date_version": re.compile(r"\bDate\s*:\s*([\d/.\-]+)", re.I),
    }

    DAYS = {
        "sat": "Samedi", "sam": "Samedi",
        "sun": "Dimanche", "dim": "Dimanche",
        "mon": "Lundi", "lun": "Lundi",
        "tue": "Mardi", "mar": "Mardi",
        "wed": "Mercredi", "mer": "Mercredi",
        "thu": "Jeudi", "jeu": "Jeudi",
        "fri": "Vendredi", "ven": "Vendredi",
    }

    MODALITIES = {
        "PW": "TP", "TP": "TP", "LAB": "TP",
        "TD": "TD", "ED": "TD", "TUT": "TD", "DW": "TD",
    }

    @classmethod
    def _is_valid_day(cls, text: str) -> bool:
        if not text:
            return False
        key = re.sub(r"[^a-zA-Z]", "", text).lower()[:3]
        return key in cls.DAYS

    # ------------------------------------------------------------------ parse
    def parse(
        self,
        file_path: str,
        document_title: Optional[str] = None,
        effective_start_line: int = 0,
    ) -> List[Chunk]:
        # NB : effective_start_line est conservé pour la compatibilité d'interface.
        # Il n'est plus utilisé : les tableaux sont extraits indépendamment du texte,
        # et tronquer le texte risquait de supprimer les métadonnées (formation, date...).
        clean_title = document_title if document_title else os.path.basename(file_path)
        chunks: List[Chunk] = []

        try:
            with pdfplumber.open(file_path) as pdf:
                blocks: List[_ScheduleBlock] = []
                current_block: Optional[_ScheduleBlock] = None
                global_meta: Dict[str, str] = {}

                for page in pdf.pages:
                    page_text = page.extract_text() or ""
                    page_meta = self._extract_metadata(page_text)
                    if not global_meta:
                        global_meta = dict(page_meta)

                    formation = page_meta.get("formation")
                    if formation:
                        # Nouvelle section détectée si formation différente ou premier bloc
                        if current_block is None or current_block.metadata.get("formation") != formation:
                            merged_meta = dict(global_meta)
                            merged_meta.update(page_meta)
                            current_block = _ScheduleBlock(merged_meta)
                            blocks.append(current_block)
                        else:
                            current_block.metadata.update(page_meta)
                    elif current_block is None:
                        current_block = _ScheduleBlock(global_meta)
                        blocks.append(current_block)

                    # Extraire les grilles d'emplois du temps (ignorer mini-tableaux de légende < 3 colonnes)
                    for table in page.extract_tables() or []:
                        if not table or not table[0] or len(table[0]) < 3:
                            continue
                        current_block.time_slots, current_block.last_day = self._process_table(
                            table,
                            current_block.time_slots,
                            current_block.last_day,
                            current_block.sessions_by_day,
                        )

            # Génération des chunks par section et par jour
            for block in blocks:
                if not block.sessions_by_day and not block.time_slots:
                    continue

                header = self._build_header(block.metadata)

                for day, day_sessions in block.sessions_by_day.items():
                    day_sessions.sort(key=lambda s: s["slot_idx"])
                    if day_sessions:
                        body = "\n".join(self._seance_to_sentence(s) for s in day_sessions)
                    else:
                        body = "Aucune séance programmée ce jour-là (pas de cours, TD ni TP)."
                    chunks.append(Chunk(
                        text=f"{header}\n{self._day_label(day)} :\n{body}",
                        metadata=ChunkMetadata(
                            document_name=clean_title,
                            family_type="H",
                            formation=block.metadata.get("formation"),
                            annee_universitaire=block.metadata.get("annee_universitaire"),
                            niveau=block.metadata.get("niveau"),
                            date_version=block.metadata.get("date_version"),
                        ),
                    ))

        except Exception as e:
            logger.error(f"Erreur d'extraction sémantique H sur {file_path}: {e}")
            chunks = []

        return chunks if chunks else FallbackParser.parse_safe(file_path, "H")

    # -------------------------------------------------------------- tableaux
    def _process_table(
        self,
        table: List[List[Optional[str]]],
        time_slots: List[str],
        last_day: Optional[str],
        sessions_by_day: Dict[str, List[dict]],
    ) -> Tuple[List[str], Optional[str]]:
        """Traite un tableau. Filtre les lignes non pertinentes et associe les séances."""
        if not table:
            return time_slots, last_day

        header_idx = next(
            (i for i, r in enumerate(table)
             if r and any(self.TIME_RE.search(self._clean(c)) for c in r[1:])),
            None,
        )
        if header_idx is not None:
            time_slots = [self._clean(c) for c in table[header_idx]]
            data_rows = table[header_idx + 1:]
        elif time_slots:          # page de continuation : on réutilise l'en-tête précédent
            data_rows = table
        else:
            return time_slots, last_day

        for row in data_rows:
            if not row:
                continue

            first_cell = self._clean(row[0])
            if first_cell:
                if not self._is_valid_day(first_cell):
                    # Ignorer les lignes de légende, sous-titres ou numéros de salle parasites
                    continue
                day = first_cell
                last_day = day
                sessions_by_day.setdefault(day, [])
            elif last_day is None:
                continue
            else:
                day = last_day    # ligne de continuation d'un jour

            for i, cell in enumerate(row):
                if i == 0:
                    continue
                slot = time_slots[i] if i < len(time_slots) and time_slots[i] else "Heure inconnue"
                for raw_entry in self._split_cell(cell):
                    seance = self._parse_entry(raw_entry)
                    if seance["type_seance"] == "non_reconnu":
                        logger.warning(f"H: séance non reconnue ({day}, {slot}): {raw_entry!r}")
                    seance.update({"jour": day, "creneau": slot, "slot_idx": i})
                    sessions_by_day[day].append(seance)

        return time_slots, last_day

    # ------------------------------------------------------------ métadonnées
    def _extract_metadata(self, text: str) -> Dict[str, str]:
        metadata: Dict[str, str] = {}
        for key, pattern in self.META_RE.items():
            m = pattern.search(text)
            if m:
                metadata[key] = m.group(1).strip()
        return metadata

    @staticmethod
    def _build_header(md: Dict[str, str]) -> str:
        details = []
        if md.get("annee_universitaire"):
            details.append(f"année universitaire {md['annee_universitaire']}")
        if md.get("niveau"):
            details.append(f"semestre {md['niveau']}")
        if md.get("date_version"):
            details.append(f"version du {md['date_version']}")
        header = f"Emploi du temps — {md.get('formation', 'formation inconnue')}"
        return f"{header} ({', '.join(details)})" if details else header

    def _day_label(self, raw_day: str) -> str:
        """'Sun' -> 'Dimanche (Sun)' pour matcher les requêtes FR tout en gardant l'original."""
        key = re.sub(r"[^a-zA-Z]", "", raw_day.lower())[:3]
        fr = self.DAYS.get(key)
        return f"{fr} ({raw_day})" if fr and fr.lower() != raw_day.lower() else raw_day

    # ---------------------------------------------------------------- cellules
    @staticmethod
    def _clean(text: Optional[str]) -> str:
        return re.sub(r"\s+", " ", text).strip() if text else ""

    @classmethod
    def _split_cell(cls, cell_text: Optional[str]) -> List[str]:
        """Une cellule peut contenir plusieurs séances empilées (marquées par 'G<n>:')."""
        flat = cls._clean(cell_text)
        if not flat:
            return []
        if cls.GROUP_SPLIT_RE.search(flat):
            return [p.strip() for p in cls.GROUP_SPLIT_RE.split(flat) if p.strip()]
        return [flat]

    @classmethod
    def _parse_entry(cls, raw: str) -> dict:
        """Identifie le type de séance (TP/TD vs Cours vs Distance) et extrait les composants."""
        # 1. TP / TD
        m = cls.CELL_ENTRY_RE.match(raw)
        if m:
            modalite = m.group("modalite").strip()
            return {
                "type_seance": "TP/TD",
                "groupe": m.group("groupe"),
                "salle": m.group("salle").strip(),
                "module": m.group("module").strip(),
                "modalite": modalite,
                "modalite_norm": cls.MODALITIES.get(modalite.upper(), modalite),
                "enseignant": m.group("enseignant").strip(" .,;"),
            }

        # 2. Cours à distance (TCE, BUR et WEB, TIC...)
        m_remote = cls.REMOTE_RE.match(raw)
        if m_remote:
            return {
                "type_seance": "Cours",
                "groupe": None,
                "module": m_remote.group("module").strip(),
                "salle": "à distance",
                "enseignant": None,
                "salle_enseignant_brut": "à distance",
            }

        # 3. Cours magistral
        m2 = cls.COURSE_RE.match(raw)
        if m2:
            tail = m2.group("tail").strip()
            room = cls.COURSE_ROOM_RE.match(tail)
            return {
                "type_seance": "Cours",
                "groupe": None,
                "module": m2.group("module").strip(),
                "salle": room.group("salle").strip() if room else None,
                "enseignant": room.group("enseignant").strip(" .,;") if room else None,
                "salle_enseignant_brut": tail,
            }

        return {"type_seance": "non_reconnu", "texte_brut": raw}

    # ---------------------------------------------------------------- phrases
    @staticmethod
    def _seance_to_sentence(s: dict) -> str:
        """Une ligne autonome par séance (compréhensible même hors du chunk)."""
        slot = s["creneau"]

        if s["type_seance"] == "TP/TD":
            mod, norm = s["modalite"], s["modalite_norm"]
            kind = norm if norm.upper() == mod.upper() else f"{norm} ({mod})"
            who = f"groupe {s['groupe']}" if s.get("groupe") else "groupe non précisé"
            parts = [f"- {slot} : {kind} {s['module']} — {who}", f"salle {s['salle']}"]
            if s.get("enseignant"):
                parts.append(f"enseignant {s['enseignant']}")
            return ", ".join(parts) + "."

        if s["type_seance"] == "Cours":
            parts = [f"- {slot} : Cours {s['module']} — section entière"]
            if s.get("salle") or s.get("enseignant"):
                if s.get("salle"):
                    r = s["salle"]
                    if r.lower() in ["à distance", "en ligne"]:
                        parts.append(r)
                    else:
                        parts.append(r if r.lower().startswith("salle") else f"salle {r}")
                if s.get("enseignant"):
                    parts.append(f"enseignant {s['enseignant']}")
            else:
                parts.append(f"salle/enseignant : {s['salle_enseignant_brut']}")
            return ", ".join(parts) + "."

        return f"- {slot} : {s.get('texte_brut', 'Erreur extraction')}"