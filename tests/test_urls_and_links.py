"""Tests for URL normalization and BoardDocs link remapping helpers."""

from __future__ import annotations

import export_boarddocs as bd


def test_resolve_attachment_url_absolute_and_root_relative(base_url: str):
    absolute = "https://go.boarddocs.com/pa/phoe/Board.nsf/files/X/$file/a.pdf"
    assert bd.resolve_attachment_url(absolute, base_url) == absolute

    root = "/pa/phoe/Board.nsf/files/ABCDEF123456/$file/doc.pdf"
    assert bd.resolve_attachment_url(root, base_url) == f"https://go.boarddocs.com{root}"

    relative = "files/ABCDEF123456/$file/doc.pdf"
    resolved = bd.resolve_attachment_url(relative, base_url)
    assert resolved == f"{base_url}/files/ABCDEF123456/$file/doc.pdf"
    assert "board.nsf/board.nsf" not in resolved


def test_is_boarddocs_url(site: str, base_url: str):
    assert bd.is_boarddocs_url("https://go.boarddocs.com/pa/phoe/Board.nsf/Public", site)
    assert bd.is_boarddocs_url("/pa/phoe/Board.nsf/goto?open&id=ITEM1", site)
    assert not bd.is_boarddocs_url("https://example.com/doc.pdf", site)


def test_normalize_link_uri_strips_fragment_and_lowercases(base_url: str):
    uri = "HTTPS://GO.BOARDDOCS.COM/pa/phoe/Board.nsf/files/AbCdEf/#page=2"
    norm = bd.normalize_link_uri(uri, base_url)
    assert norm.endswith("/pa/phoe/board.nsf/files/abcdef")
    assert "#" not in norm


def test_extract_boarddocs_document_id():
    file_url = (
        "https://go.boarddocs.com/pa/phoe/Board.nsf/files/FILE1234567890/$file/x.pdf"
    )
    assert bd.extract_boarddocs_document_id(file_url) == "FILE1234567890"

    goto_url = "https://go.boarddocs.com/pa/phoe/Board.nsf/goto?open&id=ITEM9999999999"
    assert bd.extract_boarddocs_document_id(goto_url) == "ITEM9999999999"
    assert bd.extract_boarddocs_document_id("https://example.com/") is None


def test_url_lookup_keys_includes_site_slug_path(site: str, base_url: str):
    keys = bd.url_lookup_keys(
        f"https://go.boarddocs.com/{site}/Board.nsf/files/fileabc123456/$file/x.pdf",
        "/pa/phoe/Board.nsf/files/FILEABC123456/$file/x.pdf",
        "FILEABC123456",
        base_url,
        site,
    )
    assert "fileabc123456" in keys or "FILEABC123456" in keys
    assert f"/{site}/board.nsf/files/fileabc123456" in keys


def test_build_url_page_lookup_and_find_link_target_page(site: str, base_url: str):
    saved = [
        bd.SavedAttachment(
            bookmark="Budget.pdf",
            blob=b"%PDF",
            resolved_url=f"https://go.boarddocs.com/{site}/Board.nsf/files/FILE1111111111/$file/budget.pdf",
            href="/pa/phoe/Board.nsf/files/FILE1111111111/$file/budget.pdf",
            file_unique="FILE1111111111",
            item_unique="ITEM2222222222",
        )
    ]
    page_by_bookmark = {"Budget.pdf": 3}
    lookup = bd.build_url_page_lookup(page_by_bookmark, saved, base_url, site)

    file_uri = saved[0].resolved_url
    assert bd.find_link_target_page(file_uri, lookup, base_url, site) == 3

    goto_uri = f"https://go.boarddocs.com/{site}/Board.nsf/goto?open&id=ITEM2222222222"
    assert bd.find_link_target_page(goto_uri, lookup, base_url, site) == 3

    assert (
        bd.find_link_target_page("https://example.com/other.pdf", lookup, base_url, site)
        is None
    )


def test_annotate_boarddocs_links_in_html(site: str, base_url: str):
    agenda_html = """
    <p><a href="https://go.boarddocs.com/pa/phoe/Board.nsf/files/FILE1111111111/$file/a.pdf">
      Budget</a></p>
    <p><a href="https://example.com/external">Outside</a></p>
    """
    saved = [
        bd.SavedAttachment(
            bookmark="Budget.pdf",
            blob=b"x",
            resolved_url="https://go.boarddocs.com/pa/phoe/Board.nsf/files/FILE1111111111/$file/a.pdf",
            href="/pa/phoe/Board.nsf/files/FILE1111111111/$file/a.pdf",
            file_unique="FILE1111111111",
        )
    ]
    out = bd.annotate_boarddocs_links_in_html(agenda_html, base_url, site, saved)
    assert "data-boarddocs-bookmark" in out
    assert "Budget.pdf" in out
    assert "Attachment in this PDF" in out
    assert "example.com" in out


def test_prepare_agenda_html_strips_scripts_and_wraps_body(base_url: str, site: str):
    raw = """
    <html><head><script>alert(1)</script></head>
    <body><p class="print-meeting-name">Board Meeting</p></body></html>
    """
    doc = bd.prepare_agenda_html(raw, base_url, site=site, saved_attachments=None)
    assert "<script>" not in doc.lower()
    assert "print-meeting-name" in doc
    assert "<!DOCTYPE html>" in doc
    assert base_url in doc
