"""PDF text/table extraction."""
class PdfExtractor:
    async def extract(self, pdf_bytes):
        try:
            import pdfplumber, io
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                text = "\n".join(p.extract_text() or "" for p in pdf.pages)
                tables = [t for p in pdf.pages for t in p.extract_tables()]
                return {"text":text, "tables":tables, "pages":len(pdf.pages)}
        except Exception as e: return {"text":"", "tables":[], "error":str(e)}
