"""Tests that use PyMuPDF for minimal PDF assembly (no Playwright)."""

from __future__ import annotations

import fitz

import export_boarddocs as bd


def _minimal_agenda_pdf_with_link(uri: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    rect = fitz.Rect(72, 72, 200, 90)
    page.insert_link({"kind": fitz.LINK_URI, "from": rect, "uri": uri})
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_build_nested_agenda_pdf_remaps_boarddocs_link(site: str, base_url: str):
    file_unique = "FILE1111111111"
    uri = f"https://go.boarddocs.com/{site}/Board.nsf/files/{file_unique}/$file/budget.pdf"
    agenda_pdf = _minimal_agenda_pdf_with_link(uri)

    attachment_pdf = fitz.open()
    attachment_pdf.new_page()
    att_bytes = attachment_pdf.tobytes()
    attachment_pdf.close()

    saved = [
        bd.SavedAttachment(
            bookmark="Budget.pdf",
            blob=att_bytes,
            resolved_url=uri,
            href=f"/{site}/Board.nsf/files/{file_unique}/$file/budget.pdf",
            file_unique=file_unique,
        )
    ]

    result = bd.build_nested_agenda_pdf(
        agenda_pdf,
        saved,
        base_url=base_url,
        site=site,
    )

    doc = fitz.open(stream=result, filetype="pdf")
    try:
        assert doc.page_count >= 2
        found_goto = False
        for pno in range(doc.page_count):
            for link in doc[pno].get_links():
                if link.get("kind") == fitz.LINK_GOTO:
                    found_goto = True
                    assert link.get("page", link.get("page")) is not None
        assert found_goto, "expected at least one internal goto link after remap"
    finally:
        doc.close()


def test_html_to_pdf_story_produces_valid_pdf(base_url: str):
    html_doc = bd.prepare_agenda_html(
        "<body><p>Test agenda</p></body>",
        base_url,
    )
    pdf_bytes = bd.validate_pdf_bytes(bd.html_to_pdf_story(html_doc))
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        assert doc.page_count >= 1
    finally:
        doc.close()
