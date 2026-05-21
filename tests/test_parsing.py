"""Tests for HTML/JSON parsing helpers."""

from __future__ import annotations

import export_boarddocs as bd


def test_meeting_iso_date():
    meeting = bd.Meeting(
        unique="M1",
        name="Regular Meeting",
        numberdate="20260518",
        unid="u1",
    )
    assert meeting.iso_date == "2026-05-18"


def test_classify_content_section():
    assert bd.classify_content_section("I. Public Content") == "public"
    assert bd.classify_content_section("II. Administrative Content") == "administrative"
    assert bd.classify_content_section("III. Executive Content") == "executive"
    assert bd.classify_content_section("Consent Agenda") == "other"


def test_parse_public_files_html_with_size():
    html = (
        '<a class="public-file" unique="ABC123DEF456" '
        'href="/pa/phoe/Board.nsf/files/ABC123DEF456/$file/budget.pdf">'
        "Budget.pdf (1.2 MB)</a>"
    )
    attachments = bd.parse_public_files_html(html)
    assert len(attachments) == 1
    att = attachments[0]
    assert att.unique == "ABC123DEF456"
    assert att.name == "Budget.pdf"
    assert att.size == "1.2 MB"
    assert "budget.pdf" in att.href


def test_parse_file_links_from_html_dedupes_across_patterns():
    html = """
    <a class="public-file" unique="SAMEID123456" href="/files/SAMEID123456/a">Doc A</a>
    <a class="file" href="/pa/phoe/Board.nsf/files/SAMEID123456/$file/a">Doc A duplicate</a>
    """
    attachments = bd.parse_file_links_from_html(html)
    assert len(attachments) == 1
    assert attachments[0].unique == "SAMEID123456"


def test_parse_file_links_href_before_unique():
    html = (
        '<a class="administrative-file" href="/files/ADM1234567890/x" '
        'unique="ADM1234567890">Report.pdf</a>'
    )
    attachments = bd.parse_file_links_from_html(html)
    assert len(attachments) == 1
    assert attachments[0].unique == "ADM1234567890"
    assert attachments[0].name == "Report.pdf"


def test_parse_agenda_categories_and_items():
    agenda_html = """
    <ul>
      <li class="category wrap-category" unique="CAT1">
        <span>I.</span><span>Public Content</span>
      </li>
      <li class="wrap-item item" id="item-1" unique="ITEM1111111111"
          Xtitle="Approve minutes">
        <span>1.</span>
        <a class="public-file" unique="FILE2222222222"
           href="/pa/phoe/Board.nsf/files/FILE2222222222/$file/minutes.pdf">
          Minutes.pdf
        </a>
      </li>
      <li class="category wrap-category" unique="CAT2">
        <span>II.</span><span>Executive Content</span>
      </li>
      <li class="wrap-item item" id="item-2" unique="ITEM3333333333"
          Xtitle="Personnel matter">
        <span>2.</span><i class="fa-file-text-o"></i>
      </li>
    </ul>
    """
    categories = bd.parse_agenda_categories(agenda_html)
    assert len(categories) == 2
    assert categories[0][2] == "Public Content"
    assert categories[1][2] == "Executive Content"

    items = bd.parse_agenda_items(agenda_html)
    assert len(items) == 2

    assert items[0].unique == "ITEM1111111111"
    assert items[0].title == "Approve minutes"
    assert items[0].content_section == "public"
    assert items[0].category_name == "Public Content"
    assert len(items[0].attachments) == 1

    assert items[1].unique == "ITEM3333333333"
    assert items[1].content_section == "executive"
    assert items[1].has_attachment is True
    assert items[1].attachments == []


def test_summarize_agenda_sections():
    items = [
        bd.AgendaItem("a", "1", "A", True, [], "public", "Public"),
        bd.AgendaItem("b", "2", "B", False, [bd.Attachment("f", "/x", "x")], "public", "Public"),
        bd.AgendaItem("c", "3", "C", True, [], "executive", "Exec"),
    ]
    summary = bd.summarize_agenda_sections(items)
    assert summary["public"]["items"] == 2
    assert summary["public"]["with_icon"] == 1
    assert summary["public"]["with_inline_files"] == 1
    assert summary["executive"]["with_icon"] == 1


def test_fetch_attachments_from_endpoints_merges_and_dedupes():
    class FakeResponse:
        def __init__(self, status: int, text: str) -> None:
            self.status_code = status
            self.text = text

    class FakeClient:
        def post_raw(self, endpoint: str, data: str) -> FakeResponse:
            if endpoint == "BD-GetFiles":
                return FakeResponse(
                    200,
                    '<a class="file" unique="FILEAAAAAAAAAA" href="/a">A</a>',
                )
            if endpoint == "BD-GetPublicFiles":
                return FakeResponse(
                    200,
                    '<a class="public-file" unique="FILEAAAAAAAAAA" href="/a">A</a>'
                    '<a class="public-file" unique="FILEBBBBBBBBBB" href="/b">B</a>',
                )
            return FakeResponse(404, "")

    client = FakeClient()
    result = bd.fetch_attachments_from_endpoints(
        client,  # type: ignore[arg-type]
        "ITEM1",
        "COMM1",
        endpoints=("BD-GetFiles", "BD-GetPublicFiles"),
    )
    assert len(result) == 2
    uniques = {a.unique for a in result}
    assert uniques == {"FILEAAAAAAAAAA", "FILEBBBBBBBBBB"}
