"""JSON-LD, OpenGraph, microdata extractor."""
class StructuredDataExtractor:
    async def extract(self, html, url):
        try:
            import extruct
            return extruct.extract(html, base_url=url, syntaxes=["json-ld","opengraph","microdata"])
        except: return {}
