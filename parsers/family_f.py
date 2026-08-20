import pymupdf
import os
import re
from typing import List, Optional
from PIL import Image
import pytesseract
import logging

from core import Chunk, ChunkMetadata, BaseFamilyParser, ParserRegistry
from core.utils import SystemUtils, AcademicMetadataExtractor
from parsers.fallback import FallbackParser

logger = logging.getLogger("RAG_USTHB_OCR")

@ParserRegistry.register("F")
class FamilyFParser(BaseFamilyParser):
    def parse(
        self, 
        file_path: str, 
        document_title: Optional[str] = None,
        effective_start_line: int = 0
    ) -> List[Chunk]:
        # --- AJOUT : Détermination du titre propre ---
        clean_title = document_title if document_title else os.path.basename(file_path)
        ocr_pages = []

        try:
            with pymupdf.open(file_path) as doc:
                for page in doc:
                    pix = page.get_pixmap(dpi=300)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    
                    # :Support multilingue (Français + Arabe)
                   
                    # L'ordre "ara+fra" ou "fra+ara" permet de lire les deux alphabets sur la même page.
                    tesseract_langs = "fra+ara" 
                    
                    text = pytesseract.image_to_string(img, lang=tesseract_langs, config="--psm 4")
                    ocr_pages.append(text)
        except Exception as e:
            logger.error(f"Échec de l'OCR sur {file_path} : {e}")
            # Assurez-vous que FallbackParser est bien importé/défini
            return FallbackParser.parse_safe(file_path, "F")

        full_text = "\n".join(ocr_pages)

        # --- AJOUT : Tronquer l'en-tête institutionnel post-OCR ---
        if effective_start_line > 0:
            lines = full_text.split('\n')
            if effective_start_line < len(lines):
                full_text = "\n".join(lines[effective_start_line:])

        # : Regex tolérante et bilingue pour les Articles
        # - Art\.? : Accepte "Art." et "Art " (corrige le bug de arrete71403nov2011)
        # - المادة : Détecte "Al-Madda" en arabe 
        # - الأولى : Gère le cas spécifique du premier article en arabe ("Madda Oula")
        article_pattern = r'(Art\.?\s*\d+er?|Article\s*\d+|المادة\s*(?:\d+|الأول[ىي]))'
        splits = re.split(article_pattern, full_text, flags=re.I)
        chunks = []
        
        # SAUVETAGE DU PRÉAMBULE
        preambule = splits[0].strip()
        preambule = re.sub(r'(?<!\n)\n(?!\n)', ' ', preambule)

        procedure_meta = "Texte Juridique / نص قانوني"
        
        # Regex large pour Décrets et Arrêtés (FR/AR)
        # Détecte: "Décret n° 01-293", "Arrêté n° 714", "قرار رقم 994"
        doc_match = re.search(r'((?:décret|arrêté|مرسوم|قرار).*?(?:n°|رقم)\s*\d+(?:-\d+)?)', preambule, re.I)
        if doc_match:
            procedure_meta = doc_match.group(1).strip().capitalize()

        if len(preambule) > 50:
            chunks.append(Chunk(
                text=f"Préambule / Objet du {procedure_meta} :\n{preambule}",
                metadata=ChunkMetadata(
                    document_name=clean_title, 
                    family_type="F",
                    procedure=procedure_meta
                )
            ))

        # PARCOURS DES ARTICLES
        for i in range(1, len(splits), 2):
            art_title = splits[i].strip()
            art_body = splits[i+1].strip() if i+1 < len(splits) else ""
            
            # Nettoyage des sauts de ligne "visuels"
            art_body = re.sub(r'(?<!\n)\n(?!\n)', ' ', art_body)

            #  Ajout de mots clés pour tableaux (Indemnité, DA, دينار)
            keywords_baremes = ["taux", "barème", "rétribution", "montant", "indemnité", " da ", "دينار"]
            if any(k in art_body.lower() for k in keywords_baremes):
                art_body = f"=== BARÈMES ET TAUX / معدلات وأجور ===\n{art_body}"

            if len(art_body) > 15:
                chunks.append(Chunk(
                    text=f"{procedure_meta} | {art_title} :\n{art_body}",
                    metadata=ChunkMetadata(
                        document_name=clean_title, 
                        family_type="F",
                        procedure=procedure_meta
                    )
                ))

        return chunks