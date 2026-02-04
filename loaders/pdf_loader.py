"""PDF document loader"""

import shutil
from pathlib import Path
from .base import DocumentLoader


class PDFLoader(DocumentLoader):
    """Loader for PDF documents.

    PDFs are the primary format, so this loader simply
    validates and optionally copies the file.
    """

    def to_pdf(self, output_path: str) -> str:
        """Copy PDF to output location.

        For PDF files, we just copy to the output location
        to maintain a consistent pipeline.
        """
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        if str(self.file_path) != str(output):
            shutil.copy2(self.file_path, output)

        return str(output)

    @property
    def is_pdf(self) -> bool:
        return True
