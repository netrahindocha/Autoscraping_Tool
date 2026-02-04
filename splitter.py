import re
from pathlib import Path
from typing import List, Tuple

try:
    import pikepdf
except ImportError:
    pikepdf = None

try:
    from PyPDF2 import PdfReader, PdfWriter
except ImportError:
    PdfReader = None
    PdfWriter = None


def sanitize_filename(name: str) -> str:
    # Remove or replace invalid characters
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'\s+', '_', name.strip())
    name = re.sub(r'_+', '_', name)
    name = name.strip('_')

    # Limit length
    if len(name) > 50:
        name = name[:50].rstrip('_')

    return name or "Section"


class PDFSplitter:
    # Splits PDF documents into sections.

    def __init__(self, pdf_path: str, output_dir: str):
        self.pdf_path = Path(pdf_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def split(self, boundaries: List[Tuple[str, int, int]]) -> List[Tuple[str, str]]:
        # Split PDF based on section boundaries.

        if pikepdf:
            return self._split_with_pikepdf(boundaries)
        elif PdfReader and PdfWriter:
            return self._split_with_pypdf2(boundaries)
        else:
            raise RuntimeError(
                "No PDF library available. Install pikepdf (recommended):\n"
                "  pip install pikepdf\n"
                "Or PyPDF2:\n"
                "  pip install PyPDF2"
            )

    def _split_with_pikepdf(self, boundaries: List[Tuple[str, int, int]]) -> List[Tuple[str, str]]:
        # Split using pikepdf (preferred method).
        results = []

        with pikepdf.open(self.pdf_path) as pdf:
            total_pages = len(pdf.pages)

            for idx, (title, start_page, end_page) in enumerate(boundaries):
                # Validate page range
                start_page = max(0, min(start_page, total_pages - 1))
                end_page = max(start_page, min(end_page, total_pages - 1))

                # Create output PDF
                output_pdf = pikepdf.Pdf.new()
                for page_num in range(start_page, end_page + 1):
                    output_pdf.pages.append(pdf.pages[page_num])

                # Generate filename
                section_num = str(idx + 1).zfill(2)
                safe_name = sanitize_filename(title)
                filename = f"Section_{section_num}_{safe_name}.pdf"
                output_path = self.output_dir / filename

                output_pdf.save(output_path)
                results.append((title, str(output_path)))

        return results

    def _split_with_pypdf2(self, boundaries: List[Tuple[str, int, int]]) -> List[Tuple[str, str]]:
        # Split using PyPDF2 (fallback method).
        results = []

        reader = PdfReader(str(self.pdf_path))
        total_pages = len(reader.pages)

        for idx, (title, start_page, end_page) in enumerate(boundaries):
            # Validate page range
            start_page = max(0, min(start_page, total_pages - 1))
            end_page = max(start_page, min(end_page, total_pages - 1))

            # Create output PDF
            writer = PdfWriter()
            for page_num in range(start_page, end_page + 1):
                writer.add_page(reader.pages[page_num])

            # Generate filename
            section_num = str(idx + 1).zfill(2)
            safe_name = sanitize_filename(title)
            filename = f"Section_{section_num}_{safe_name}.pdf"
            output_path = self.output_dir / filename

            with open(output_path, 'wb') as f:
                writer.write(f)

            results.append((title, str(output_path)))

        return results
