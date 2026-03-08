"""
Markdown to XHTML Converter - Industry Standard OEBPS Format.

Converts translated markdown content to XHTML paragraphs with proper
XML escaping, illustration handling, and formatting.

Path convention: Uses OEBPS standard paths (../Images/)
"""

import re
from typing import Dict, List, Tuple
from html import escape

try:
    from smartypants import smartypants, Attr
    SMARTYPANTS_AVAILABLE = True
except ImportError:
    SMARTYPANTS_AVAILABLE = False
    Attr = None

from ..config import SCENE_BREAK_MARKER, ILLUSTRATION_PLACEHOLDER_PATTERN, MARKDOWN_IMAGE_PATTERN
from .config import COLLAPSE_BLANK_LINES, BLANK_LINE_FREQUENCY, get_epub_version

# Industry-standard image path (OEBPS format)
IMAGES_PATH = "../Images"

# Footnote patterns
CUSTOM_FOOTNOTE_MARKER_RE = re.compile(r"\(\*\)")
MARKDOWN_FOOTNOTE_MARKER_RE = re.compile(r"\[\^([^\]]+)\]")
MARKDOWN_FOOTNOTE_DEF_RE = re.compile(r"^\[\^([^\]]+)\]:\s*(.+)$")
CUSTOM_FOOTNOTE_DEF_COLON_RE = re.compile(r"^\*\*\*(.+?):\*\*\s*(.+?)\*$")
CUSTOM_FOOTNOTE_DEF_SEP_RE = re.compile(r"^\*\*\*(.+?)\*\*\s*(?:[:：]|[-–—])\s*(.+?)\*$")
NOTEREF_PLACEHOLDER_RE = re.compile(r"__NOTEREF_(\d+)__")
STANDALONE_BR_RE = re.compile(r"^<br\s*/?>$", re.IGNORECASE)


