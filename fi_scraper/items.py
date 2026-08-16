import scrapy

class FiDocumentItem(scrapy.Item):
    doc_id = scrapy.Field()
    url_source = scrapy.Field()
    title = scrapy.Field()
    raw_text = scrapy.Field()
    type_document = scrapy.Field()  # 'html', 'pdf', 'docx', 'xlsx', 'image'
    file_path = scrapy.Field()
    date_scraping = scrapy.Field()


