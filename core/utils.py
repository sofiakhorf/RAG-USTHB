import os
import re
import subprocess
import pymupdf  # Remplacement de fitz
from typing import Tuple, Dict, Optional

from core.models import PipelineConfig


class SystemUtils:
    @staticmethod
    def convert_doc_to_docx(file_path: str, config: PipelineConfig) -> str:
        if not file_path.lower().endswith('.doc'):
            return file_path
        
        outdir = os.path.dirname(file_path) or "."
        cmd = [config.libreoffice_path, "--headless", "--convert-to", "docx", file_path, "--outdir", outdir]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return file_path + "x"

    @staticmethod
    def check_pdf_fonts_and_info(file_path: str) -> Tuple[bool, str]:
        has_text = False
        creator_info = ""
        try:
            res_fonts = subprocess.run(["pdffonts", file_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
            has_text = len(res_fonts.stdout.strip().split("\n")) > 2
        except FileNotFoundError:
            # Remplacement de fitz.open par pymupdf.open
            with pymupdf.open(file_path) as d:
                has_text = any(len(page.get_fonts()) > 0 for page in d)

        try:
            res_info = subprocess.run(["pdfinfo", file_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
            for line in res_info.stdout.split("\n"):
                if line.lower().startswith("creator:"):
                    creator_info = line.split(":", 1)[1].strip()
        except FileNotFoundError:
            # Remplacement de fitz.open par pymupdf.open
            with pymupdf.open(file_path) as d:
                creator_info = d.metadata.get("creator", "")

        return has_text, creator_info

    @staticmethod
    def is_arabic_page(text: str, threshold: float = 0.5) -> bool:
        """
        Renvoie True SEULEMENT si plus de 50% des caractères de la page sont en arabe.
        """
        clean_text = re.sub(r'\s+', '', text)
        if not clean_text:
            return False
        
        # Compter les caractères appartenant au bloc Unicode Arabe
        arabic_chars = len(re.findall(r'[\u0600-\u06FF]', clean_text))
        
        # Calculer le ratio
        ratio = arabic_chars / len(clean_text)
        
        return ratio > threshold


class AcademicMetadataExtractor:
    @staticmethod
    def extract_from_text(text: str) -> Dict[str, Optional[str]]:
        meta = {
            "annee_universitaire": None,
            "niveau": None,
            "formation": None,
            "ue": None,
            "matiere": None
        }
        ay_match = re.search(r"(20\d{2}[-/_]20\d{2}|\b20\d{2}\b)", text)
        if ay_match:
            meta["annee_universitaire"] = ay_match.group(0)
            
        niv_match = re.search(r"\b(L[1-3]|M[1-2]|ING[1-5]|LICENCE\s*[1-3]|MASTER\s*[1-2])\b", text, re.IGNORECASE)
        if niv_match:
            meta["niveau"] = niv_match.group(0).upper()
            
        spec_match = re.search(r"\b(ISIL|BIGDATA|SSI|IL|IA|GTR|RSD|ACAD|BIOINFO)\b", text, re.IGNORECASE)
        if spec_match:
            meta["formation"] = spec_match.group(0).upper()
            
        return meta