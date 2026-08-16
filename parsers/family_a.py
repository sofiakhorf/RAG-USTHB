

# --- 1. Bibliothèques standards Python ---
import os
import re
from typing import List, Optional

# --- 2. Bibliothèques externes ---
import pdfplumber                  # Pour l'extraction avancée des PDF (tableaux, layout, filtres)
from docx import Document          # Pour lire les fichiers .docx (python-docx)

from docx.text.paragraph import Paragraph 
from docx.table import Table


from core import Chunk, ChunkMetadata, BaseFamilyParser, ParserRegistry
from core.utils import SystemUtils, AcademicMetadataExtractor
from parsers.fallback import FallbackParser


@ParserRegistry.register("A")
class FamilyAParser(BaseFamilyParser):
    def parse(self, file_path: str, document_title: Optional[str] = None) -> List[Chunk]:
        ext = os.path.splitext(file_path)[1].lower()
        raw_lines = []
        
        # --- AJOUT : Utilisation prioritaire du titre propre ---
        clean_title = document_title if document_title else os.path.basename(file_path).rsplit(".", 1)[0].replace("_", " ")
        if ext == '.docx':
            doc = Document(file_path)
            # Parcourir les éléments du document dans leur ordre d'apparition réel
            for element in doc.element.body:
                # S'il s'agit d'un paragraphe (Texte normal)
                if element.tag.endswith('p'):
                
                    p = Paragraph(element, doc)
                    text = re.sub(r'[\u2610\u2611\u2612\u25a2\u25a1]|\*\s', '[ ] ', p.text.strip())
                    if text:
                        raw_lines.append(text)
                
                # S'il s'agit d'un tableau
                elif element.tag.endswith('tbl'):
                   
                    table = Table(element, doc)
                    for row in table.rows:
                        cells = [re.sub(r'\s+', ' ', cell.text.strip()) for cell in row.cells if cell.text.strip()]
                        if cells:
                            raw_lines.append(" | ".join(cells))
       
        else:
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    # 1. Trouver les objets tableaux sur la page
                    tables_objs = page.find_tables()
                    
                    # 2. S'il y a des tableaux, extraire leur contenu proprement
                    if tables_objs:
                        for table_obj in tables_objs:
                            table_data = table_obj.extract()
                            for row in table_data:
                                cells = [re.sub(r'\s+', ' ', cell.strip()) for cell in row if cell and cell.strip()]
                                if cells:
                                    raw_lines.append(" | ".join(cells))
                        
                        # 3. Créer une version de la page où les zones de tableaux sont exclues
                        # (évite de réextraire le texte des tableaux en double)
                        def not_in_table(obj):
                            # Vérifie si le caractère/mot se trouve à l'intérieur du bounding box d'un tableau
                            px0, py0, px1, py1 = obj["x0"], obj["top"], obj["x1"], obj["bottom"]
                            for t in tables_objs:
                                tx0, ty0, tx1, ty1 = t.bbox
                                if px0 >= tx0 and py0 >= ty0 and px1 <= tx1 and py1 <= ty1:
                                    return False
                            return True

                        # Filtrer la page pour ne garder que le texte HORS tableaux
                        clean_page = page.filter(not_in_table)
                        text_outside = clean_page.extract_text(layout=True) or ""
                    else:
                        # S'il n'y a pas de tableau, extraire tout le texte normalement
                        text_outside = page.extract_text(layout=True) or ""

                    # 4. Nettoyer et ajouter le texte hors tableau
                    if text_outside.strip():
                        text_outside = re.sub(r'[\uf06f\uf0fe\uf0a8\u25a1\u25a2]', '[ ] ', text_outside)
                        raw_lines.append(text_outside)
                        
        raw_text = "\n".join(raw_lines)
        labels = re.findall(r'([A-ZÀ-Ÿ][a-zA-ZÀ-ÿ\s\’\'-]+)\s*[:\.]', raw_text)
        clean_labels = list(dict.fromkeys([l.strip() for l in labels if len(l.strip()) > 2]))[:15]
        
        # Le header injecté au LLM utilise maintenant le bon titre
        header = f"Formulaire : {clean_title}.\nChamps requis : {', '.join(clean_labels) if clean_labels else 'Procédure'}.\n=========================\n"

        return [Chunk(
            text=header + raw_text,
            metadata=ChunkMetadata(
                document_name=clean_title,
                family_type="A",
                procedure=clean_title.lower()
            )
        )]