import os
import re
import hashlib
import requests
from datetime import datetime
from scrapy.spiders import CrawlSpider, Rule
from scrapy.linkextractors import LinkExtractor
from selectolax.parser import HTMLParser
from fi_scraper.items import FiDocumentItem

class FiSpider(CrawlSpider):
    name = "fi_spider"
    allowed_domains = ["finfo.usthb.dz"]
    start_urls = ["https://finfo.usthb.dz/"]

    os.makedirs("downloads", exist_ok=True)

    rules = (
        Rule(
            LinkExtractor(
                allow_domains=["finfo.usthb.dz"],
                deny=[r'.*/login.*', r'.*/cas/.*', r'.*\?mode=.*'],
                deny_extensions=[]
            ),
            callback="parse_item",
            follow=True
        ),
    )

    def parse_item(self, response):
        url = response.url
        clean_url = url.split('?')[0].lower()
        content_type = response.headers.get("Content-Type", b"").decode("utf-8").lower()

        # --- CAS 1 : Fichiers joints classiques (PDF, DOCX, XLSX, Images) ---
        target_extensions = ['.pdf', '.docx', '.xlsx', '.png', '.jpg', '.jpeg']
        is_document = any(clean_url.endswith(ext) for ext in target_extensions) or \
                      any(ft in content_type for ft in ['pdf', 'word', 'spreadsheet', 'excel'])

        if is_document:
            ext = clean_url.split('.')[-1] if '.' in clean_url else 'bin'
            if ext not in ['pdf', 'docx', 'xlsx', 'png', 'jpg', 'jpeg']:
                if 'pdf' in content_type: ext = 'pdf'
                elif 'word' in content_type: ext = 'docx'
                elif 'excel' in content_type or 'spreadsheet' in content_type: ext = 'xlsx'

            doc_type = 'pdf' if ext == 'pdf' else ('docx' if ext == 'docx' else ('xlsx' if ext == 'xlsx' else 'image'))
            
            filename = hashlib.md5(url.encode()).hexdigest() + f".{ext}"
            filepath = os.path.join("downloads", filename)
            
            with open(filepath, "wb") as f:
                f.write(response.body)

            item = FiDocumentItem()
            item["doc_id"] = hashlib.sha256(url.encode()).hexdigest()
            item["url_source"] = url
            item["title"] = os.path.basename(clean_url)
            item["raw_text"] = ""
            item["type_document"] = doc_type
            item["file_path"] = filepath
            item["date_scraping"] = datetime.now().strftime("%Y-%m-%d")
            yield item

        # --- CAS 2 : Pages HTML (Détection des pages ET des Google Sheets intégrés) ---
        elif "text/html" in content_type:
            parser = HTMLParser(response.body)

            # 1. Traitement spécifique des liens Google Sheets trouvés sur la page
            for a_tag in parser.css("a[href*='docs.google.com/spreadsheets']"):
                gs_url = a_tag.attributes.get("href", "")
                match = re.search(r"/d/([a-zA-Z0-9-_]+)", gs_url)
                if match:
                    sheet_id = match.group(1)
                    export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
                    
                    try:
                        # Téléchargement direct du fichier généré par Google
                        res = requests.get(export_url, timeout=10)
                        if res.status_code == 200:
                            filename = f"gsheet_{sheet_id}.xlsx"
                            filepath = os.path.join("downloads", filename)
                            with open(filepath, "wb") as f:
                                f.write(res.content)
                            
                            gs_item = FiDocumentItem()
                            gs_item["doc_id"] = hashlib.sha256(gs_url.encode()).hexdigest()
                            gs_item["url_source"] = gs_url
                            gs_item["title"] = a_tag.text(strip=True) or f"Google Sheet {sheet_id}"
                            gs_item["raw_text"] = ""
                            gs_item["type_document"] = "xlsx"  # Traité comme un Excel normal ensuite
                            gs_item["file_path"] = filepath
                            gs_item["date_scraping"] = datetime.now().strftime("%Y-%m-%d")
                            yield gs_item
                    except Exception as e:
                        print(f"Erreur lors de la récupération du Google Sheet {gs_url}: {e}")

            # 2. Nettoyage du bruit HTML habituel
            for tag in parser.css("header, footer, nav, aside, script, style, .sidebar, .menu"):
                tag.decompose()

            body = parser.body
            if not body:
                return

            raw_text = body.text(separator=" ", strip=True)
            if len(raw_text) < 100:
                return

            title_node = parser.css_first("title")

            item = FiDocumentItem()
            item["doc_id"] = hashlib.sha256(url.encode()).hexdigest()
            item["url_source"] = url
            item["title"] = title_node.text(strip=True) if title_node else "Page Web FI"
            item["raw_text"] = raw_text
            item["type_document"] = "html"
            item["file_path"] = ""
            item["date_scraping"] = datetime.now().strftime("%Y-%m-%d")
            yield item