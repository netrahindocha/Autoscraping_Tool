import argparse
import sys
from pathlib import Path
from typing import Dict, List, Tuple

from .loaders import get_loader
from .heading_detector import HeadingDetector
from .splitter import PDFSplitter, sanitize_filename
from .extractor import PDFExtractor, ExtractedHyperlink
from .converter import MarkdownConverter


class Autoscraper:

    def __init__(
        self,
        input_path: str,
        output_dir: str = "output",
        verbose: bool = True
    ):
        self.input_path = Path(input_path)
        self.output_dir = Path(output_dir)
        self.verbose = verbose

        # Create output directories
        self.pdf_dir = self.output_dir / "pdf"
        self.markdown_dir = self.output_dir / "markdown"
        self.assets_dir = self.output_dir / "assets"
        self.images_dir = self.assets_dir / "images"

        for d in [self.pdf_dir, self.markdown_dir, self.assets_dir, self.images_dir]:
            d.mkdir(parents=True, exist_ok=True)

        self._log(f"Input: {self.input_path}")
        self._log(f"Output: {self.output_dir}")

    def _log(self, message: str):
        # Print log message if verbose mode is on.
        if self.verbose:
            print(message)

    def process(self) -> Dict[str, List[str]]:
        # Process the document through the entire pipeline.
        results = {'pdf': [], 'markdown': []}

        # Step 1: Load and convert to PDF
        self._log("\n=== Step 1: Loading document ===")
        loader = get_loader(str(self.input_path))
        pdf_path = loader.get_pdf_path(str(self.output_dir / "temp"))
        self._log(f"PDF path: {pdf_path}")

        # Step 2: Detect headings and get section boundaries
        self._log("\n=== Step 2: Detecting headings ===")
        with HeadingDetector(pdf_path) as detector:
            boundaries = detector.get_section_boundaries()
            header_footer_entries = detector.header_footer_entries
            sub_titles = detector.sub_titles

            self._log(f"Found {len(boundaries)} sections:")
            for title, start, end in boundaries:
                self._log(f"  - {title} (pages {start+1}-{end+1})")

            if header_footer_entries:
                self._log(f"Auto-detected {len(header_footer_entries)} header/footer patterns")

        # Step 2.5: Extract hyperlinks from original PDF (before splitting)
        # Hyperlink annotations are often lost when PDFs are split
        self._log("\n=== Step 2.5: Extracting hyperlinks from original PDF ===")
        original_extractor = PDFExtractor(pdf_path, "00", str(self.assets_dir))
        all_hyperlinks = original_extractor.extract_hyperlinks()
        self._log(f"Found {len(all_hyperlinks)} hyperlinks in original PDF")

        # Step 3: Split PDF into sections
        self._log("\n=== Step 3: Splitting PDF ===")
        splitter = PDFSplitter(pdf_path, str(self.pdf_dir))
        split_results = splitter.split(boundaries)

        for title, path in split_results:
            self._log(f"  Created: {path}")
            results['pdf'].append(path)

        # Build section title -> markdown filename mapping for internal links
        section_mapping = {}
        for idx, (title, _) in enumerate(split_results):
            section_id = str(idx + 1).zfill(2)
            safe_name = sanitize_filename(title)
            md_filename = f"Section_{section_id}_{safe_name}.md"
            section_mapping[title] = md_filename

        # Step 4: Process each split PDF
        self._log("\n=== Step 4: Extracting assets and converting to Markdown ===")

        for idx, (title, split_pdf_path) in enumerate(split_results):
            section_id = str(idx + 1).zfill(2)
            start_page, end_page = boundaries[idx][1], boundaries[idx][2]
            self._log(f"\nProcessing section {section_id}: {title}")

            # Extract images from split PDF
            extractor = PDFExtractor(split_pdf_path, section_id, str(self.assets_dir))
            images = extractor.extract_images()
            self._log(f"  Extracted {len(images)} images")

            # Filter hyperlinks from original PDF for this section's page range
            # and adjust page numbers to be relative to the split PDF
            section_hyperlinks = [
                ExtractedHyperlink(
                    url=link.url,
                    text=link.text,
                    page_num=link.page_num - start_page,
                    is_internal=link.is_internal,
                    x=link.x,
                    y=link.y
                )
                for link in all_hyperlinks
                if start_page <= link.page_num <= end_page
            ]
            self._log(f"  Mapped {len(section_hyperlinks)} hyperlinks")

            # Get next section title for boundary detection
            next_section_title = None
            if idx + 1 < len(split_results):
                next_section_title = split_results[idx + 1][0]

            # Convert to Markdown
            converter = MarkdownConverter(
                pdf_path=split_pdf_path,
                section_title=title,
                section_id=section_id,
                images=images,
                hyperlinks=section_hyperlinks,
                header_footer_entries=header_footer_entries,
                all_sections=section_mapping,
                sub_titles=sub_titles,
                next_section_title=next_section_title
            )

            markdown_content, has_meaningful_content = converter.convert()

            # Skip sections with no meaningful content (only heading, no text/images/hyperlinks)
            if not has_meaningful_content and not images and not section_hyperlinks:
                self._log(f"  Skipping empty section (no content)")
                # Remove the split PDF since section is empty
                Path(split_pdf_path).unlink(missing_ok=True)
                results['pdf'].remove(split_pdf_path)
                continue

            # Save Markdown file
            # Generate filename directly using index (not from mapping which may have duplicates)
            safe_name = sanitize_filename(title)
            md_filename = f"Section_{section_id}_{safe_name}.md"
            md_path = self.markdown_dir / md_filename

            md_path.write_text(markdown_content, encoding='utf-8')
            self._log(f"  Created: {md_path}")
            results['markdown'].append(str(md_path))

        # Summary
        self._log("\n=== Processing Complete ===")
        self._log(f"Split PDFs: {len(results['pdf'])}")
        self._log(f"Markdown files: {len(results['markdown'])}")
        self._log(f"Output directory: {self.output_dir}")

        return results


def main():
    # CLI entry point.
    parser = argparse.ArgumentParser(
        description="Autoscraper - Convert documents to split PDFs and Markdown"
    )
    parser.add_argument(
        "input",
        help="Input document path (PDF, DOCX, HTML, TXT)"
    )
    parser.add_argument(
        "-o", "--output",
        default="output",
        help="Output directory (default: output)"
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress output messages"
    )

    args = parser.parse_args()

    try:
        scraper = Autoscraper(
            input_path=args.input,
            output_dir=args.output,
            verbose=not args.quiet
        )
        results = scraper.process()

        if not args.quiet:
            print("\nGenerated files:")
            print("\nPDFs:")
            for p in results['pdf']:
                print(f"  {p}")
            print("\nMarkdown:")
            for p in results['markdown']:
                print(f"  {p}")

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
