import re
from dataclasses import dataclass
from pathlib import Path

import pypdf

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


@dataclass
class ParsedSection:
    """A chunk-ready piece of a document: its content and where it came from."""

    section: str | None
    content: str


def parse_markdown(text: str) -> list[ParsedSection]:
    """Split markdown into one section per heading, following the heading hierarchy."""
    sections: list[ParsedSection] = []
    heading_stack: list[tuple[int, str]] = []
    current_lines: list[str] = []

    def flush() -> None:
        content = "\n".join(current_lines).strip()
        if content:
            path = " > ".join(title for _, title in heading_stack) or None
            sections.append(ParsedSection(section=path, content=content))

    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            flush()
            current_lines = []
            level = len(match.group(1))
            title = match.group(2)
            heading_stack = [h for h in heading_stack if h[0] < level]
            heading_stack.append((level, title))
        else:
            current_lines.append(line)
    flush()
    return sections


def parse_pdf(path: Path) -> list[ParsedSection]:
    """Split a PDF into one section per page."""
    reader = pypdf.PdfReader(str(path))
    sections: list[ParsedSection] = []
    for index, page in enumerate(reader.pages, start=1):
        content = (page.extract_text() or "").strip()
        if content:
            sections.append(ParsedSection(section=f"Page {index}", content=content))
    return sections