class MarkdownToXHTML:
    """Converts markdown content to XHTML paragraph format."""

    @staticmethod
    def convert_paragraphs(paragraphs: List[str]) -> List[str]:
        """
        Convert a list of paragraphs to XHTML <p> tags.

        Args:
            paragraphs: List of paragraph strings (including "<blank>" markers)

        Returns:
            List of XHTML paragraph strings
        """
        xhtml_paragraphs = []

        for para in paragraphs:
            xhtml_para = MarkdownToXHTML._convert_single_paragraph(para)
            if xhtml_para:
                xhtml_paragraphs.append(xhtml_para)

        return xhtml_paragraphs

    @staticmethod
    def _convert_single_paragraph(para: str, skip_illustrations: bool = False) -> str:
        """
        Convert a single paragraph to XHTML.

        Args:
            para: Single paragraph string
            skip_illustrations: If True, skip illustration placeholders

        Returns:
            XHTML paragraph tag or empty string
        """
        if para == "<blank>":
            return '<p><br/></p>'

        # Check for standalone illustration placeholder (block-level)
        stripped = para.strip()
        if STANDALONE_BR_RE.match(stripped):
            return '<p class="lyric-break"><br/></p>'

        if MarkdownToXHTML._is_illustration_placeholder(stripped):
            if skip_illustrations:
                return ""
            else:
                return MarkdownToXHTML._convert_illustration_placeholder(stripped)

        # Check for scene break marker
        if stripped == SCENE_BREAK_MARKER:
            return '<p class="section-break">◆</p>'

        # Markdown blockquote support:
        # - Lyric blocks in memoir chapters use: > *line*
        # - Other blockquotes are rendered as quoted prose lines.
        if stripped.startswith(">"):
            return MarkdownToXHTML._convert_blockquote_block(para)

        # Check if paragraph contains inline image tags (normalize and preserve them)
        if '<img' in para and 'src=' in para:
            para = MarkdownToXHTML._normalize_inline_images(para)
            # Wrap in paragraph if not already wrapped
            if para.startswith('<img'):
                return f'<p class="illustration">{para}</p>'
            return para

        escaped_content = MarkdownToXHTML._render_inline_markdown(para)

        return f'<p>{escaped_content}</p>'

    @staticmethod
    def _convert_blockquote_line(stripped: str) -> str:
        """
        Convert markdown blockquote lines.
        - `> *...*` => lyric line
        - `>`      => stanza/quote break
        - other    => quoted prose line
        """
        block = stripped[1:].strip()
        if not block:
            return '<p class="lyric-break"><br/></p>'

        rendered = MarkdownToXHTML._render_inline_markdown(block)

        # Lyric lines in memoir chapters are consistently italicized in blockquotes.
        if block.startswith("*") and block.endswith("*"):
            return f'<p class="lyric">{rendered}</p>'

        return f'<p class="blockquote">{rendered}</p>'

    @staticmethod
    def _convert_blockquote_block(block: str) -> str:
        """
        Convert one paragraph that may contain multiple markdown blockquote lines.

        This preserves lyric stanza formatting when a stanza is serialized as:
        > *line 1*
        >
        > *line 2*
        """
        lines = []
        for raw in block.splitlines():
            stripped = raw.strip()
            if not stripped:
                continue
            if stripped.startswith(">"):
                lines.append(MarkdownToXHTML._convert_blockquote_line(stripped))
            else:
                # Mixed-content fallback: preserve non-blockquote lines as normal prose.
                rendered = MarkdownToXHTML._render_inline_markdown(stripped)
                lines.append(f'<p>{rendered}</p>')

        return "\n".join(lines)

    @staticmethod
    def _render_inline_markdown(content: str) -> str:
        """Render one inline markdown fragment to escaped XHTML-safe HTML."""
        if re.search(r'!\[gaiji\]\([^)]+\)', content):
            content = MarkdownToXHTML._convert_inline_gaiji(content)

        if SMARTYPANTS_AVAILABLE:
            stacked_quotes = []
            stacked_pattern = re.compile(r'"{3,}([^"]+)"{3,}')

            def protect_stacked(match):
                stacked_quotes.append(match.group(0))
                return f"__STACKED_{len(stacked_quotes)-1}__"

            content = stacked_pattern.sub(protect_stacked, content)
            content = smartypants(content, Attr.q | Attr.D | Attr.e)
            for idx, original in enumerate(stacked_quotes):
                content = content.replace(f"__STACKED_{idx}__", original)

        escaped_content = content.replace('&', '&amp;')
        escaped_content = escaped_content.replace('&amp;#', '&#')
        escaped_content = escaped_content.replace('<', '&lt;')
        escaped_content = escaped_content.replace('>', '&gt;')

        return MarkdownToXHTML._convert_markdown_formatting(escaped_content)

    @staticmethod
    def _normalize_inline_images(para: str) -> str:
        """
        Normalize existing img tags to OEBPS standard paths.
        
        Converts EN translation inline images to proper EPUB format:
        - Updates path from ../image/ to ../Images/
        - Updates class from 'fit' to 'insert'
        
        Args:
            para: Paragraph text containing img tags
            
        Returns:
            Normalized paragraph text
        """
        # Update path from ../image/ to ../Images/
        para = re.sub(
            r'src="\.\./image/([^"]+)"',
            r'src="../Images/\1"',
            para
        )
        # Update class from 'fit' to 'insert'
        para = re.sub(
            r'class="fit"',
            r'class="insert"',
            para
        )
        return para

    @staticmethod
    def _convert_inline_gaiji(text: str) -> str:
        """Convert inline `![gaiji](filename)` markdown to XHTML gaiji image tags."""
        return re.sub(
            r'!\[gaiji\]\(([^)]+)\)',
            lambda m: f'<img class="gaiji" src="{IMAGES_PATH}/{m.group(1)}" alt=""/>',
            text
        )

    @staticmethod
    def _convert_markdown_formatting(text: str) -> str:
        """
        Convert markdown formatting to HTML tags.

        Converts:
        - **bold** to <strong>bold</strong>
        - *italic* to <em>italic</em>

        Args:
            text: Text with markdown formatting

        Returns:
            Text with HTML tags
        """
        # Convert **bold** to <strong>bold</strong>
        text = re.sub(r'\*\*([^*]+?)\*\*', r'<strong>\1</strong>', text)

        # Convert *italic* to <em>italic</em>
        text = re.sub(r'(?<!\*)\*(?!\*)([^*]+?)(?<!\*)\*(?!\*)', r'<em>\1</em>', text)

        return text

    @staticmethod
    def _is_illustration_placeholder(text: str) -> bool:
        """Check if text contains an illustration placeholder (legacy or markdown format)."""
        # Legacy format: [ILLUSTRATION: filename]
        if re.search(ILLUSTRATION_PLACEHOLDER_PATTERN, text):
            return True
        # Markdown format: ![illustration](filename) or ![gaiji](filename)
        if re.search(MARKDOWN_IMAGE_PATTERN, text):
            return True
        return False

    @staticmethod
    def _convert_illustration_placeholder(text: str) -> str:
        """Convert illustration placeholder to XHTML img tag."""
        # Try legacy format first: [ILLUSTRATION: filename]
        match = re.search(ILLUSTRATION_PLACEHOLDER_PATTERN, text)
        if match:
            filename = match.group(1)
            return f'<p class="illustration"><img class="insert" src="{IMAGES_PATH}/{filename}" alt=""/></p>'
        
        # Try markdown format: ![alt](filename)
        match = re.search(MARKDOWN_IMAGE_PATTERN, text)
        if match:
            alt_type = match.group(1)  # 'illustration', 'gaiji', or ''
            filename = match.group(2)
            
            if alt_type == 'gaiji':
                # Gaiji: inline character - no wrapper paragraph, just the img
                # Will be embedded inline within surrounding text
                return f'<img class="gaiji" src="{IMAGES_PATH}/{filename}" alt=""/>'
            else:
                # Regular illustration - full block with wrapper
                return f'<p class="illustration"><img class="insert" src="{IMAGES_PATH}/{filename}" alt=""/></p>'
        
        return ""

    @staticmethod
    def convert_to_xhtml_string(paragraphs: List[str]) -> str:
        """
        Convert paragraphs to a single XHTML content string.

        Args:
            paragraphs: List of paragraph strings

        Returns:
            Concatenated XHTML paragraphs as string
        """
        filtered_paragraphs = MarkdownToXHTML._collapse_blank_lines(paragraphs)
        processed_paragraphs, footnotes = MarkdownToXHTML._prepare_footnotes(filtered_paragraphs)

        xhtml_paragraphs = MarkdownToXHTML.convert_paragraphs(processed_paragraphs)
        xhtml_content = '\n      '.join(xhtml_paragraphs)
        if footnotes:
            xhtml_content = MarkdownToXHTML._inject_noteref_links(xhtml_content, footnotes)
            footnotes_html = MarkdownToXHTML._build_footnotes_section(footnotes)
            if xhtml_content:
                return f"{xhtml_content}\n      {footnotes_html}"
            return footnotes_html

        return xhtml_content

    @staticmethod
    def _prepare_footnotes(paragraphs: List[str]) -> Tuple[List[str], List[Dict[str, str]]]:
        """Parse footnote definitions and inject noteref placeholders."""
        custom_marker_total = 0
        markdown_ref_ids = set()

        for para in paragraphs:
            if para == "<blank>":
                continue
            if MARKDOWN_FOOTNOTE_DEF_RE.match(para.strip()):
                continue
            custom_marker_total += len(CUSTOM_FOOTNOTE_MARKER_RE.findall(para))
            markdown_ref_ids.update(MARKDOWN_FOOTNOTE_MARKER_RE.findall(para))

        custom_defs: List[str] = []
        markdown_defs: Dict[str, str] = {}
        kept: List[str] = []

        for para in paragraphs:
            if para == "<blank>":
                kept.append(para)
                continue

            stripped = para.strip()
            md_def = MARKDOWN_FOOTNOTE_DEF_RE.match(stripped)
            if md_def:
                note_id = md_def.group(1).strip()
                if note_id in markdown_ref_ids:
                    markdown_defs[note_id] = md_def.group(2).strip()
                    continue

            custom_def = CUSTOM_FOOTNOTE_DEF_COLON_RE.match(stripped) or CUSTOM_FOOTNOTE_DEF_SEP_RE.match(stripped)
            if custom_def and len(custom_defs) < custom_marker_total:
                label = custom_def.group(1).strip().rstrip(":")
                body = custom_def.group(2).strip()
                custom_defs.append(f"{label}: {body}")
                continue

            kept.append(para)

        notes: List[Dict[str, str]] = []
        custom_index = 0
        output_paragraphs: List[str] = []

        for para in kept:
            if para == "<blank>":
                output_paragraphs.append(para)
                continue

            def markdown_ref_repl(match: re.Match) -> str:
                note_id = match.group(1).strip()
                note_text = markdown_defs.get(note_id)
                if not note_text:
                    return match.group(0)
                idx = len(notes) + 1
                notes.append({"number": str(idx), "text": note_text})
                return f"__NOTEREF_{idx}__"

            rendered = MARKDOWN_FOOTNOTE_MARKER_RE.sub(markdown_ref_repl, para)

            def custom_ref_repl(match: re.Match) -> str:
                nonlocal custom_index
                if custom_index >= len(custom_defs):
                    return match.group(0)
                idx = len(notes) + 1
                note_text = custom_defs[custom_index]
                custom_index += 1
                notes.append({"number": str(idx), "text": note_text})
                return f"__NOTEREF_{idx}__"

            rendered = CUSTOM_FOOTNOTE_MARKER_RE.sub(custom_ref_repl, rendered)
            output_paragraphs.append(rendered)

        return output_paragraphs, notes

    @staticmethod
    def _inject_noteref_links(xhtml_content: str, footnotes: List[Dict[str, str]]) -> str:
        """Replace `__NOTEREF_n__` placeholders with XHTML note reference links."""
        epub3 = get_epub_version() == "EPUB3"

        def repl(match: re.Match) -> str:
            num = int(match.group(1))
            if num < 1 or num > len(footnotes):
                return match.group(0)
            note_id = f"fn-{num}"
            ref_id = f"fnref-{num}"
            if epub3:
                return (
                    f'<a id="{ref_id}" class="noteref" href="#{note_id}" epub:type="noteref">[{num}]</a>'
                )
            return f'<a id="{ref_id}" class="noteref" href="#{note_id}">[{num}]</a>'

        return NOTEREF_PLACEHOLDER_RE.sub(repl, xhtml_content)

    @staticmethod
    def _build_footnotes_section(footnotes: List[Dict[str, str]]) -> str:
        """Build XHTML footnote section appended to the chapter body."""
        epub3 = get_epub_version() == "EPUB3"
        section_open = '<section class="footnotes" epub:type="footnotes">' if epub3 else '<section class="footnotes">'
        lines = [section_open, '        <h2>Notes</h2>', '        <ol class="footnote-list">']

        for item in footnotes:
            num = int(item["number"])
            note_id = f"fn-{num}"
            ref_id = f"fnref-{num}"
            note_html = MarkdownToXHTML._render_inline_markdown(item["text"])
            if epub3:
                lines.append(
                    '          '
                    + f'<li id="{note_id}" class="footnote-item" epub:type="footnote">'
                    + f'<p>{note_html} <a class="footnote-backref" href="#{ref_id}" aria-label="Back to text">↩</a></p>'
                    + '</li>'
                )
            else:
                lines.append(
                    '          '
                    + f'<li id="{note_id}" class="footnote-item">'
                    + f'<p>{note_html} <a class="footnote-backref" href="#{ref_id}" aria-label="Back to text">↩</a></p>'
                    + '</li>'
                )

        lines.extend(['        </ol>', '      </section>'])
        return "\n".join(lines)

    @staticmethod
    def _collapse_blank_lines(paragraphs: List[str]) -> List[str]:
        """
        Collapse consecutive <blank> markers to reduce visual breaks.
        Swallows the first blank line (standard paragraph separator) 
        but keeps subsequent ones as explicit breaks.

        Args:
            paragraphs: List of paragraph strings

        Returns:
            Filtered list with fewer <blank> markers
        """
        if not COLLAPSE_BLANK_LINES:
            return paragraphs

        filtered = []
        blank_run = 0

        for para in paragraphs:
            if para == "<blank>":
                blank_run += 1
                # Swallow the first blank line in any run
                # Keep any subsequent ones
                if blank_run > 1:
                    filtered.append(para)
            else:
                blank_run = 0
                filtered.append(para)

        return filtered

    @staticmethod
    def escape_xml_content(text: str) -> str:
        """Escape XML special characters in text content."""
        return escape(text)


