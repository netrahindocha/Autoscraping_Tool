from pathlib import Path
from .base import DocumentLoader

class TextLoader(DocumentLoader):
    # Loader for plain text files.

    def to_pdf(self, output_path: str) -> str:
        # Convert text to PDF using reportlab.
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas
            from reportlab.lib.units import inch

            with open(self.file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            c = canvas.Canvas(output_path, pagesize=letter)
            width, height = letter
            y = height - inch

            for line in content.split('\n'):
                if y < inch:
                    c.showPage()
                    y = height - inch
                    c.setFont("Courier", 10)

                c.setFont("Courier", 10)
                c.drawString(inch, y, line[:100])
                y -= 12

            c.save()
            return output_path
        except ImportError as e:
            raise RuntimeError("Install: pip install reportlab") from e
