import os
import re
import logging
from typing import List, Optional
import pymupdf  # Remplacement de PyMuPDF

from core import Chunk, ChunkMetadata, BaseFamilyParser, ParserRegistry
from core.utils import SystemUtils, AcademicMetadataExtractor
from parsers.fallback import FallbackParser

logger = logging.getLogger("RAG_USTHB")

@ParserRegistry.register("J")
class FamilyJParser(BaseFamilyParser):
    """
    Famille J : Organigrammes et schémas vectoriels.
    Extrait les boîtes textuelles et infère la hiérarchie parent/enfant via coordonnées géométriques.
    Gère aussi les documents de répartition contenant des listes et petits tableaux.
    """
    
    def parse(
        self, 
        file_path: str, 
        document_title: Optional[str] = None,
        effective_start_line: int = 0
    ) -> List[Chunk]:
        chunks = []
        try:
            # --- AJOUT : Vérification sur le titre propre ---
            title_to_check = (document_title if document_title else os.path.basename(file_path)).lower()

            
            # 1. Si c'est l'organigramme pur (dessin vectoriel avec boîtes)
            # (effective_start_line n'est pas transmis car la logique dépend de BBox absolues, pas de lignes de texte)
            if "organigramme" in title_to_check:
                chunks.extend(self._parse_organigramme_boxes(file_path, document_title))
            # 2. Si c'est le document de répartition (texte, listes à puces, frises)
            else:
                chunks.extend(self._parse_repartition_text(file_path, document_title, effective_start_line))
                
        except Exception as e:
            logger.error(f"Erreur d'extraction sémantique J sur {file_path}: {e}")

        return chunks if chunks else FallbackParser.parse_safe(file_path, "J")

    def _parse_organigramme_boxes(self, file_path: str, document_title: Optional[str] = None) -> List[Chunk]:
        chunks = []
        doc = pymupdf.open(file_path)
        clean_title = document_title if document_title else os.path.basename(file_path)
        
        for page_num, page in enumerate(doc):
            # 1. Récupérer les rectangles dessinés
            rects = []
            for d in page.get_drawings():
                for item in d["items"]:
                    if item[0] == "re":  # 're' = rectangle
                        r = item[1]
                        # Filtrer les micros-rectangles (bruit vectoriel)
                        if r.width > 30 and r.height > 10:
                            rects.append(r)
            
            # 2. Récupérer le texte par blocs
            text_instances = []
            for b in page.get_text("dict")["blocks"]:
                for l in b.get("lines", []):
                    for s in l.get("spans", []):
                        if s["text"].strip():
                            text_instances.append({
                                "bbox": pymupdf.Rect(s["bbox"]), 
                                "text": s["text"].strip()
                            })
            
            # 3. Assigner le texte aux boîtes (chevauchement BBox)
            nodes = []
            for r_idx, r in enumerate(rects):
                node_text = []
                for t in text_instances:
                    if r.intersects(t["bbox"]):
                        node_text.append(t["text"])
                
                if node_text:
                    # Nettoyage des espaces multiples dus aux sauts de ligne
                    label = " ".join(node_text)
                    label = re.sub(r'\s{2,}', ' ', label).strip()
                    
                    center_x = r.x0 + r.width / 2
                    bottom_y = r.y1
                    top_y = r.y0
                    nodes.append({
                        "id": r_idx, 
                        "label": label, 
                        "cx": center_x, 
                        "top": top_y, 
                        "bottom": bottom_y
                    })
            
            # 4. Inférer la hiérarchie (Parent au-dessus de l'enfant et aligné sur X)
            for child in nodes:
                best_parent = None
                min_dist = float('inf')
                
                for parent in nodes:
                    if parent["id"] == child["id"]: 
                        continue
                    dy = child["top"] - parent["bottom"]
                    dx = abs(child["cx"] - parent["cx"])
                    
                    # Tolérance géométrique : le parent est au-dessus (dy>0) et aligné
                    if 0 < dy < 80 and dx < 50:
                        if dy < min_dist:
                            min_dist = dy
                            best_parent = parent
                
                parent_label = best_parent["label"] if best_parent else "Racine (Décanat / Direction Supérieure)"
                
                chunks.append(Chunk(
                    text=f"Entité structurelle de la Faculté : {child['label']}. Rattachée hiérarchiquement à : {parent_label}.",
                    metadata=ChunkMetadata(
                        document_name=clean_title, # Utilisation du titre ici
                        family_type="J",
                        page=page_num + 1,
                        node_entity=child['label'],
                        parent_entity=parent_label
                    )
                ))
                
        doc.close()
        return chunks

    def _parse_repartition_text(
        self, 
        file_path: str, 
        document_title: Optional[str] = None,
        effective_start_line: int = 0
    ) -> List[Chunk]:
        """Extrait les listes à puces et frises chronologiques des documents de répartition."""
        chunks = []
        doc = pymupdf.open(file_path)
        clean_title = document_title if document_title else os.path.basename(file_path)
        
        for page_num, page in enumerate(doc):
            text = page.get_text()
            if not text.strip(): 
                continue
                
            # --- AJOUT : Tronquer l'en-tête institutionnel sur la 1ère page ---
            if page_num == 0 and effective_start_line > 0:
                lines = text.split('\n')
                if effective_start_line < len(lines):
                    text = "\n".join(lines[effective_start_line:])
                else:
                    text = ""
            
            # Nettoyage des numéros de page/dates parasites (ex: "1/10/2022 2")
            lines = text.split('\n')
            clean_lines = []
            for line in lines:
                # Ignore les lignes qui sont juste des dates de présentation + numéro de page
                if re.match(r'^\d+/\d+/\d{4}\s*\d*$', line.strip()):
                    continue
                clean_lines.append(line)
            
            clean_text = "\n".join(clean_lines).strip()
            
            # On crée un chunk par page, car ces documents mélangent frises, listes et tableaux
            # Le format texte à plat est ici parfaitement lisible par le LLM
            chunks.append(Chunk(
                text=f"Document de répartition et structures de la faculté (Page {page_num+1}) :\n{clean_text}",
                metadata=ChunkMetadata(
                    document_name=clean_title,
                    family_type="J",
                    page=page_num + 1
                )
            ))
            
        doc.close()
        return chunks