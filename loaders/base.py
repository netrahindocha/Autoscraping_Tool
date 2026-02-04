"""Base document loader class"""

from abc import ABC, abstractmethod
from pathlib import Path


class DocumentLoader(ABC):
    """Abstract base class for document loaders.

    All loaders must normalize their input to PDF format.
    """

    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        if not self.file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

    @abstractmethod
    def to_pdf(self, output_path: str) -> str:
        """Convert the document to PDF format.

        Args:
            output_path: Path where the PDF should be saved

        Returns:
            Path to the generated PDF file
        """
        pass

    @property
    def is_pdf(self) -> bool:
        """Check if the source is already a PDF"""
        return self.file_path.suffix.lower() == '.pdf'

    def get_pdf_path(self, output_dir: str) -> str:
        """Get the PDF path, converting if necessary.

        If the source is already PDF, returns the original path.
        Otherwise, converts to PDF and returns the new path.
        """
        if self.is_pdf:
            return str(self.file_path)

        output_path = Path(output_dir) / f"{self.file_path.stem}.pdf"
        return self.to_pdf(str(output_path))
