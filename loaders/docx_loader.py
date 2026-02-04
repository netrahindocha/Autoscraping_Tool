import subprocess
import sys
from pathlib import Path
from .base import DocumentLoader


class DocxLoader(DocumentLoader):

    def to_pdf(self, output_path: str) -> str:
        # Convert Word document to PDF.

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        # Try docx2pdf first (requires MS Word on Windows)
        if self._try_docx2pdf(output_path):
            return str(output)

        # Try LibreOffice
        if self._try_libreoffice(output_path):
            return str(output)

        # Pure Python fallback using python-docx and reportlab
        return self._convert_with_python(output_path)

    def _try_docx2pdf(self, output_path: str) -> bool:
        # Try converting using docx2pdf (Windows + MS Word)
        try:
            from docx2pdf import convert
            convert(str(self.file_path), output_path)
            return Path(output_path).exists()
        except ImportError:
            return False
        except Exception:
            return False

    def _try_libreoffice(self, output_path: str) -> bool:
        # Try converting using LibreOffice
        output = Path(output_path)

        # Common LibreOffice paths
        lo_paths = [
            'soffice',
            'libreoffice',
            '/usr/bin/libreoffice',
            '/usr/bin/soffice',
            'C:/Program Files/LibreOffice/program/soffice.exe',
            'C:/Program Files (x86)/LibreOffice/program/soffice.exe',
        ]

        for lo_path in lo_paths:
            try:
                result = subprocess.run([
                    lo_path,
                    '--headless',
                    '--convert-to', 'pdf',
                    '--outdir', str(output.parent),
                    str(self.file_path)
                ], capture_output=True, timeout=60)

                # LibreOffice outputs with original name + .pdf
                expected = output.parent / f"{self.file_path.stem}.pdf"
                if expected.exists():
                    if str(expected) != output_path:
                        expected.rename(output_path)
                    return True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue

        return False

    def _convert_with_python(self, output_path: str) -> str:
        # Pure Python conversion using python-docx and reportlab
        try:
            from docx import Document
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas
            from reportlab.lib.units import inch

            doc = Document(str(self.file_path))
            c = canvas.Canvas(output_path, pagesize=letter)
            width, height = letter

            y = height - inch
            line_height = 14

            for para in doc.paragraphs:
                text = para.text
                if not text:
                    y -= line_height
                    continue

                # Handle basic styling
                font_size = 12
                if para.style and para.style.name:
                    if 'Heading 1' in para.style.name:
                        font_size = 18
                    elif 'Heading 2' in para.style.name:
                        font_size = 16
                    elif 'Heading' in para.style.name:
                        font_size = 14

                c.setFont("Helvetica", font_size)

                # Word wrap
                words = text.split()
                current_line = ""
                for word in words:
                    test_line = f"{current_line} {word}".strip()
                    if c.stringWidth(test_line, "Helvetica", font_size) < width - 2*inch:
                        current_line = test_line
                    else:
                        if current_line:
                            c.drawString(inch, y, current_line)
                            y -= line_height
                        current_line = word

                    if y < inch:
                        c.showPage()
                        y = height - inch
                        c.setFont("Helvetica", font_size)

                if current_line:
                    c.drawString(inch, y, current_line)
                    y -= line_height * 1.5

            c.save()
            return output_path

        except ImportError as e:
            raise RuntimeError(
                "Cannot convert DOCX to PDF. Install required packages:\n"
                "  pip install python-docx reportlab\n"
                "Or install docx2pdf (Windows with MS Word):\n"
                "  pip install docx2pdf\n"
                "Or install LibreOffice for cross-platform support."
            ) from e
