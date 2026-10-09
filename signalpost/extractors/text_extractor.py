"""Clean text extraction."""
class TextExtractor:
    async def extract(self, html, url=""):
        try:
            import trafilatura
            return trafilatura.extract(html, url=url, include_links=True, include_tables=True)
        except: return None
