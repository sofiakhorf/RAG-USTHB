


import os
import re
import logging
from typing import List, Optional
import pytesseract
from PIL import Image

from core import Chunk, ChunkMetadata, BaseFamilyParser, ParserRegistry
from core.utils import SystemUtils, AcademicMetadataExtractor
from parsers.fallback import FallbackParser


logger = logging.getLogger("RAG_USTHB")

@ParserRegistry.register("I")
class FamilyIParser(BaseFamilyParser):
    """
    Famille I : Avis administratifs courts scannés (Images bilingues).
    Isole le corps de texte utile via un OCR zoné en français pour éviter le bruit de l'en-tête.
    """
    
    # Définition des zones de la page (en pourcentage de la hauteur)
    ZONES = {
        "entete": (0.00, 0.14),
        "meta": (0.14, 0.24),
        "corps": (0.23, 0.90),   # Léger recouvrement volontaire avec "meta" pour ne rien couper
        "signature": (0.90, 1.00),
    }

    ENTETE_FIXE = (
        "En-tête institutionnel USTHB bilingue (République Algérienne Démocratique et Populaire / "
        "Ministère de l'Enseignement Supérieur et de la Recherche Scientifique / USTHB / "
        "Faculté d'Informatique) — gabarit fixe, non ré-océrisé."
    )

    # Regex pour l'extraction des métadonnées
    TYPE_RE = re.compile(r"Avis\s+(Annulation|Consultation)\s*N[°ʹ']?\s*([A-Za-z0-9]+)", re.IGNORECASE)
    REF_RE = re.compile(r"N[/']?Réf\s*[:\.]?\s*([\w /\.]+)")
    DATE_RE = re.compile(r"(\d{1,2}[/\.]\d{1,2}[/\.]\d{2,4})")
    LOT_RE = re.compile(r"LOT\s*N[°ʹ']?\s*\d+.*", re.IGNORECASE)

    def parse(self, file_path: str, document_title: Optional[str] = None) -> List[Chunk]:
        # --- AJOUT : Détermination du titre propre ---
        clean_title = document_title if document_title else os.path.basename(file_path)
        chunks = []
        try:
            img = Image.open(file_path)
            
            # 1. OCR ciblé sur la zone méta (référence, date, titre)
            meta_text = pytesseract.image_to_string(
                self._crop_image(img, *self.ZONES["meta"]), 
                lang=self.config.tesseract_lang_fra
            )
            
            # 2. OCR ciblé sur la zone corps (texte utile, listes)
            corps_text = pytesseract.image_to_string(
                self._crop_image(img, *self.ZONES["corps"]), 
                lang=self.config.tesseract_lang_fra
            )

            # 3. Extraction des métadonnées via Regex
            type_match = self.TYPE_RE.search(meta_text) or self.TYPE_RE.search(corps_text)
            sous_type = type_match.group(1).lower() if type_match else "inconnu"
            numero = type_match.group(2) if type_match else None
            
            ref_match = self.REF_RE.search(meta_text)
            date_match = self.DATE_RE.search(meta_text) or self.DATE_RE.search(corps_text)

            # 4. Extraction structurelle du corps (Lots et Checklist)
            lots = self.LOT_RE.findall(corps_text)
            checklist = [l.strip("* ").strip() for l in corps_text.splitlines() if l.strip().startswith("*")]

            # 5. Construction du texte du Chunk
            lines = [
                self.ENTETE_FIXE,
                f"[Avis {sous_type.capitalize()} N°{numero or '?'} — "
                f"réf. {ref_match.group(1).strip() if ref_match else '?'} — "
                f"{date_match.group(1) if date_match else '?'}]",
                "",
                corps_text.strip(),
            ]
            
            if lots:
                lines.append("\nLots :")
                lines += [f"- {l}" for l in lots]
                
            if checklist:
                lines.append("\nPièces exigées :")
                lines += [f"- {c}" for c in checklist]
                
            lines.append(
                "\n[Document signé et tamponné par la Doyenne de la Faculté d'Informatique — "
                "signature/tampon non transcrits par OCR.]"
            )
            
            chunk_text = "\n".join(lines)

            chunks.append(Chunk(
                text=chunk_text,
                metadata=ChunkMetadata(
                    document_name=clean_title,
                    family_type="I",
                    procedure=sous_type,  # Ex: "annulation" ou "consultation"
                    date_version=date_match.group(1) if date_match else None
                )
            ))

        except Exception as e:
            logger.error(f"Erreur d'extraction sémantique I (OCR) sur {file_path}: {e}")

        # Bascule sur le parseur de secours si l'OCR n'a rien retourné ou a planté
        return chunks if chunks else FallbackParser.parse_safe(file_path, "I")

    @staticmethod
    def _crop_image(img: Image.Image, frac_top: float, frac_bottom: float) -> Image.Image:
        """Recadre l'image selon les fractions de hauteur spécifiées."""
        w, h = img.size
        return img.crop((0, int(h * frac_top), w, int(h * frac_bottom)))