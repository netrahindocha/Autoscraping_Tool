"""HTML document loader"""

import subprocess
from pathlib import Path
from .base import DocumentLoader


class HTMLLoader(DocumentLoader):
    """Loader for HTML documents."""

    def to_pdf(self, output_path: str) -> str:
        """Convert HTML to PDF using available converters."""
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        # Try weasyprint first
        if self._try_weasyprint(output_path):
            return str(output)

        # Try wkhtmltopdf
        if self._try_wkhtmltopdf(output_path):
            return str(output)

        # Pure Python fallback
        return self._convert_with_python(output_path)

    def _try_weasyprint(self, output_path: str) -> bool:
        try:
            from weasyprint import HTML
            HTML(filename=str(self.file_path)).write_pdf(output_path)
            return Path(output_path).exists()
        except ImportError:
            return False
        except Exception:
            return False

    def _try_wkhtmltopdf(self, output_path: str) -> bool:
        try:
            result = subprocess.run([
                'wkhtmltopdf', str(self.file_path), output_path
            ], capture_output=True, timeout=60)
            return Path(output_path).exists()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _convert_with_python(self, output_path: str) -> str:
        """Pure Python conversion using reportlab"""
        try:
            from bs4 import BeautifulSoup
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas
            from reportlab.lib.units import inch

            with open(self.file_path, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f.read(), 'html.parser')

            c = canvas.Canvas(output_path, pagesize=letter)
            width, height = letter
            y = height - inch

            for text in soup.stripped_strings:
                if y < inch:
                    c.showPage()
                    y = height - inch

                c.drawString(inch, y, text[:100])
                y -= 14

            c.save()
            return output_path
        except ImportError as e:
            raise RuntimeError("Install: pip install beautifulsoup4 reportlab") from e
