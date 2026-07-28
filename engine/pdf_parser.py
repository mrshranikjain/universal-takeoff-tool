"""PDF Parser - handles multi-page PDF opening and page selection"""
import fitz
import os


class PDFParser:
    def __init__(self, pdf_path):
        self.path = pdf_path
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        self.doc = fitz.open(pdf_path)
        self.page_count = len(self.doc)
    
    def get_pages(self, page_spec="1"):
        """Return list of (page_num, page_obj) based on spec.
        
        Args:
            page_spec: "1", "all", "1,3,5", "1-5"
        Returns:
            list of (page_number, fitz.Page) tuples
        """
        if page_spec == "all":
            return [(i + 1, self.doc[i]) for i in range(self.page_count)]
        
        pages = []
        for part in page_spec.split(","):
            part = part.strip()
            if "-" in part:
                start, end = part.split("-")
                for p in range(int(start), int(end) + 1):
                    if 1 <= p <= self.page_count:
                        pages.append((p, self.doc[p - 1]))
            else:
                p = int(part)
                if 1 <= p <= self.page_count:
                    pages.append((p, self.doc[p - 1]))
        return pages
    
    def get_page_count(self):
        return self.page_count
    
    def close(self):
        self.doc.close()