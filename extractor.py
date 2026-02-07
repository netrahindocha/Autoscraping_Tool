import io
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    from PIL import Image
except ImportError:
    Image = None

import pdfplumber


@dataclass
class ExtractedImage:
    # Represents an extracted image
    image_data: bytes
    format: str
    page_num: int
    x: float
    y: float
    width: float
    height: float
    saved_path: Optional[str] = None


@dataclass
class ExtractedHyperlink:
    # Represents an extracted hyperlink
    url: str
    text: str
    page_num: int
    is_internal: bool
    x: float
    y: float


class PDFExtractor:
    # Extracts images and hyperlinks from PDF documents

    def __init__(self, pdf_path: str, section_id: str, assets_dir: str):
      
        self.pdf_path = Path(pdf_path)
        self.section_id = section_id
        self.assets_dir = Path(assets_dir)
        self.images_dir = self.assets_dir / "images"
        self.images_dir.mkdir(parents=True, exist_ok=True)

    def extract_images(self) -> List[ExtractedImage]:
        # Extract all images from the PDF.
        if fitz:
            return self._extract_images_pymupdf()
        else:
            return self._extract_images_pdfplumber()

    def _extract_images_pymupdf(self) -> List[ExtractedImage]:
        images = []
        doc = fitz.open(str(self.pdf_path))

        image_count = 0
        for page_num in range(len(doc)):
            page = doc[page_num]
            image_list = page.get_images()

            for img_index, img in enumerate(image_list):
                xref = img[0]
                base_image = doc.extract_image(xref)

                if base_image:
                    image_data = base_image["image"]
                    image_ext = base_image.get("ext", "png")

                    # Get image position
                    img_rect = page.get_image_rects(xref)
                    if img_rect:
                        rect = img_rect[0]
                        x, y = rect.x0, rect.y0
                        width, height = rect.width, rect.height
                    else:
                        x, y, width, height = 0, 0, 0, 0

                    image_count += 1
                    filename = f"section_{self.section_id}_img_{str(image_count).zfill(3)}.{image_ext}"
                    save_path = self.images_dir / filename

                    with open(save_path, 'wb') as f:
                        f.write(image_data)

                    images.append(ExtractedImage(
                        image_data=image_data,
                        format=image_ext,
                        page_num=page_num,
                        x=x,
                        y=y,
                        width=width,
                        height=height,
                        saved_path=str(save_path)
                    ))

        doc.close()
        return images

    def _extract_images_pdfplumber(self) -> List[ExtractedImage]:
        # Extract images using pdfplumber (fallback).
        images = []

        with pdfplumber.open(self.pdf_path) as pdf:
            image_count = 0

            for page_num, page in enumerate(pdf.pages):
                page_images = page.images

                for img in page_images:
                    try:
                        # pdfplumber provides image coordinates
                        x = img.get('x0', 0)
                        y = img.get('top', 0)
                        width = img.get('width', 0)
                        height = img.get('height', 0)

                        # Try to extract image data
                        if 'stream' in img:
                            image_data = img['stream'].get_data()
                            image_count += 1

                            filename = f"section_{self.section_id}_img_{str(image_count).zfill(3)}.png"
                            save_path = self.images_dir / filename

                            # Try to process with PIL if available
                            if Image:
                                try:
                                    pil_image = Image.open(io.BytesIO(image_data))
                                    pil_image.save(save_path, 'PNG')
                                except Exception:
                                    with open(save_path, 'wb') as f:
                                        f.write(image_data)
                            else:
                                with open(save_path, 'wb') as f:
                                    f.write(image_data)

                            images.append(ExtractedImage(
                                image_data=image_data,
                                format='png',
                                page_num=page_num,
                                x=x,
                                y=y,
                                width=width,
                                height=height,
                                saved_path=str(save_path)
                            ))
                    except Exception:
                        continue

        return images

    def extract_hyperlinks(self) -> List[ExtractedHyperlink]:
        # Extract all hyperlinks from the PDF.
        if fitz:
            return self._extract_links_pymupdf()
        else:
            return self._extract_links_pdfplumber()

    def _extract_links_pymupdf(self) -> List[ExtractedHyperlink]:
        # Extract hyperlinks using PyMuPDF.
        links = []
        doc = fitz.open(str(self.pdf_path))

        for page_num in range(len(doc)):
            page = doc[page_num]

            for link in page.get_links():
                uri = link.get('uri', '')

                # Skip links with empty URIs
                if not uri:
                    continue

                rect = link.get('from', fitz.Rect(0, 0, 0, 0))

                # Get text at link location
                text = page.get_textbox(rect) if rect else ''
                text = text.strip() if text else uri

                # Check if internal link (starts with # or doesn't have a protocol)
                is_internal = uri.startswith('#') or (
                    not uri.startswith(('http://', 'https://', 'mailto:')) and
                    '://' not in uri and
                    not uri.startswith('www.')
                )

                links.append(ExtractedHyperlink(
                    url=uri,
                    text=text,
                    page_num=page_num,
                    is_internal=is_internal,
                    x=rect.x0 if rect else 0,
                    y=rect.y0 if rect else 0
                ))

        doc.close()
        return links

    def _extract_links_pdfplumber(self) -> List[ExtractedHyperlink]:
        # Extract hyperlinks using pdfplumber.
        links = []

        with pdfplumber.open(self.pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages):
                # pdfplumber stores hyperlinks in annots
                if hasattr(page, 'annots') and page.annots:
                    for annot in page.annots:
                        uri = annot.get('uri', '')

                        # Skip links with empty URIs
                        if not uri:
                            continue

                        # Check if internal link
                        is_internal = uri.startswith('#') or (
                            not uri.startswith(('http://', 'https://', 'mailto:')) and
                            '://' not in uri and
                            not uri.startswith('www.')
                        )

                        links.append(ExtractedHyperlink(
                            url=uri,
                            text=uri,  # pdfplumber doesn't easily give link text
                            page_num=page_num,
                            is_internal=is_internal,
                            x=annot.get('x0', 0),
                            y=annot.get('top', 0)
                        ))

        return links

    def get_image_references(self, images: List[ExtractedImage], markdown_dir: str) -> Dict[int, List[str]]:
        # Get markdown image references organized by page.
        references = {}
        markdown_path = Path(markdown_dir)

        for img in images:
            if img.saved_path:
                # Calculate relative path from markdown to image
                rel_path = Path(img.saved_path).relative_to(markdown_path.parent.parent)
                # Use forward slashes for markdown
                rel_path_str = str(rel_path).replace('\\', '/')

                ref = f"![Image]({rel_path_str})"

                if img.page_num not in references:
                    references[img.page_num] = []
                references[img.page_num].append(ref)

        return references
