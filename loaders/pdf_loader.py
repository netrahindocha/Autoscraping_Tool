import shutil
from pathlib import Path
from .base import DocumentLoader

class PDFLoader(DocumentLoader):

    def to_pdf(self, output_path: str) -> str:
 
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        if str(self.file_path) != str(output):
            shutil.copy2(self.file_path, output)

        return str(output)

    @property
    def is_pdf(self) -> bool:
        return True
