import re
from dataclasses import dataclass
from typing import List, Optional, Set, Tuple
import pdfplumber


@dataclass
class HeadingEntry:
    # Represents a detected heading in the document
    title: str
    level: int  # 1 for H1/main, 2 for H2/sub, etc.
    page_num: int  # 0-indexed page number
    y_position: float  # y-coordinate on the page


@dataclass
class TOCEntry:
    # Represents a Table of Contents entry
    title: str
    level: int
    page_num: Optional[int]  # Target page if available


class HeadingDetector:
    # Detects TOC and headings in PDF documents

    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self._pdf = None
        self._toc_pages: Set[int] = set()
        self._header_footer_entries: Set[Tuple[int, str]] = set()
        self._sub_titles: Set[str] = set()

    def __enter__(self):
        self._pdf = pdfplumber.open(self.pdf_path)
        return self

    def __exit__(self, *args):
        if self._pdf:
            self._pdf.close()

    def detect_toc(self) -> Tuple[List[TOCEntry], Set[int]]:
        # Detect Table of Contents entries.
        entries = []
        toc_pages = set()
        min_indent = 999

        # Check first 3 pages for TOC
        for page_num in range(min(3, len(self._pdf.pages))):
            page = self._pdf.pages[page_num]
            text = page.extract_text(layout=True)
            if not text:
                continue

            for line in text.splitlines():
                stripped = line.strip()
                # TOC lines typically have dots leading to page number
                if "..." in stripped or re.search(r'\.{3,}', stripped):
                    title = re.split(r'\.{2,}', stripped)[0].strip()
                    if title and len(title) > 2:
                        indent = len(line) - len(line.lstrip())
                        min_indent = min(min_indent, indent)

                        # Try to extract page number
                        page_match = re.search(r'(\d+)\s*$', stripped)
                        target_page = int(page_match.group(1)) - 1 if page_match else None

                        entries.append({
                            'title': title,
                            'indent': indent,
                            'target_page': target_page
                        })
                        toc_pages.add(page_num)

        # Classify by indent level
        toc_entries = []
        for entry in entries:
            level = 1 if entry['indent'] <= min_indent else 2
            toc_entries.append(TOCEntry(
                title=entry['title'],
                level=level,
                page_num=entry['target_page']
            ))

        self._toc_pages = toc_pages
        return toc_entries, toc_pages

    def detect_headers_footers(self) -> Set[Tuple[int, str]]:
        # Auto-detect repeating headers/footers by y-position.
        sample_pages = self._pdf.pages[1:min(10, len(self._pdf.pages))]
        if len(sample_pages) < 2:
            return set()

        line_occurrences = {}

        for page in sample_pages:
            chars = page.chars
            if not chars:
                continue

            lines_by_top = {}
            for c in chars:
                top_key = round(c['top'])
                if top_key not in lines_by_top:
                    lines_by_top[top_key] = []
                lines_by_top[top_key].append(c)

            page_lines_seen = set()
            for top_key in sorted(lines_by_top.keys()):
                line_chars = sorted(lines_by_top[top_key], key=lambda x: x['x0'])
                line_text = ' '.join(''.join(c['text'] for c in line_chars).split())
                if not line_text or len(line_text) <= 2:
                    continue

                key = (top_key, line_text)
                if key not in page_lines_seen:
                    page_lines_seen.add(key)
                    line_occurrences[key] = line_occurrences.get(key, 0) + 1

        threshold = len(sample_pages) * 0.5
        header_footer_entries = set()
        for (y_pos, text), count in line_occurrences.items():
            if count >= threshold:
                header_footer_entries.add((y_pos, text))

        self._header_footer_entries = header_footer_entries
        return header_footer_entries

    def detect_h1_headings(self) -> List[HeadingEntry]:
        # Detect H1 headings based on font size and styling.
        headings = []

        for page_num, page in enumerate(self._pdf.pages):
            if page_num in self._toc_pages:
                continue

            chars = page.chars
            if not chars:
                continue

            # Group chars by y-position
            lines_by_top = {}
            for c in chars:
                top_key = round(c['top'])
                if top_key not in lines_by_top:
                    lines_by_top[top_key] = []
                lines_by_top[top_key].append(c)

            for top_key in sorted(lines_by_top.keys()):
                line_chars = sorted(lines_by_top[top_key], key=lambda x: x['x0'])

                # Skip if it's a header/footer
                line_text = ' '.join(''.join(c['text'] for c in line_chars).split())
                if (top_key, line_text) in self._header_footer_entries:
                    continue

                if not line_text or len(line_text) <= 2:
                    continue

                # Check if this line has larger font (potential heading)
                avg_size = sum(c.get('size', 12) for c in line_chars) / len(line_chars)

                # H1 criteria: larger font, not too long, starts with capital
                if avg_size >= 14 and len(line_text) < 100 and line_text[0].isupper():
                    # Additional checks: mostly letters, not a sentence
                    if not line_text.endswith('.') or len(line_text.split()) <= 6:
                        headings.append(HeadingEntry(
                            title=line_text,
                            level=1,
                            page_num=page_num,
                            y_position=top_key
                        ))

        return headings

    def get_section_boundaries(self) -> List[Tuple[str, int, int]]:
        # Get section boundaries for splitting.

        # First try TOC
        toc_entries, toc_pages = self.detect_toc()
        self.detect_headers_footers()

        if toc_entries:
            # Store sub-titles (level 2) for use as ## headings within sections
            self._sub_titles = {e.title for e in toc_entries if e.level == 2}

            # Use TOC entries (only H1/main entries for splitting)
            main_entries = [e for e in toc_entries if e.level == 1]
            if main_entries:
                return self._boundaries_from_toc(main_entries)

        # Fallback to H1 heading detection
        h1_headings = self.detect_h1_headings()
        if h1_headings:
            return self._boundaries_from_headings(h1_headings)

        # No headings found - return entire document as one section
        return [("Document", 0, len(self._pdf.pages) - 1)]

    def _boundaries_from_toc(self, entries: List[TOCEntry]) -> List[Tuple[str, int, int]]:
        # Convert TOC entries to section boundaries.
        boundaries = []
        total_pages = len(self._pdf.pages)

        for i, entry in enumerate(entries):
            start_page = entry.page_num if entry.page_num is not None else 0

            if i + 1 < len(entries):
                next_page = entries[i + 1].page_num
                # Include the next section's start page — it may be shared
                # (next section starts mid-page).  The markdown converter
                # will stop at the next section's title regardless.
                end_page = next_page if next_page is not None else total_pages - 1
            else:
                end_page = total_pages - 1

            # Ensure valid range
            start_page = max(0, min(start_page, total_pages - 1))
            end_page = max(start_page, min(end_page, total_pages - 1))

            boundaries.append((entry.title, start_page, end_page))

        return boundaries

    def _boundaries_from_headings(self, headings: List[HeadingEntry]) -> List[Tuple[str, int, int]]:
        # Convert heading entries to section boundaries.
        boundaries = []
        total_pages = len(self._pdf.pages)

        for i, heading in enumerate(headings):
            start_page = heading.page_num

            if i + 1 < len(headings):
                # Include the next section's start page (may be shared mid-page)
                end_page = headings[i + 1].page_num
            else:
                end_page = total_pages - 1

            end_page = max(start_page, end_page)
            boundaries.append((heading.title, start_page, end_page))

        return boundaries

    @property
    def toc_pages(self) -> Set[int]:
        return self._toc_pages

    @property
    def header_footer_entries(self) -> Set[Tuple[int, str]]:
        return self._header_footer_entries

    @property
    def sub_titles(self) -> Set[str]:
        return self._sub_titles
