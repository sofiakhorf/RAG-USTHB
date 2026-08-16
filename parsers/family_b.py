# --- 1. Bibliothèques standards Python ---
import os
import re
from typing import List, Optional

# --- 2. Bibliothèques externes ---
import pymupdf # (pour l'extraction PDF avancée : texte, dict, tables, dessins)

from core import Chunk, ChunkMetadata, BaseFamilyParser, ParserRegistry
from core.utils import SystemUtils, AcademicMetadataExtractor
from parsers.fallback import FallbackParser

@ParserRegistry.register("B")
class FamilyBParser(BaseFamilyParser):
    def parse(self, file_path: str, document_title: Optional[str] = None) -> List[Chunk]:
        # Détermination du titre propre
        clean_title = document_title if document_title else os.path.basename(file_path)
        chunks = []
        doc = pymupdf.open(file_path)
        
        # 1. Contexte global du document
        formation = "ISIL" if "isil" in file_path.lower() else "BIGDATAA"
        niveau = "licence" if "isil" in file_path.lower() else "master"
        
        current_h1, current_h2, current_h3 = "", "", ""
        fiche_buffer = []

        for idx, page in enumerate(doc):
            text_simple = page.get_text()
            
            # Filtre pages en arabe
            if SystemUtils.is_arabic_page(text_simple):
                continue
            #eliminer text arabe restant    
            text_simple= re.sub(r'[\u0600-\u06FF]+', '', text_simple)
            
            # Filtre pages de signatures / tampons
            if len(text_simple.strip()) < 80 and len(page.get_images()) > 0:
                chunks.append(Chunk(
                    text=f"[{formation}] Page visée et approuvée par les autorités.",
                    metadata=ChunkMetadata(
                        document_name=clean_title,
                        family_type="B",
                        formation=formation,
                        page=idx + 1
                    )
                ))
                continue

            # 2. EXTRACTION ET TRAITEMENT DES TABLEAUX
            tabs = page.find_tables()
            table_bboxes = []
            
            if tabs:
                for tab in tabs:
                    table_bboxes.append(tab.bbox)  # Coordonnées (x0, y0, x1, y1) du tableau
                    for row in tab.extract():
                        # Nettoyage des cellules
                        cells = [re.sub(r'\s+', ' ', cell.strip()) for cell in row if cell and cell.strip()]
                        if cells:
                            fiche_buffer.append(" | ".join(cells))

            # 3. EXTRACTION DU TEXTE AVEC TRI SPATIAL (Gère les colonnes)
            blocks = page.get_text("dict")["blocks"]
            text_blocks = [b for b in blocks if "lines" in b]

            # Tri spatial : trier par position Y (haut en bas), puis X (gauche à droite)
            sorted_blocks = sorted(
                text_blocks, 
                key=lambda b: (round(b["bbox"][1], 1), round(b["bbox"][0], 1))
            )

            for block in sorted_blocks:
                bx0, by0, bx1, by1 = block["bbox"]

                # Éviter de ré-extraire le texte situé à l'intérieur d'un tableau
                is_inside_table = False
                for tx0, ty0, tx1, ty1 in table_bboxes:
                    if bx0 >= tx0 and by0 >= ty0 and bx1 <= tx1 and by1 <= ty1:
                        is_inside_table = True
                        break
                
                if is_inside_table:
                    continue  # Saute ce bloc car son contenu a déjà été extrait via find_tables()

                # Parcourir les lignes et spans hors-tableaux
                for line in block["lines"]:
                    for span in line["spans"]:
                        txt = span["text"].strip()
                        size = span["size"]
                        if not txt:
                            continue

                        # Update des niveaux de titres H1, H2, H3
                        if size > 15:
                            current_h1 = txt
                        elif size > 12.5 and re.match(r'^(Semestre|UE|Unité d\'enseignement|[I|V|X]+\s*-)', txt, re.I):
                            current_h2 = txt
                        elif re.match(r'^(Intitulé\s+de\s+la\s+|Intitulé\s+du\s+)?(Matière|Module)|\d+\s*-|Code\s*:', txt, re.I):
                            current_h3 = txt

                        # Déclencheur de fermeture du Chunk précédent
                        if re.search(r'(Intitulé\s+de\s+la\s+|Intitulé\s+du\s+)?(Matière|Module)\s*:', txt, re.I):
                            if fiche_buffer:
                                breadcrumb = f"{niveau.upper()} {formation} > {current_h1} > {current_h2} > {current_h3}\n"
                                chunks.append(Chunk(
                                    text=breadcrumb + "\n".join(fiche_buffer),
                                    metadata=ChunkMetadata(
                                        document_name=clean_title,
                                        family_type="B",
                                        formation=formation,
                                        ue=current_h2,
                                        matiere=current_h3
                                    )
                                ))
                                fiche_buffer = []

                        fiche_buffer.append(txt)

        # 4. Traitement du dernier buffer en fin de document
        if fiche_buffer:
            breadcrumb = f"{niveau.upper()} {formation} > {current_h1} > {current_h2}\n"
            chunks.append(Chunk(
                text=breadcrumb + "\n".join(fiche_buffer),
                metadata=ChunkMetadata(
                    document_name=clean_title,
                    family_type="B", 
                    formation=formation
                )
            ))

        doc.close()
        return chunks