def convert_paragraphs_to_xhtml(paragraphs: List[str], skip_illustrations: bool = False) -> str:
    """
    Main function to convert markdown paragraphs to XHTML.

    Args:
        paragraphs: List of paragraph strings
        skip_illustrations: If True, skip illustration placeholders

    Returns:
        XHTML content string
    """
    if skip_illustrations:
        xhtml_paragraphs = []
        for para in paragraphs:
            if para == "<blank>":
                xhtml_paragraphs.append('<p><br/></p>')
            elif not MarkdownToXHTML._is_illustration_placeholder(para):
                xhtml_para = MarkdownToXHTML._convert_single_paragraph(para, skip_illustrations=True)
                if xhtml_para:
                    xhtml_paragraphs.append(xhtml_para)
        return '\n      '.join(xhtml_paragraphs)
    else:
        return MarkdownToXHTML.convert_to_xhtml_string(paragraphs)


def extract_illustrations_from_paragraphs(paragraphs: List[str]) -> List[str]:
    """
    Extract illustration filenames from paragraph list.

    Args:
        paragraphs: List of paragraph strings

    Returns:
        List of illustration filenames
    """
    illustrations = []

    for para in paragraphs:
        match = re.search(ILLUSTRATION_PLACEHOLDER_PATTERN, para)
        if match:
            filename = match.group(1)
            illustrations.append(filename)

    return illustrations
