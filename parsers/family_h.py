



import re
import os
import logging
import pdfplumber
from typing import List, Optional

from core import Chunk, ChunkMetadata, BaseFamilyParser, ParserRegistry
from core.utils import SystemUtils, AcademicMetadataExtractor
from parsers.fallback import FallbackParser


logger = logging.getLogger("RAG_USTHB")

@ParserRegistry.register("H")
class FamilyHParser(BaseFamilyParser):
    """
    Famille H : Emplois du temps (Grille horaire Jour x Créneau).
    Éclate les séances empilées (TP/TD/Cours) via regex et génère un chunk par jour.
    """
    
    # Regex pour parser une séance de TP/TD : "G3:TP.C6/Iden Acces -- PW, EL NAGGER"
    CELL_ENTRY_RE = re.compile(
        r"(?:(?P<groupe>G\d+):)?(?P<salle>[^/]+)/(?P<module>[^-\n]+?)\s*--\s*"
        r"(?P<modalite>[A-Za-z]+),?\s*(?P<enseignant>.+)"
    )
    # Regex pour parser un cours magistral : "Wir Mob Net Security course :DGUERROUMI"
    COURSE_RE = re.compile(r"(?P<module>.+?)\s*course\s*:\s*(?P<salle_enseignant>.+)", re.IGNORECASE)
    
    META_RE = {
        "formation": re.compile(r"Schedules of\s*:\s*(.+)"),
        "annee_universitaire": re.compile(r"College year:\s*([\d/]+)"),
        "niveau": re.compile(r"Semester:\s*(\d+)"),
        "date_version": re.compile(r"Date:\s*([\d/]+)"),
    }

    def parse(self, file_path: str, document_title: Optional[str] = None) -> List[Chunk]:
        # --- AJOUT : Détermination du titre propre ---
        clean_title = document_title if document_title else os.path.basename(file_path)
        chunks = []
        try:
            with pdfplumber.open(file_path) as pdf:
                full_text = ""
                for page in pdf.pages:
                    full_text += page.extract_text() + "\n"
                
                # 1. Extraction des métadonnées globales
                metadata = {}
                for key, pattern in self.META_RE.items():
                    m = pattern.search(full_text)
                    if m:
                        metadata[key] = m.group(1).strip()

                # 2. Regrouper les séances par jour (au cas où le tableau déborde sur plusieurs pages)
                sessions_by_day = {}

                for page in pdf.pages:
                    tables = page.extract_tables()
                    if not tables:
                        continue
                    
                    table = tables[0]
                    # Nettoyage des en-têtes horaires (ex: "16:20 -\n17:50" -> "16:20 - 17:50")
                    time_slots = [re.sub(r'\s*\n\s*', ' ', c).strip() if c else "" for c in table[0][1:]]

                    for row in table[1:]:
                        if not row or not row[0]:
                            continue
                        day = row[0].strip()
                        
                        for i, cell in enumerate(row[1:]):
                            time_slot = time_slots[i] if i < len(time_slots) else "Heure inconnue"
                            
                            # Éclatement de la cellule en sous-entrées
                            for raw_entry in self._split_cell(cell):
                                seance = self._parse_entry(raw_entry)
                                seance["jour"] = day
                                seance["creneau"] = time_slot
                                
                                if day not in sessions_by_day:
                                    sessions_by_day[day] = []
                                sessions_by_day[day].append(seance)

                # 3. Création d'un chunk par jour non vide
                header = (
                    f"Emploi du temps — {metadata.get('formation', 'Inconnue')} "
                    f"({metadata.get('annee_universitaire', '')}, Semestre {metadata.get('niveau', '')}, "
                    f"Version du {metadata.get('date_version', '')})"
                )

                for day, day_sessions in sessions_by_day.items():
                    body_sentences = [self._seance_to_sentence(s) for s in day_sessions]
                    chunk_text = f"{header}\n{day} :\n" + "\n".join(body_sentences)
                    
                    chunks.append(Chunk(
                        text=chunk_text,
                        metadata=ChunkMetadata(
                            document_name=clean_title,
                            family_type="H",
                            formation=metadata.get("formation"),
                            annee_universitaire=metadata.get("annee_universitaire"),
                            niveau=metadata.get("niveau"),
                            date_version=metadata.get("date_version")
                        )
                    ))

        except Exception as e:
            logger.error(f"Erreur d'extraction sémantique H sur {file_path}: {e}")

        return chunks if chunks else FallbackParser.parse_safe(file_path, "H")

    # --- Méthodes utilitaires statiques ---

    @staticmethod
    def _split_cell(cell_text: Optional[str]) -> List[str]:
        r"""Une cellule peut contenir plusieurs séances empilées (marquées par G\d+:)."""
        if not cell_text or not cell_text.strip():
            return []
        # On aplatit les sauts de ligne pour faciliter le split
        flat = cell_text.replace("\n", " ")
        flat = re.sub(r'\s{2,}', ' ', flat).strip()
        
        if re.search(r"G\d+:", flat):
            # Si on trouve des marqueurs de groupe, on sépare sur ce marqueur
            parts = re.split(r"(?=G\d+:)", flat)
            return [p.strip() for p in parts if p.strip()]
        return [flat]

    @staticmethod
    def _parse_entry(raw: str) -> dict:
        """Identifie le type de séance (TP/TD vs Cours) et extrait les composants."""
        m = FamilyHParser.CELL_ENTRY_RE.match(raw)
        if m:
            return {
                "type_seance": "TP/TD",
                "groupe": m.group("groupe"),
                "salle": m.group("salle").strip(),
                "module": m.group("module").strip(),
                "modalite": m.group("modalite").strip(),
                "enseignant": m.group("enseignant").strip(),
            }
        
        m2 = FamilyHParser.COURSE_RE.match(raw)
        if m2:
            return {
                "type_seance": "Cours",
                "groupe": "Tous",
                "module": m2.group("module").strip(),
                "salle_enseignant_brut": m2.group("salle_enseignant").strip(),
            }
        
        return {"type_seance": "non_reconnu", "texte_brut": raw}

    @staticmethod
    def _seance_to_sentence(s: dict) -> str:
        """Convertit un dictionnaire de séance en une phrase lisible par un humain/LLM."""
        if s["type_seance"] == "TP/TD":
            return (
                f"- {s['creneau']} : groupe {s['groupe']} — {s['module']} "
                f"({s['modalite']}), salle {s['salle']}, enseignant {s['enseignant']}."
            )
        if s["type_seance"] == "Cours":
            return (
                f"- {s['creneau']} : cours de {s['module']} (groupe entier), "
                f"salle/enseignant : {s['salle_enseignant_brut']}."
            )
        return f"- {s['creneau']} : {s.get('texte_brut', 'Erreur extraction')}"