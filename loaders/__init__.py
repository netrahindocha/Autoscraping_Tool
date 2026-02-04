from .base import DocumentLoader
from .pdf_loader import PDFLoader
from .docx_loader import DocxLoader
from .html_loader import HTMLLoader
from .txt_loader import TextLoader

def get_loader(file_path: str) -> DocumentLoader:
    ext = file_path.lower().split('.')[-1]

    loaders = {
        'pdf': PDFLoader,
        'docx': DocxLoader,
        'doc': DocxLoader,
        'html': HTMLLoader,
        'htm': HTMLLoader,
        'txt': TextLoader,
        'text': TextLoader,
    }

    loader_class = loaders.get(ext)
    if not loader_class:
        raise ValueError(f"Unsupported file format: .{ext}")

    return loader_class(file_path)

__all__ = ['DocumentLoader', 'PDFLoader', 'DocxLoader', 'HTMLLoader', 'TextLoader', 'get_loader']
