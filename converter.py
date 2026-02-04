import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pdfplumber

from .extractor import ExtractedHyperlink, ExtractedImage


class MarkdownConverter:

    def __init__(
        self,
        pdf_path: str,
        section_title: str,
        section_id: str,
        images: List[ExtractedImage],
        hyperlinks: List[ExtractedHyperlink],
        header_footer_entries: Set[Tuple[int, str]],
        all_sections: Dict[str, str],  # title -> markdown filename mapping
        sub_titles: Optional[Set[str]] = None,
    ):
        self.pdf_path = Path(pdf_path)
        self.section_title = section_title
        self.section_id = section_id
        self.images = images
        self.hyperlinks = hyperlinks
        self.header_footer_entries = header_footer_entries
        self.all_sections = all_sections  # For internal link mapping
        self.sub_titles = sub_titles or set()
        self._content_started = False  # Tracks if passed over section title

    def convert(self) -> str:
        content_items = []

        with pdfplumber.open(self.pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages):
                page_content, stop_y = self._process_page(page, page_num)

                page_images = sorted(
                    [img for img in self.images if img.page_num == page_num and img.saved_path],
                    key=lambda img: img.y
                )

                if stop_y is not None:
                    page_images = [img for img in page_images if img.y < stop_y]

                if page_images:
                    merged = []
                    img_idx = 0
                    for item in page_content:
                        item_y = item.get('y', 0.0)
                        while img_idx < len(page_images) and page_images[img_idx].y < item_y:
                            img = page_images[img_idx]
                            merged.append({
                                'type': 'image',
                                'path': self._get_relative_image_path(img.saved_path),
                                'alt': f"Image from page {page_num + 1}"
                            })
                            img_idx += 1
                        merged.append(item)
                    while img_idx < len(page_images):
                        img = page_images[img_idx]
                        merged.append({
                            'type': 'image',
                            'path': self._get_relative_image_path(img.saved_path),
                            'alt': f"Image from page {page_num + 1}"
                        })
                        img_idx += 1
                    content_items.extend(merged)
                else:
                    content_items.extend(page_content)

        return self._format_to_markdown(content_items)

    def _process_page(self, page, page_num: int) -> Tuple[List[dict], float | None]:
        text = page.extract_text(layout=True)
        if not text:
            return [], None

        # Get tables and clean them (removes header fragments, merges continuation rows)
        found_tables = page.find_tables()
        tables = [t.extract() for t in found_tables]
        # Y-ranges (top, bottom) for spatial duplicate-text filtering
        table_bboxes = [(t.bbox[1], t.bbox[3]) for t in found_tables]
        cleaned_tables_with_bbox = self._clean_tables(tables, table_bboxes)
        cleaned_tables = [t for t, _ in cleaned_tables_with_bbox]
        table_content = self._get_table_text_content(cleaned_tables)

        # Get header line indices
        header_indices = self._get_header_line_indices(page)

        # Map each raw text line to its Y position on the page, then clean
        all_line_y = self._get_line_y_positions(page, text)
        lines, lines_y = self._clean_page_text(text, header_indices, all_line_y)

        # On first page, skip content until we find our own section title
        # (handles pages shared between sections, e.g. Section 01 and 02 both on page 3)
        if not self._content_started:
            start_idx = self._find_own_section_start(lines)
            if start_idx >= 0:
                lines = lines[start_idx:]
                lines_y = lines_y[start_idx:]
                self._content_started = True
            else:
                # Our title not on this page — skip entire page
                return [], None

        result = []
        i = 0
        table_insert_pos = None  # Position in result where first table text was filtered
        table_insert_y = None
        stop_y = None  # Set when we hit the next section's title

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Skip paragraph separator markers
            if not stripped:
                i += 1
                continue

            indent = len(line) - len(line.lstrip())
            normalized = ' '.join(stripped.split())
            item_y = lines_y[i] if i < len(lines_y) else 0.0

            # Stop if we hit another section's title
            if self._is_next_section_title(normalized):
                stop_y = item_y
                break

            # Check for sub-heading from TOC (## heading)
            if self._is_sub_title(normalized):
                result.append({'type': 'heading', 'level': 2, 'text': normalized, 'y': item_y})
                i += 1
                continue

            # Check for bullet
            if stripped.startswith('•'):
                bullet_text, sub_items, j = self._parse_bullet(lines, i, indent)
                result.append({'type': 'bullet', 'level': 0, 'text': bullet_text, 'y': item_y})
                for level, text in sub_items:
                    result.append({'type': 'bullet', 'level': level, 'text': text, 'y': item_y})
                i = j
                continue

            # Check for numbered list
            numbered_match = re.match(r'^(\d+)\.\s*(.*)$', stripped)
            if numbered_match:
                num_text, sub_items, j = self._parse_numbered(lines, i, indent)
                result.append({
                    'type': 'numbered',
                    'level': 0,
                    'marker': numbered_match.group(1),
                    'text': num_text,
                    'y': item_y
                })
                for sub in sub_items:
                    result.append({
                        'type': 'numbered',
                        'level': sub['level'],
                        'marker': sub['marker'],
                        'text': sub['text'],
                        'y': item_y
                    })
                i = j
                continue

            # Check for continued sub-item
            letter_match = re.match(r'^([a-z])\.\s*(.*)$', stripped)
            if letter_match and indent > 0:
                effective_base = indent - 5  # default estimate
                for k in range(i + 1, min(i + 30, len(lines))):
                    if not lines[k].strip():
                        continue
                    pk_indent = len(lines[k]) - len(lines[k].lstrip())
                    if re.match(r'^\d+\.\s*', lines[k].strip()) and pk_indent < indent:
                        effective_base = pk_indent
                        break
                _, sub_items, j = self._parse_numbered(lines, i, effective_base, start_as_sub=True)
                for sub in sub_items:
                    result.append({
                        'type': 'numbered',
                        'level': sub['level'],
                        'marker': sub['marker'],
                        'text': sub['text'],
                        'y': item_y
                    })
                i = j
                continue

            # Two checks: text-match for cells extracted by pdfplumber, and spatial
            if cleaned_tables and (self._is_table_text(normalized, table_content)
                                   or any(y0 <= item_y <= y1 for y0, y1 in table_bboxes)):
                if table_insert_pos is None:
                    table_insert_pos = len(result)
                    table_insert_y = item_y
                i += 1
                continue

            # Check for sub-heading (### level) — short title-like lines not in TOC
            if self._is_heading(normalized):
                result.append({'type': 'heading', 'level': 3, 'text': normalized, 'y': item_y})
                i += 1
                continue

            # Regular paragraph
            para_text, j = self._parse_paragraph(lines, i, indent, table_content if cleaned_tables else set())
            if para_text.strip():
                # Apply hyperlink mapping
                para_text = self._apply_hyperlinks(para_text)
                result.append({'type': 'paragraph', 'text': para_text, 'y': item_y})
            i = j

        # If stop_y is set (shared page), skip tables whose top edge is at or below stop_y.
        for table, (ty0, _ty1) in cleaned_tables_with_bbox:
            if stop_y is not None and ty0 >= stop_y:
                continue
            if table and len(table) >= 2:
                md_table = self._table_to_markdown(table)
                if md_table:
                    if table_insert_pos is not None:
                        result.insert(table_insert_pos, {'type': 'table', 'text': md_table, 'y': table_insert_y or 0.0})
                        table_insert_pos += 1
                    else:
                        result.append({'type': 'table', 'text': md_table, 'y': 0.0})

        return result, stop_y

    def _clean_page_text(self, text: str, header_indices: Set[int], all_line_y: List[float]) -> Tuple[List[str], List[float]]:

        lines = text.splitlines()
        cleaned = []
        cleaned_y = []
        prev_blank = False

        for idx, line in enumerate(lines):
            stripped = line.strip()
            if idx in header_indices:
                continue
            if stripped.isdigit() and len(stripped) <= 3:
                continue
            if not stripped:
                if not prev_blank and cleaned:
                    cleaned.append('')  # Single blank as paragraph separator
                    cleaned_y.append(cleaned_y[-1] if cleaned_y else 0.0)
                    prev_blank = True
                continue
            cleaned.append(line)
            cleaned_y.append(all_line_y[idx] if idx < len(all_line_y) else 0.0)
            prev_blank = False

        return cleaned, cleaned_y

    def _get_header_line_indices(self, page) -> Set[int]:
        chars = page.chars
        if not chars:
            return set()

        text = page.extract_text(layout=True)
        if not text:
            return set()

        lines = text.splitlines()

        # Group chars by y-position
        lines_by_top = {}
        for c in chars:
            top_key = round(c['top'])
            if top_key not in lines_by_top:
                lines_by_top[top_key] = []
            lines_by_top[top_key].append(c)

        # Build text for each y-position
        y_texts = {}
        for top_key in sorted(lines_by_top.keys()):
            line_chars = sorted(lines_by_top[top_key], key=lambda x: x['x0'])
            y_texts[top_key] = ' '.join(''.join(c['text'] for c in line_chars).split())

        # Find header y-positions on this page
        header_y_positions = set()
        for top_key, line_text in y_texts.items():
            if (top_key, line_text) in self.header_footer_entries:
                header_y_positions.add(top_key)

        # Match to line indices
        header_indices = set()
        for y_pos in header_y_positions:
            header_text = y_texts.get(y_pos, '')
            if not header_text:
                continue
            for idx, line in enumerate(lines):
                normalized = ' '.join(line.strip().split())
                if normalized == header_text and idx not in header_indices:
                    header_indices.add(idx)
                    break

        return header_indices

    def _get_first_content_y(self, page) -> float:
        chars = page.chars
        if not chars:
            return 0.0

        # Group chars by y-position
        lines_by_top = {}
        for c in chars:
            top_key = round(c['top'])
            if top_key not in lines_by_top:
                lines_by_top[top_key] = []
            lines_by_top[top_key].append(c)

        # Walk lines top-to-bottom, return first that isn't header/page number
        for top_key in sorted(lines_by_top.keys()):
            line_chars = sorted(lines_by_top[top_key], key=lambda x: x['x0'])
            line_text = ' '.join(''.join(c['text'] for c in line_chars).split())

            if not line_text.strip():
                continue
            if line_text.strip().isdigit() and len(line_text.strip()) <= 3:
                continue
            if (top_key, line_text) in self.header_footer_entries:
                continue
            return float(top_key)

        return 0.0

    def _get_line_y_positions(self, page, text: str) -> List[float]:

        text_lines = text.splitlines()
        chars = page.chars
        if not chars:
            return [0.0] * len(text_lines)

        # Group chars by rounded Y — same approach as _get_header_line_indices
        lines_by_top: dict = {}
        for c in chars:
            top_key = round(c['top'])
            if top_key not in lines_by_top:
                lines_by_top[top_key] = []
            lines_by_top[top_key].append(c)

        sorted_ys = sorted(lines_by_top.keys())

        # Merge consecutive Y keys within 3 points into one group.
        # Use the first (topmost) Y as the representative.
        # Skip groups that contain only whitespace characters.
        merged_y_positions: List[float] = []
        i = 0
        while i < len(sorted_ys):
            group_start = sorted_ys[i]
            # Collect all consecutive Ys within 3 points of group_start
            all_chars_in_group: list = list(lines_by_top[sorted_ys[i]])
            j = i + 1
            while j < len(sorted_ys) and sorted_ys[j] - group_start <= 3:
                all_chars_in_group.extend(lines_by_top[sorted_ys[j]])
                j += 1
            # Skip if group is whitespace-only
            group_text = ''.join(c.get('text', '') for c in all_chars_in_group)
            if group_text.strip():
                merged_y_positions.append(float(group_start))
            i = j

        # Sequential match: each non-empty text line consumes the next merged Y
        result = []
        y_idx = 0
        for line in text_lines:
            if line.strip():
                if y_idx < len(merged_y_positions):
                    result.append(merged_y_positions[y_idx])
                    y_idx += 1
                else:
                    result.append(0.0)
            else:
                result.append(-1.0)

        return result

    def _normalize_title(self, text: str) -> str:
        return ' '.join(text.strip(':').strip().lower().split())

    def _find_own_section_start(self, lines: List[str]) -> int:
       
        own_normalized = self._normalize_title(self.section_title)

        for idx, line in enumerate(lines):
            normalized = self._normalize_title(line.strip())
            if normalized == own_normalized:
                return idx + 1  # Start from line after the title

        # Title not found — this page is entirely ours, start from top
        return 0

    def _is_sub_title(self, text: str) -> bool:
        #Check if text matches sub-title from TOC
        if not text or not self.sub_titles:
            return False
        text_normalized = self._normalize_title(text)
        for sub in self.sub_titles:
            if text_normalized == self._normalize_title(sub):
                return True
        return False

    def _is_heading(self, text: str) -> bool:
        #Check if text looks like a heading.

        if not text or len(text) > 60:
            return False

        # Skip if it matches the section title (already shown as H1)
        if text.strip(':').lower() == self.section_title.strip(':').lower():
            return False

        if not text[0].isupper():
            return False

        words = text.split()
        if len(words) > 8:
            return False

        # Sentences typically have commas
        if ',' in text:
            return False

        # Don't treat sentences starting with these as headings
        sentence_starters = {'to', 'the', 'a', 'an', 'if', 'when', 'as', 'for', 'due', 'in', 'on', 'by'}
        if words[0].lower() in sentence_starters:
            return False

        # Common sentence verbs - if present, likely not a heading
        sentence_verbs = {'will', 'have', 'has', 'been', 'being', 'are', 'is', 'was', 'were'}
        text_lower = text.lower()
        for verb in sentence_verbs:
            if f' {verb} ' in text_lower or text_lower.endswith(f' {verb}'):
                return False

        # Sentences ending with period and many words
        if text.endswith('.') and len(words) > 4:
            return False

        # Mid-sentence periods (e.g. "Ordinance Sec. 22.03.095.") indicate a fragment, not a heading
        text_core = text.rstrip('.,:;')
        if '.' in text_core:
            return False

        return True

    def _is_next_section_title(self, text: str) -> bool:
        #Check if text matches another section's title (not the current section).

        if not text:
            return False

        # Normalize for comparison - remove punctuation, extra spaces, normalize case
        text_normalized = ' '.join(text.strip(':').strip().lower().split())

        for section_title in self.all_sections.keys():
            # Skip our own section
            own_normalized = ' '.join(self.section_title.strip(':').strip().lower().split())
            if section_title.strip(':').strip().lower() == own_normalized:
                continue

            # Check if this text matches another section's title
            section_normalized = ' '.join(section_title.strip(':').strip().lower().split())

            if text_normalized == section_normalized:
                return True

            # Check without trailing punctuation
            if text_normalized.rstrip(':.') == section_normalized.rstrip(':.'):
                return True

            # Check if text starts with or contains section title
            if text_normalized.startswith(section_normalized) and len(text_normalized) < len(section_normalized) + 20:
                return True

            # Check if section title is contained in text (for cases where title has extra text)
            if section_normalized in text_normalized and len(section_normalized) > 10:
                return True

        return False

    def _parse_bullet(self, lines: List[str], start: int, base_indent: int) -> Tuple[str, List[Tuple[int, str]], int]:
        
        line = lines[start]
        bullet_text = line.strip()[1:].strip()  # Remove bullet character •
        sub_items: List[Tuple[int, str]] = []
        j = start + 1

        # Indent thresholds relative to base bullet indent
        sub_indent_min = base_indent + 4      # Sub-bullet level (e.g. 15 for base=11)
        sub_sub_indent_min = base_indent + 9  # Sub-sub-bullet level (e.g. 20 for base=11)

        last_was_marker_skip = False  # True after skipping a standalone 'o' or '\uf0a7'

        while j < len(lines):
            next_line = lines[j]
            next_stripped = next_line.strip()

            # Skip blank lines within bullet blocks (PDF rendering artifacts)
            if not next_stripped:
                j += 1
                continue

            next_indent = len(next_line) - len(next_line.lstrip())
            next_normalized = ' '.join(next_stripped.split())

            # Stop conditions
            if self._is_next_section_title(next_normalized):
                break
            if self._is_sub_title(next_normalized):
                break
            if next_stripped.startswith('•'):
                break

            # Skip standalone markers only ('o' alone or '\uf0a7' alone)
            if next_stripped == 'o' or next_stripped == '\uf0a7':
                last_was_marker_skip = True
                j += 1
                continue

            # Sub-sub-bullet: line starting with \uf0a7 followed by content
            if next_stripped.startswith('\uf0a7') and len(next_stripped) > 1:
                text = next_stripped[1:].strip()
                if text:
                    sub_items.append((2, text))
                last_was_marker_skip = False
                j += 1
                continue

            # Sub-sub-bullet continuation (high indent after a sub-sub item)
            if next_indent >= sub_sub_indent_min:
                if sub_items and sub_items[-1][0] == 2:
                    sub_items[-1] = (2, sub_items[-1][1] + ' ' + next_stripped)
                else:
                    sub_items.append((1, next_stripped))
                last_was_marker_skip = False
                j += 1
                continue

            # Sub-bullet level text
            if next_indent >= sub_indent_min:
                if last_was_marker_skip and sub_items and sub_items[-1][0] == 1:
                    # After 'o' skip — continuation of current sub-bullet
                    sub_items[-1] = (1, sub_items[-1][1] + ' ' + next_stripped)
                else:
                    # New sub-bullet
                    sub_items.append((1, next_stripped))
                last_was_marker_skip = False
                j += 1
                continue

            # Main bullet continuation (indent between base and sub level)
            if next_indent >= base_indent and next_indent < sub_indent_min:
                if not sub_items:
                    bullet_text += ' ' + next_stripped
                else:
                    break  # Past the sub-bullets — stop
                last_was_marker_skip = False
                j += 1
                continue

            # Below base indent — stop
            break

        return bullet_text.strip(), sub_items, j

    # Valid Roman numerals for level-2 marker detection
    _ROMAN_NUMERALS = {
        'i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x',
        'xi', 'xii', 'xiii', 'xiv', 'xv', 'xvi', 'xvii', 'xviii', 'xix', 'xx'
    }

    def _parse_numbered(self, lines: List[str], start: int, base_indent: int,
                        start_as_sub: bool = False) -> Tuple[str, List[dict], int]:
        """Parse a numbered list item and its sub-items using indentation.

        Levels are determined by indent thresholds relative to *base_indent*:
          Level 0 – top-level number (1., 2., …)        indent <= base + 3
          Level 1 – letter sub-item (a., b., …)         indent in [base+4, base+9)
          Level 2 – roman sub-item (i., ii., …)         indent in [base+9, base+14)
          Level 3 – sub-number (1., 2., …)              indent >= base+14
        """
        if start_as_sub:
            num_text = ''
            j = start
        else:
            line = lines[start]
            match = re.match(r'^(\d+)\.\s*(.*)$', line.strip())
            num_text = match.group(2) if match else ''
            j = start + 1
        sub_items: List[dict] = []

        # Current item at each nesting level — used for continuation appending
        current_at: dict = {}  # level -> item dict

        L1 = base_indent + 4
        L2 = base_indent + 9
        L3 = base_indent + 14

        while j < len(lines):
            next_line = lines[j]
            next_stripped = next_line.strip()

            if not next_stripped:
                j += 1
                continue

            next_indent = len(next_line) - len(next_line.lstrip())
            next_normalized = ' '.join(next_stripped.split())

            # Hard stop conditions
            if self._is_next_section_title(next_normalized):
                break
            if self._is_sub_title(next_normalized):
                break
            if next_stripped.startswith('•'):
                break

            # Classify indent → level
            if next_indent >= L3:
                level = 3
            elif next_indent >= L2:
                level = 2
            elif next_indent >= L1:
                level = 1
            else:
                level = 0

            # Level 0: at or below base indent
            if level == 0:
                if re.match(r'^\d+\.\s*', next_stripped):
                    break  # new top-level numbered item
                if not sub_items and next_indent >= base_indent:
                    # Continuation text at base indent (e.g. a long quoted string
                    # that wraps at the same indent as the number)
                    num_text += ' ' + next_stripped
                    j += 1
                    continue
                break  # content below base or after sub-items — stop

            # Try to match a marker appropriate for this level
            new_item = None
            if level == 1:
                m = re.match(r'^([a-z])\.\s*(.*)$', next_stripped)
                if m:
                    new_item = {'level': 1, 'marker': m.group(1), 'text': m.group(2)}
            elif level == 2:
                m = re.match(r'^([a-z]+)\.\s*(.*)$', next_stripped)
                if m and m.group(1) in self._ROMAN_NUMERALS:
                    new_item = {'level': 2, 'marker': m.group(1), 'text': m.group(2)}
            elif level == 3:
                m = re.match(r'^(\d+)\.\s*(.*)$', next_stripped)
                if m:
                    new_item = {'level': 3, 'marker': m.group(1), 'text': m.group(2)}

            if new_item:
                sub_items.append(new_item)
                current_at[level] = new_item
                # Reset deeper levels
                for deeper in range(level + 1, 4):
                    current_at.pop(deeper, None)
            else:
                # Continuation – attach to the deepest active item at ≤ this level
                target = level
                while target >= 1 and target not in current_at:
                    target -= 1
                if target >= 1:
                    current_at[target]['text'] += ' ' + next_stripped
                else:
                    num_text += ' ' + next_stripped

            j += 1

        # Trim whitespace
        num_text = num_text.strip()
        for item in sub_items:
            item['text'] = item['text'].strip()

        return num_text, sub_items, j

    def _parse_paragraph(self, lines: List[str], start: int, base_indent: int, table_content: Set[str]) -> Tuple[str, int]:
        
        para_text = lines[start].strip()
        j = start + 1

        while j < len(lines):
            next_line = lines[j]
            next_stripped = next_line.strip()

            # Blank line: check if continuation (next non-blank starts lowercase) or paragraph break
            if not next_stripped:
                k = j + 1
                while k < len(lines) and not lines[k].strip():
                    k += 1
                if k < len(lines):
                    peek = lines[k].strip()
                    if peek and peek[0].islower():
                        # Lowercase continuation — skip blank(s) and rejoin
                        j = k
                        continue
                # Uppercase or special char or end of lines — paragraph break
                break

            next_indent = len(next_line) - len(next_line.lstrip())
            next_normalized = ' '.join(next_stripped.split())

            # Stop at another section's title or sub-heading
            if self._is_next_section_title(next_normalized):
                break
            if self._is_sub_title(next_normalized):
                break
            if self._is_table_text(next_stripped, table_content):
                j += 1
                continue
            if self._is_heading(next_normalized):
                break
            if next_stripped.startswith('•'):
                break
            if re.match(r'^(\d+|[a-z])\.\s*', next_stripped):
                break
            if abs(next_indent - base_indent) < 10:
                para_text += ' ' + next_stripped
                j += 1
            else:
                break

        return para_text, j

    def _get_table_text_content(self, tables) -> Set[str]:

        content = set()
        for table in tables:
            if table:
                for row in table:
                    if row:
                        for cell in row:
                            if cell:
                                text = ' '.join(str(cell).split())
                                if len(text) > 3:
                                    content.add(text)
        return content

    def _is_table_text(self, text: str, table_content: Set[str]) -> bool:
       
        normalized = ' '.join(text.split())
        if normalized in table_content:
            return True
        for tc in table_content:
            if len(tc) > 10:
                if tc in normalized:
                    return True
                # Reverse: text is a substring of a table cell (handles merged cells)
                if len(normalized) > 5 and normalized in tc:
                    return True
        return False

    def _clean_table_cell(self, cell, header_texts: Set[str]) -> str:
    
        if cell is None:
            return ''

        lines = [l.strip() for l in str(cell).split('\n') if l.strip()]

        if header_texts:
            filtered = []
            for line in lines:
                is_fragment = False
                if len(line) > 3:
                    for header in header_texts:
                        if line in header or header.startswith(line):
                            is_fragment = True
                            break
                if not is_fragment:
                    filtered.append(line)
            # Only apply filtering when other content survives.  A cell
            # whose sole value is a word like "Disconnection" must not be
            # emptied just because it is a substring of a page header.
            if filtered:
                lines = filtered

        return ' '.join(lines)

    def _clean_tables(self, tables, bboxes=None) -> List[list]:
      
        header_texts = {text for _, text in self.header_footer_entries}
        cleaned_tables = []
        use_bbox = bboxes is not None

        for idx, table in enumerate(tables):
            if not table:
                continue

            # Clean all cells
            cleaned = []
            for row in table:
                if not row:
                    continue
                cleaned.append([self._clean_table_cell(cell, header_texts) for cell in row])

            # Determine number of actually used columns (trim trailing empty cols)
            max_used_cols = 0
            for row in cleaned:
                for ci in range(len(row) - 1, -1, -1):
                    if row[ci].strip():
                        max_used_cols = max(max_used_cols, ci + 1)
                        break

            if max_used_cols < 2:
                continue  # Skip single-column or empty tables

            # Trim to used columns
            cleaned = [row[:max_used_cols] for row in cleaned]

            # Merge continuation rows
            merged = []
            for row in cleaned:
                is_continuation = (merged
                                   and not row[0].strip()
                                   and (len(row) < 2 or not row[1].strip()))
                if is_continuation:
                    for ci in range(min(len(row), len(merged[-1]))):
                        if row[ci].strip():
                            merged[-1][ci] = (merged[-1][ci] + ' ' + row[ci]).strip()
                else:
                    merged.append(list(row))

            # Filter out entirely empty rows
            merged = [row for row in merged if any(c.strip() for c in row)]

            # Merge columns where pdfplumber over-detected boundaries
            merged = self._merge_sparse_columns(merged)

            if len(merged) >= 2:
                if use_bbox:
                    cleaned_tables.append((merged, bboxes[idx]))
                else:
                    cleaned_tables.append(merged)

        return cleaned_tables

    def _merge_sparse_columns(self, table: List[List[str]]) -> List[List[str]]:
        
        if not table or len(table) < 2:
            return table

        header = table[0]
        num_cols = len(header)

        # Positions of non-empty header cells
        header_cols = [i for i, h in enumerate(header) if h.strip()]

        # Nothing to merge if every column already has a header, or < 2 logical cols
        if len(header_cols) >= num_cols or len(header_cols) < 2:
            return table

        # Define column groups based on header positions
        groups: List[Tuple[int, int]] = []
        prev = -1
        for hc in header_cols:
            groups.append((prev + 1, hc))
            prev = hc
        # Trailing columns after the last header col join the last group
        if prev < num_cols - 1:
            groups[-1] = (groups[-1][0], num_cols - 1)

        # Merge each row according to groups
        merged_table: List[List[str]] = []
        for row in table:
            new_row: List[str] = []
            for start, end in groups:
                cells = [row[c].strip() for c in range(start, end + 1) if c < len(row)]
                # Remove empties, then deduplicate:
                # 1) exact duplicates   2) cells that are substrings of another
                cells = list(dict.fromkeys(c for c in cells if c))
                deduped = [c for c in cells if not any(c != other and c in other for other in cells)]
                new_row.append(' '.join(deduped))
            merged_table.append(new_row)

        return merged_table

    def _table_to_markdown(self, table) -> str:
        # Convert a pre-cleaned table to markdown format
        if not table or len(table) < 2:
            return ""

        max_cols = max(len(row) for row in table)
        for row in table:
            while len(row) < max_cols:
                row.append("")

        md_lines = []
        header = table[0]
        md_lines.append("| " + " | ".join(header) + " |")
        md_lines.append("| " + " | ".join(["---"] * len(header)) + " |")

        for row in table[1:]:
            md_lines.append("| " + " | ".join(row[:len(header)]) + " |")

        return "\n".join(md_lines)

    def _apply_hyperlinks(self, text: str) -> str:
        # Apply hyperlink mapping to text.

        merged: List[dict] = []
        for link in self.hyperlinks:
            if merged and merged[-1]['url'] == link.url and not link.is_internal:
                merged[-1]['text'] += ' ' + link.text
            else:
                merged.append({
                    'text': link.text,
                    'url': link.url,
                    'is_internal': link.is_internal
                })

        # Apply longest match first so merged phrases take priority
        for ml in sorted(merged, key=lambda x: len(x['text']), reverse=True):
            if ml['text'] not in text:
                continue
            if ml['is_internal']:
                for title, md_file in self.all_sections.items():
                    if title.lower() in ml['url'].lower() or ml['url'].lower() in title.lower():
                        text = text.replace(ml['text'], f"[{ml['text']}](../markdown/{md_file})", 1)
                        break
            else:
                text = text.replace(ml['text'], f"[{ml['text']}]({ml['url']})", 1)

        return text

    def _get_relative_image_path(self, image_path: str) -> str:
        # Get relative path from markdown to image
        return f"../assets/images/{Path(image_path).name}"

    def _format_to_markdown(self, content_items: List[dict]) -> str:
        # Format content items to markdown string
        md_lines = []

        # Add title
        md_lines.append(f"# {self.section_title}\n")

        for item in content_items:
            if item['type'] == 'heading':
                hashes = '#' * item['level']
                md_lines.append(f"\n{hashes} {item['text']}\n")

            elif item['type'] == 'bullet':
                indent = '  ' * item['level']
                md_lines.append(f"{indent}- {item['text']}")

            elif item['type'] == 'numbered':
                indent = '  ' * item['level']
                md_lines.append(f"{indent}{item['marker']}. {item['text']}")

            elif item['type'] == 'paragraph':
                md_lines.append(f"\n{item['text']}\n")

            elif item['type'] == 'table':
                md_lines.append(f"\n{item['text']}\n")

            elif item['type'] == 'image':
                md_lines.append(f"\n![{item['alt']}]({item['path']})\n")

        # Clean up multiple newlines
        result = '\n'.join(md_lines)
        result = re.sub(r'\n{3,}', '\n\n', result)

        return result
