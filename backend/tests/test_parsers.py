from pathlib import Path

import pypdf

from app.ingestion.parsers import ParsedSection, parse_markdown, parse_pdf


def test_parse_markdown_splits_by_heading_with_nested_paths():
    text = """# Title

Intro text.

## Section A

Content A.

### Subsection A.1

Content A.1.

## Section B

Content B.
"""

    sections = parse_markdown(text)

    assert sections == [
        ParsedSection(section="Title", content="Intro text."),
        ParsedSection(section="Title > Section A", content="Content A."),
        ParsedSection(section="Title > Section A > Subsection A.1", content="Content A.1."),
        ParsedSection(section="Title > Section B", content="Content B."),
    ]


def test_parse_markdown_skips_empty_sections():
    text = "# Title\n\n## Empty\n\n## Section\n\nContent.\n"

    sections = parse_markdown(text)

    assert sections == [ParsedSection(section="Title > Section", content="Content.")]


def test_parse_markdown_content_before_first_heading_has_no_section():
    text = "Just some text.\n\n# Title\n\nMore text.\n"

    sections = parse_markdown(text)

    assert sections == [
        ParsedSection(section=None, content="Just some text."),
        ParsedSection(section="Title", content="More text."),
    ]


def test_parse_pdf_skips_blank_pages(tmp_path: Path):
    pdf_path = tmp_path / "blank.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with pdf_path.open("wb") as f:
        writer.write(f)

    sections = parse_pdf(pdf_path)

    assert sections == []
