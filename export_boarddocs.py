#!/usr/bin/env python3
"""
Export BoardDocs agendas and attachments as nested PDFs.

Output layout:
  {district_id}/{Public|Private}/{committee_name}/{YYYY-MM-DD}-Agenda.pdf

Each agenda PDF contains the printed agenda plus embedded attachment files
(PDF portfolio) and appended non-PDF pages where conversion is possible.

If any attachment cannot be downloaded, the meeting export fails (no partial PDF).

BoardDocs hyperlinks in agenda PDFs are remapped to internal attachment bookmarks so
exports remain usable after the district ends its BoardDocs contract.

Public access uses BoardDocs POST endpoints (BD-GetMeetingsList, BD-GetAgenda,
BD-GetPublicFiles, PRINT-AgendaDetailed). Private access reuses the same flow
after Playwright login, using BD-GetFiles when public files are unavailable.
"""

from __future__ import annotations

import argparse
import getpass
import html
import io
import json
import logging
import platform
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup

try:
    import fitz  # PyMuPDF
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyMuPDF is required: pip install pymupdf") from exc

LOG = logging.getLogger("boarddocs-export")

DEFAULT_SITE = "pa/phoe"
DISCOVERY_DIR = "discovery"

# BoardDocs logged-in agendas often group items under these category titles.
CONTENT_SECTION_MARKERS: tuple[tuple[str, str], ...] = (
    ("public content", "public"),
    ("administrative content", "administrative"),
    ("executive content", "executive"),
)

# CSS classes observed or expected on file download anchors.
FILE_LINK_CLASSES: tuple[str, ...] = (
    "public-file",
    "file",
    "administrative-file",
    "executive-file",
    "private-file",
)

# Endpoints probed during --survey-content (private session).
SURVEY_FILE_ENDPOINTS: tuple[str, ...] = (
    "BD-GetFiles",
    "BD-GetPublicFiles",
    "BD-GetAdministrativeFiles",
    "BD-GetExecutiveFiles",
    "BD-GetAllFiles",
)

PRIVATE_FILE_ENDPOINTS: tuple[str, ...] = (
    "BD-GetFiles",
    "BD-GetPublicFiles",
)
DEFAULT_PUBLIC_URL = "https://go.boarddocs.com/pa/phoe/Board.nsf/Public"
DEFAULT_OUTPUT = "output"
DEFAULT_CONFIG_NAME = "config.json"
REQUEST_DELAY_SEC = 0.25

# JSON keys (snake_case or kebab-case) mapped to argparse dest names.
CONFIG_KEY_ALIASES: dict[str, str] = {
    "public-url": "public_url",
    "public_url": "public_url",
    "committee-id": "committee_ids",
    "committee_ids": "committee_ids",
    "committee-ids": "committee_ids",
    "public-only": "public_only",
    "public_only": "public_only",
    "private-only": "private_only",
    "private_only": "private_only",
    "login-url": "login_url",
    "login_url": "login_url",
    "cookies-file": "cookies_file",
    "cookies_file": "cookies_file",
    "headed-login": "headed_login",
    "headed_login": "headed_login",
    "pdf-engine": "pdf_engine",
    "pdf_engine": "pdf_engine",
    "request-delay": "request_delay",
    "request_delay": "request_delay",
    "survey-content": "survey_content",
    "survey_content": "survey_content",
}

# argparse destinations that may be set from config.json.
CONFIG_ARG_DESTS: frozenset[str] = frozenset(
    {
        "site",
        "public_url",
        "output",
        "since",
        "until",
        "limit",
        "committee_ids",
        "public_only",
        "private_only",
        "login_url",
        "username",
        "cookies_file",
        "headed_login",
        "pdf_engine",
        "request_delay",
        "verbose",
        "survey_content",
    }
)

HEADERS = {
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "en-US,en;q=0.9",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "x-requested-with": "XMLHttpRequest",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
}


@dataclass
class Committee:
    committee_id: str
    name: str


@dataclass
class Attachment:
    unique: str
    href: str
    name: str
    size: str = ""


@dataclass
class SavedAttachment:
    """Downloaded file plus metadata for bookmarks and link remapping."""

    bookmark: str
    blob: bytes
    resolved_url: str
    href: str
    file_unique: str
    item_unique: str = ""


@dataclass
class AgendaItem:
    unique: str
    order: str
    title: str
    has_attachment: bool
    attachments: list[Attachment] = field(default_factory=list)
    content_section: str = "other"
    category_name: str = ""


@dataclass
class Meeting:
    unique: str
    name: str
    numberdate: str
    unid: str

    @property
    def iso_date(self) -> str:
        d = self.numberdate
        return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"


class BoardDocsClient:
    def __init__(self, site: str, session: requests.Session | None = None) -> None:
        self.site = site.strip("/")
        self.base_url = f"https://go.boarddocs.com/{self.site}/Board.nsf"
        self.session = session or requests.Session()
        self.session.headers.update(HEADERS)

    def post_raw(self, endpoint: str, data: str) -> requests.Response:
        url = f"{self.base_url}/{endpoint}"
        if not endpoint.endswith("?open"):
            url += "?open"
        return self.session.post(url, data=data, timeout=120)

    def post(self, endpoint: str, data: str) -> str:
        resp = self.post_raw(endpoint, data)
        resp.raise_for_status()
        return resp.text

    def get_bytes(self, url: str) -> bytes:
        url = resolve_attachment_url(url, self.base_url)
        resp = self.session.get(url, timeout=120)
        resp.raise_for_status()
        return resp.content

    def discover_committees(self, page_url: str | None = None) -> list[Committee]:
        """Parse committee list from a BoardDocs landing page (Public or Private)."""
        page_url = page_url or f"{self.base_url}/Public"
        html_text = self.session.get(page_url, timeout=120).text
        committees: list[Committee] = []
        seen: set[str] = set()
        for m in re.finditer(
            r'committee-trigger[^>]*committeeid="([^"]+)"[^>]*aria-label="([^"]+)"',
            html_text,
            flags=re.I,
        ):
            cid, name = m.group(1), html.unescape(m.group(2).strip())
            if cid not in seen:
                seen.add(cid)
                committees.append(Committee(cid, name))
        if committees:
            return committees

        # Fallback: committee ids embedded in page without labels
        for cid in sorted(set(re.findall(r'committeeid="([A-Z0-9]{10,15})"', html_text, re.I))):
            if cid not in seen:
                seen.add(cid)
                committees.append(Committee(cid, cid))
        return committees

    def list_meetings(self, committee_id: str) -> list[Meeting]:
        raw = self.post("BD-GetMeetingsList", f"current_committee_id={committee_id}")
        data = json.loads(raw)
        meetings: list[Meeting] = []
        for row in data:
            if not row.get("numberdate"):
                continue
            meetings.append(
                Meeting(
                    unique=row["unique"],
                    name=row.get("name", "").strip(),
                    numberdate=row["numberdate"],
                    unid=row.get("unid", ""),
                )
            )
        return meetings

    def fetch_print_agenda_html(self, meeting_id: str, committee_id: str) -> str:
        return self.post(
            "PRINT-AgendaDetailed",
            f"id={meeting_id}&current_committee_id={committee_id}",
        )

    def fetch_agenda_items(self, meeting_id: str, committee_id: str) -> list[AgendaItem]:
        agenda_html = self.post(
            "BD-GetAgenda",
            f"id={meeting_id}&current_committee_id={committee_id}",
        )
        return parse_agenda_items(agenda_html)

    def fetch_item_attachments(
        self,
        item_id: str,
        committee_id: str,
        *,
        private: bool,
    ) -> list[Attachment]:
        endpoints = PRIVATE_FILE_ENDPOINTS if private else ("BD-GetPublicFiles",)
        return fetch_attachments_from_endpoints(
            self, item_id, committee_id, endpoints=endpoints
        )


def classify_content_section(category_name: str) -> str:
    lower = category_name.lower()
    for marker, section in CONTENT_SECTION_MARKERS:
        if marker in lower:
            return section
    return "other"


def fetch_attachments_from_endpoints(
    client: BoardDocsClient,
    item_id: str,
    committee_id: str,
    *,
    endpoints: Iterable[str],
) -> list[Attachment]:
    """Query one or more BoardDocs file endpoints and merge unique attachments."""
    post_data = f"id={item_id}&current_committee_id={committee_id}"
    attachments: list[Attachment] = []
    seen: set[str] = set()
    for endpoint in endpoints:
        resp = client.post_raw(endpoint, post_data)
        if resp.status_code != 200:
            continue
        for att in parse_file_links_from_html(resp.text):
            if att.unique not in seen:
                seen.add(att.unique)
                attachments.append(att)
    return attachments


def probe_file_endpoints(
    client: BoardDocsClient,
    item_id: str,
    committee_id: str,
    *,
    endpoints: Iterable[str] = SURVEY_FILE_ENDPOINTS,
) -> list[dict[str, object]]:
    """Probe BoardDocs file endpoints for discovery reports."""
    post_data = f"id={item_id}&current_committee_id={committee_id}"
    results: list[dict[str, object]] = []
    for endpoint in endpoints:
        resp = client.post_raw(endpoint, post_data)
        parsed = parse_file_links_from_html(resp.text) if resp.status_code == 200 else []
        results.append(
            {
                "endpoint": endpoint,
                "status": resp.status_code,
                "body_len": len(resp.text),
                "parsed_files": len(parsed),
                "file_names": [a.name for a in parsed[:5]],
            }
        )
    return results


def parse_public_files_html(files_html: str, class_name: str = "public-file") -> list[Attachment]:
    attachments: list[Attachment] = []
    file_re = re.compile(
        rf'class="{re.escape(class_name)}"[^>]*unique="([^"]+)"[^>]*href="([^"]+)"[^>]*>([^<]*)</a>',
        re.I,
    )
    for m in file_re.finditer(files_html):
        raw_name = html.unescape(m.group(3).strip())
        size_match = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", raw_name)
        attachments.append(
            Attachment(
                unique=m.group(1),
                href=m.group(2),
                name=size_match.group(1).strip() if size_match else raw_name,
                size=size_match.group(2).strip() if size_match else "",
            )
        )
    return attachments


def parse_file_links_from_html(fragment: str) -> list[Attachment]:
    """Collect downloadable file links from BoardDocs HTML fragments."""
    attachments: list[Attachment] = []
    seen: set[str] = set()
    for class_name in FILE_LINK_CLASSES:
        for att in parse_public_files_html(fragment, class_name=class_name):
            if att.unique not in seen:
                seen.add(att.unique)
                attachments.append(att)
    anchor_re = re.compile(
        r'<a[^>]*class="([^"]*file[^"]*)"[^>]*(?:unique="([^"]+)"[^>]*href="([^"]+)"'
        r'|href="([^"]+)"[^>]*unique="([^"]+)")[^>]*>([^<]*)</a>',
        re.I,
    )
    for m in anchor_re.finditer(fragment):
        if m.group(2):
            unique, href, raw_name = m.group(2), m.group(3), m.group(6)
        else:
            href, unique, raw_name = m.group(4), m.group(5), m.group(6)
        unique = unique.upper()
        if unique in seen:
            continue
        seen.add(unique)
        raw_name = html.unescape((raw_name or "").strip())
        size_match = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", raw_name)
        attachments.append(
            Attachment(
                unique=unique,
                href=href,
                name=size_match.group(1).strip() if size_match else raw_name,
                size=size_match.group(2).strip() if size_match else "",
            )
        )
    for m in re.finditer(
        r'<a[^>]*href="([^"]*/files/([A-Z0-9]{10,15})[^"]*)"[^>]*>([^<]*)</a>',
        fragment,
        re.I,
    ):
        unique = m.group(2).upper()
        if unique in seen:
            continue
        seen.add(unique)
        raw_name = html.unescape(m.group(3).strip())
        size_match = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", raw_name)
        attachments.append(
            Attachment(
                unique=unique,
                href=m.group(1),
                name=size_match.group(1).strip() if size_match else raw_name,
                size=size_match.group(2).strip() if size_match else "",
            )
        )
    return attachments


def parse_agenda_categories(agenda_html: str) -> list[tuple[int, str, str]]:
    """Return (position, category_unique, display_name) for each agenda category."""
    categories: list[tuple[int, str, str]] = []
    cat_re = re.compile(
        r'class="category[^"]*"[^>]*unique="([^"]+)"[^>]*>([\s\S]*?)</li>',
        re.I,
    )
    for m in cat_re.finditer(agenda_html):
        spans = re.findall(r"<span[^>]*>([^<]*)</span>", m.group(2))
        name = spans[1].strip() if len(spans) > 1 else ""
        categories.append((m.start(), m.group(1), name))
    return categories


def parse_agenda_items(agenda_html: str) -> list[AgendaItem]:
    items: list[AgendaItem] = []
    categories = parse_agenda_categories(agenda_html)
    item_re = re.compile(
        r'class="[^"]*item[^"]*"[^>]*id="([^"]+)"[^>]*unique="([^"]+)"'
        r'[^>]*Xtitle="([^"]*)"[^>]*>([\s\S]*?)</li>',
        re.I,
    )
    for m in item_re.finditer(agenda_html):
        body = m.group(4)
        order_match = re.search(r"<span[^>]*>([^<]*)</span>", body)
        order = order_match.group(1).strip() if order_match else ""
        inline_attachments = parse_file_links_from_html(body)
        has_file_icon = "fa-file-text-o" in body
        category_name = ""
        content_section = "other"
        for pos, _cat_id, cat_name in categories:
            if pos < m.start():
                category_name = cat_name
                content_section = classify_content_section(cat_name)
            else:
                break
        items.append(
            AgendaItem(
                unique=m.group(2),
                order=order,
                title=html.unescape(m.group(3)),
                has_attachment=bool(inline_attachments) or has_file_icon,
                attachments=inline_attachments,
                content_section=content_section,
                category_name=category_name,
            )
        )
    return items


def summarize_agenda_sections(items: list[AgendaItem]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for item in items:
        bucket = summary.setdefault(
            item.content_section,
            {"items": 0, "with_icon": 0, "with_inline_files": 0},
        )
        bucket["items"] += 1
        if item.has_attachment:
            bucket["with_icon"] += 1
        if item.attachments:
            bucket["with_inline_files"] += 1
    return summary


def run_content_survey(
    client: BoardDocsClient,
    committee: Committee,
    *,
    limit_meetings: int = 1,
    request_delay_sec: float = REQUEST_DELAY_SEC,
) -> dict[str, object]:
    """
    Survey how BoardDocs exposes Public / Administrative / Executive content
    and which file endpoints return attachments for each section.
    """
    meetings = client.list_meetings(committee.committee_id)
    meetings.sort(key=lambda m: m.numberdate, reverse=True)
    meetings = meetings[:limit_meetings]
    report: dict[str, object] = {
        "committee_id": committee.committee_id,
        "committee_name": committee.name,
        "meetings": [],
    }

    for meeting in meetings:
        if request_delay_sec > 0:
            time.sleep(request_delay_sec)
        agenda_html = client.post(
            "BD-GetAgenda",
            f"id={meeting.unique}&current_committee_id={committee.committee_id}",
        )
        if request_delay_sec > 0:
            time.sleep(request_delay_sec)
        print_html = client.fetch_print_agenda_html(
            meeting.unique, committee.committee_id
        )
        items = parse_agenda_items(agenda_html)
        print_files = parse_file_links_from_html(print_html)
        meeting_report: dict[str, object] = {
            "meeting_id": meeting.unique,
            "meeting_date": meeting.iso_date,
            "meeting_name": meeting.name,
            "section_summary": summarize_agenda_sections(items),
            "print_agenda_file_count": len(print_files),
            "category_names": [name for _pos, _uid, name in parse_agenda_categories(agenda_html)],
            "section_samples": {},
        }

        by_section: dict[str, list[AgendaItem]] = {}
        for item in items:
            by_section.setdefault(item.content_section, []).append(item)

        for section, section_items in by_section.items():
            candidates = [
                i
                for i in section_items
                if i.attachments or i.has_attachment
            ][:3]
            samples: list[dict[str, object]] = []
            for item in candidates:
                if request_delay_sec > 0:
                    time.sleep(request_delay_sec)
                probes = probe_file_endpoints(
                    client, item.unique, committee.committee_id
                )
                merged = fetch_attachments_from_endpoints(
                    client,
                    item.unique,
                    committee.committee_id,
                    endpoints=PRIVATE_FILE_ENDPOINTS,
                )
                samples.append(
                    {
                        "item_id": item.unique,
                        "title": item.title[:120],
                        "category": item.category_name,
                        "inline_file_count": len(item.attachments),
                        "merged_private_fetch_count": len(merged),
                        "endpoint_probes": probes,
                    }
                )
            meeting_report["section_samples"][section] = samples

        report["meetings"].append(meeting_report)
        LOG.info(
            "Survey %s %s: sections=%s print_files=%d",
            meeting.iso_date,
            meeting.name[:50],
            meeting_report["section_summary"],
            len(print_files),
        )

    return report


def resolve_attachment_url(href: str, base_url: str) -> str:
    """
    BoardDocs returns attachment paths like /pa/phoe/Board.nsf/files/ID/$file/name.pdf.
    Do not pass these through urljoin(base_url, href.lstrip('/')) — that duplicates the path.
    """
    href = href.strip()
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("/"):
        return f"https://go.boarddocs.com{href}"
    return f"{base_url.rstrip('/')}/{href.lstrip('/')}"


def sanitize_path_component(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "-", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    return cleaned or "unknown"


def district_id_from_site(site: str) -> str:
    return site.replace("/", "-")


def is_boarddocs_url(url: str, site: str) -> bool:
    lower = url.lower()
    if "boarddocs.com" in lower:
        return True
    if "board.nsf" in lower:
        return True
    return f"/{site.strip('/')}/" in lower


def normalize_link_uri(uri: str, base_url: str) -> str:
    uri = unquote(uri.strip())
    if uri.startswith("//"):
        uri = "https:" + uri
    elif uri.startswith("/"):
        uri = f"https://go.boarddocs.com{uri}"
    elif not uri.startswith("http"):
        uri = resolve_attachment_url(uri, base_url)
    return uri.split("#")[0].rstrip("/").lower()


def extract_boarddocs_document_id(url: str) -> str | None:
    """File unique from /files/ID/ or agenda/item id from ?id=."""
    m = re.search(r"[?&]id=([^&#]+)", url, re.I)
    if m:
        return m.group(1)
    m = re.search(r"/files/([^/]+)/", url, re.I)
    if m:
        return m.group(1)
    return None


def unique_bookmark_name(filename: str, file_unique: str, used: set[str]) -> str:
    base = sanitize_path_component(filename) or file_unique
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base} ({file_unique[:6]})" if suffix == 2 else f"{base} ({suffix})"
        suffix += 1
    used.add(candidate)
    return candidate


def url_lookup_keys(
    resolved_url: str,
    href: str,
    file_unique: str,
    base_url: str,
    site: str,
) -> set[str]:
    keys: set[str] = set()
    for raw in (resolved_url, href):
        if not raw:
            continue
        norm = normalize_link_uri(raw, base_url)
        keys.add(norm)
        path = urlparse(norm).path.lower()
        keys.add(path)
        if "/board.nsf" in path:
            keys.add(path[path.index("/board.nsf") :])
    if file_unique:
        keys.add(file_unique.lower())
        keys.add(file_unique.upper())
    site_slug = site.strip("/").lower()
    if site_slug and file_unique:
        keys.add(f"/{site_slug}/board.nsf/files/{file_unique.lower()}")
    return keys


def build_url_page_lookup(
    page_by_bookmark: dict[str, int],
    saved: list[SavedAttachment],
    base_url: str,
    site: str,
) -> dict[str, int]:
    """Map URL/id keys to 0-based PDF page numbers where attachments start."""
    lookup: dict[str, int] = {}
    for att in saved:
        page = page_by_bookmark.get(att.bookmark)
        if page is None:
            continue
        for key in url_lookup_keys(
            att.resolved_url, att.href, att.file_unique, base_url, site
        ):
            lookup[key] = page
        if att.item_unique:
            for item_key in (
                att.item_unique.lower(),
                att.item_unique.upper(),
                att.item_unique,
            ):
                lookup[item_key] = page
    return lookup


def find_link_target_page(
    uri: str,
    lookup: dict[str, int],
    base_url: str,
    site: str,
) -> int | None:
    if not is_boarddocs_url(uri, site):
        return None
    norm = normalize_link_uri(uri, base_url)
    if norm in lookup:
        return lookup[norm]
    path = urlparse(norm).path.lower()
    if path in lookup:
        return lookup[path]
    if "/board.nsf" in path:
        suffix = path[path.index("/board.nsf") :]
        if suffix in lookup:
            return lookup[suffix]
    doc_id = extract_boarddocs_document_id(uri)
    if doc_id:
        for key in (doc_id, doc_id.lower(), doc_id.upper()):
            if key in lookup:
                return lookup[key]
    for key, page in lookup.items():
        if len(key) >= 10 and key in norm:
            return page
    return None


def annotate_boarddocs_links_in_html(
    agenda_html: str,
    base_url: str,
    site: str,
    saved: list[SavedAttachment],
) -> str:
    """
    Update agenda HTML so BoardDocs links are labeled as in-document attachments.
    External href values are kept so the PDF renderer emits URIs we can rewrite.
    """
    if not saved:
        return agenda_html

    bookmark_by_id: dict[str, str] = {}
    for att in saved:
        bookmark_by_id[att.file_unique.lower()] = att.bookmark
        if att.item_unique:
            bookmark_by_id[att.item_unique.lower()] = att.bookmark

    soup = BeautifulSoup(agenda_html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith("#") or href.lower().startswith("mailto:"):
            continue
        if not is_boarddocs_url(href, site) and not is_boarddocs_url(
            normalize_link_uri(href, base_url), site
        ):
            continue
        doc_id = extract_boarddocs_document_id(
            normalize_link_uri(href, base_url)
        )
        bookmark = bookmark_by_id.get((doc_id or "").lower())
        if bookmark:
            anchor["title"] = f"Attachment in this PDF: {bookmark}"
            anchor["data-boarddocs-bookmark"] = bookmark

    return str(soup)


def remap_boarddocs_uri_links_in_pdf(
    doc: fitz.Document,
    saved: list[SavedAttachment],
    page_by_bookmark: dict[str, int],
    base_url: str,
    site: str,
) -> int:
    """Replace BoardDocs http(s) link annotations with jumps to attachment pages."""
    lookup = build_url_page_lookup(page_by_bookmark, saved, base_url, site)
    if not lookup:
        return 0

    changed = 0
    for pno in range(doc.page_count):
        page = doc[pno]
        for link in list(page.get_links()):
            uri = link.get("uri")
            if not uri:
                continue
            target_page = find_link_target_page(uri, lookup, base_url, site)
            if target_page is None:
                LOG.debug("No internal target for BoardDocs link: %s", uri)
                continue
            rect = link["from"]
            page.delete_link(link)
            page.insert_link(
                {
                    "kind": fitz.LINK_GOTO,
                    "from": rect,
                    "page": target_page,
                    "to": fitz.Point(0, 0),
                }
            )
            changed += 1
    return changed


def prepare_agenda_html(
    agenda_html: str,
    base_url: str,
    *,
    site: str = "",
    saved_attachments: list[SavedAttachment] | None = None,
) -> str:
    """Normalize BoardDocs print HTML for PDF rendering."""
    if saved_attachments and site:
        agenda_html = annotate_boarddocs_links_in_html(
            agenda_html, base_url, site, saved_attachments
        )

    soup = BeautifulSoup(agenda_html, "html.parser")
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()

    body_html = soup.body.decode_contents() if soup.body else agenda_html
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<base href="{base_url}/">
<style>
  body {{ font-family: Arial, Helvetica, sans-serif; font-size: 11pt; margin: 24px; }}
  .print-meeting-date, .print-meeting-name {{ font-weight: bold; text-align: center; }}
  .category, .wrap-category {{ font-weight: bold; margin-top: 1em; }}
  .item {{ margin: 0.4em 0; }}
  a {{ color: #0645ad; word-break: break-word; }}
</style></head><body>{body_html}</body></html>"""


def html_to_pdf_story(html_doc: str) -> bytes:
    """Render HTML to PDF via PyMuPDF Story (does not use fitz.open(html))."""
    story = fitz.Story(html=html_doc)
    buffer = io.BytesIO()
    writer = fitz.DocumentWriter(buffer)
    mediabox = fitz.paper_rect("letter")
    margin = 36
    content_rect = mediabox + (margin, margin, -margin, -margin)

    more = True
    while more:
        device = writer.begin_page(mediabox)
        more, _filled = story.place(content_rect)
        story.draw(device)
        writer.end_page()
    writer.close()

    pdf_bytes = buffer.getvalue()
    if not pdf_bytes:
        raise RuntimeError("Story PDF writer produced empty output")
    return pdf_bytes


def html_to_pdf_playwright(html_doc: str) -> bytes:
    """Render HTML to PDF via headless Chromium (most reliable on Windows)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(html_doc, wait_until="load", timeout=120_000)
            return page.pdf(
                format="Letter",
                margin={
                    "top": "0.5in",
                    "bottom": "0.5in",
                    "left": "0.5in",
                    "right": "0.5in",
                },
                print_background=True,
            )
        finally:
            browser.close()


def validate_pdf_bytes(pdf_bytes: bytes) -> bytes:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if doc.page_count < 1:
            raise RuntimeError("Generated PDF has no pages")
    finally:
        doc.close()
    return pdf_bytes


def html_to_pdf_bytes(
    agenda_html: str,
    base_url: str,
    *,
    engine: str = "auto",
    site: str = "",
    saved_attachments: list[SavedAttachment] | None = None,
) -> bytes:
    """
    Convert BoardDocs agenda HTML to PDF bytes.

    engine: auto | story | playwright
      auto       — try Story, then Playwright
      story      — PyMuPDF Story only
      playwright — Chromium print (recommended if Story fails)
    """
    html_doc = prepare_agenda_html(
        agenda_html,
        base_url,
        site=site,
        saved_attachments=saved_attachments,
    )
    if engine == "auto":
        # fitz.open(html) is broken on Windows; Story can fail on large agendas too.
        if platform.system() == "Windows":
            engines = ("playwright", "story")
        else:
            engines = ("story", "playwright")
    else:
        engines = (engine,)

    errors: list[str] = []
    for eng in engines:
        try:
            if eng == "story":
                pdf_bytes = html_to_pdf_story(html_doc)
            elif eng == "playwright":
                pdf_bytes = html_to_pdf_playwright(html_doc)
            else:
                raise ValueError(f"Unknown PDF engine: {eng}")
            return validate_pdf_bytes(pdf_bytes)
        except Exception as exc:
            errors.append(f"{eng}: {exc}")
            LOG.warning("Agenda PDF engine %s failed: %s", eng, exc)

    raise RuntimeError(
        "Could not render agenda HTML to PDF. Tried: "
        + "; ".join(errors)
        + ". Use --pdf-engine playwright if Playwright is installed."
    )


def append_pdf_pages(
    target: fitz.Document,
    source_bytes: bytes,
    *,
    bookmark_title: str | None = None,
) -> None:
    start = target.page_count
    src = fitz.open(stream=source_bytes, filetype="pdf")
    target.insert_pdf(src)
    src.close()
    if bookmark_title and target.page_count > start:
        target.set_toc(target.get_toc() + [[1, bookmark_title, start + 1]])


def embed_file_portfolio(doc: fitz.Document, filename: str, file_bytes: bytes) -> None:
    doc.embfile_add(filename, file_bytes)


def build_nested_agenda_pdf(
    agenda_pdf: bytes,
    saved: list[SavedAttachment],
    *,
    base_url: str,
    site: str,
) -> bytes:
    doc = fitz.open(stream=agenda_pdf, filetype="pdf")
    page_by_bookmark: dict[str, int] = {}
    doc.set_toc([[1, "Agenda", 1]])

    for att in saved:
        lower = att.bookmark.lower()
        if lower.endswith(".pdf"):
            try:
                start = doc.page_count
                append_pdf_pages(doc, att.blob, bookmark_title=att.bookmark)
                if doc.page_count > start:
                    page_by_bookmark[att.bookmark] = start
            except Exception:
                LOG.warning("Could not merge PDF attachment %s", att.bookmark)
                embed_file_portfolio(doc, att.bookmark, att.blob)
        else:
            embed_file_portfolio(doc, att.bookmark, att.blob)

    remapped = remap_boarddocs_uri_links_in_pdf(
        doc, saved, page_by_bookmark, base_url, site
    )
    LOG.info("    remapped %d BoardDocs link(s) to attachment bookmarks", remapped)

    out = doc.tobytes(deflate=True)
    doc.close()
    return out


def resolve_login_url(url: str) -> str:
    """BoardDocs credentials are submitted at Board.nsf/Private?open&login."""
    url = url.strip()
    if re.search(r"[?&]login", url, re.I):
        return url
    base = url.rstrip("/")
    if base.endswith("/Public"):
        base = base[: -len("/Public")]
    if "/Board.nsf" in base:
        base = base.split("/Board.nsf", 1)[0] + "/Board.nsf"
    return f"{base}/Private?open&login"


def login_with_playwright(
    login_url: str,
    username: str,
    password: str,
    *,
    headless: bool = True,
) -> requests.Session:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "Playwright is required for private export. "
            "Install with: pip install playwright && playwright install chromium"
        ) from exc

    session = requests.Session()
    session.headers.update(HEADERS)
    resolved_login_url = resolve_login_url(login_url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=HEADERS["user-agent"],
            extra_http_headers={"accept-language": HEADERS["accept-language"]},
        )
        page = context.new_page()
        page.goto(resolved_login_url, wait_until="networkidle", timeout=120_000)

        user_filled = False
        for user_sel in ("#username", "#Username", 'input[name="Username"]'):
            loc = page.locator(user_sel).first
            if loc.count() and loc.is_visible():
                loc.fill(username)
                user_filled = True
                break
        if not user_filled:
            LOG.warning("Could not find visible username field at %s", resolved_login_url)

        pass_loc = page.locator(
            '#password, #Password, input[name="Password"], input[type="password"]'
        ).first
        if pass_loc.count() and pass_loc.is_visible():
            pass_loc.fill(password)
            pass_loc.press("Enter")
        else:
            LOG.warning("Could not find visible password field at %s", resolved_login_url)

        page.wait_for_load_state("networkidle", timeout=120_000)
        final_url = page.url
        cookies = context.cookies()
        browser.close()

    for cookie in cookies:
        session.cookies.set(
            cookie["name"],
            cookie["value"],
            domain=cookie.get("domain"),
            path=cookie.get("path", "/"),
        )
    if not cookies:
        LOG.warning(
            "Playwright login captured no cookies (final URL: %s). "
            "Private-only documents may be missing.",
            final_url,
        )
    return session


def export_scope(
    client: BoardDocsClient,
    *,
    committees: list[Committee],
    output_root: Path,
    visibility: str,
    since: str | None,
    until: str | None,
    limit_per_committee: int | None,
    private: bool,
    pdf_engine: str = "auto",
    request_delay_sec: float = REQUEST_DELAY_SEC,
) -> int:
    written = 0
    district = district_id_from_site(client.site)
    vis_dir = output_root / district / visibility

    for committee in committees:
        LOG.info("Committee: %s (%s)", committee.name, committee.committee_id)
        meetings = client.list_meetings(committee.committee_id)
        meetings.sort(key=lambda m: m.numberdate, reverse=True)

        if since:
            meetings = [m for m in meetings if m.numberdate >= since.replace("-", "")]
        if until:
            meetings = [m for m in meetings if m.numberdate <= until.replace("-", "")]
        if limit_per_committee:
            meetings = meetings[:limit_per_committee]

        committee_dir = vis_dir / sanitize_path_component(committee.name)
        committee_dir.mkdir(parents=True, exist_ok=True)

        for meeting in meetings:
            out_path = committee_dir / f"{meeting.iso_date}-Agenda.pdf"
            if out_path.exists():
                LOG.info("  skip existing %s", out_path.name)
                continue

            LOG.info("  %s — %s", meeting.iso_date, meeting.name[:80])
            time.sleep(request_delay_sec)

            try:
                agenda_html = client.fetch_print_agenda_html(
                    meeting.unique, committee.committee_id
                )

                items = client.fetch_agenda_items(meeting.unique, committee.committee_id)
                print_files = parse_file_links_from_html(agenda_html)
                meeting_api_files = client.fetch_item_attachments(
                    meeting.unique,
                    committee.committee_id,
                    private=private,
                )
                icon_items = [i for i in items if i.has_attachment]
                if private:
                    section_summary = summarize_agenda_sections(items)
                    if any(k in section_summary for k in ("public", "administrative", "executive")):
                        LOG.info("    content sections: %s", section_summary)
                    LOG.info(
                        "    files: print_agenda=%d meeting_api=%d items_with_icon=%d",
                        len(print_files),
                        len(meeting_api_files),
                        len(icon_items),
                    )

                saved_attachments: list[SavedAttachment] = []
                bookmark_names_used: set[str] = set()
                downloaded_file_uniques: set[str] = set()

                def save_attachment_list(
                    file_list: Iterable[Attachment],
                    *,
                    item_unique: str = "",
                ) -> None:
                    for att in file_list:
                        if att.unique in downloaded_file_uniques:
                            continue
                        href = resolve_attachment_url(att.href, client.base_url)
                        blob = client.get_bytes(href)
                        if not blob:
                            raise RuntimeError(
                                f"Empty download for attachment {att.name!r} ({href})"
                            )
                        bookmark = unique_bookmark_name(
                            att.name, att.unique, bookmark_names_used
                        )
                        saved_attachments.append(
                            SavedAttachment(
                                bookmark=bookmark,
                                blob=blob,
                                resolved_url=href,
                                href=att.href,
                                file_unique=att.unique,
                                item_unique=item_unique,
                            )
                        )
                        downloaded_file_uniques.add(att.unique)

                save_attachment_list(print_files)
                save_attachment_list(meeting_api_files, item_unique=meeting.unique)

                for item in icon_items:
                    time.sleep(request_delay_sec)
                    files = client.fetch_item_attachments(
                        item.unique,
                        committee.committee_id,
                        private=private,
                    )
                    if not files:
                        files = item.attachments
                    if not files:
                        LOG.warning(
                            "Skipping agenda item %s (%s) [%s]: attachment icon present "
                            "but BoardDocs returned no downloadable files",
                            item.order or "?",
                            item.title[:80],
                            item.content_section,
                        )
                        continue
                    save_attachment_list(files, item_unique=item.unique)

                agenda_pdf = html_to_pdf_bytes(
                    agenda_html,
                    client.base_url,
                    engine=pdf_engine,
                    site=client.site,
                    saved_attachments=saved_attachments,
                )

                final_pdf = build_nested_agenda_pdf(
                    agenda_pdf,
                    saved_attachments,
                    base_url=client.base_url,
                    site=client.site,
                )
                out_path.write_bytes(final_pdf)
                written += 1
                LOG.info(
                    "    wrote %s (%d attachments)",
                    out_path,
                    len(saved_attachments),
                )
            except Exception:
                LOG.exception("    failed %s", meeting.unique)

    return written


def find_default_config() -> Path | None:
    path = Path(DEFAULT_CONFIG_NAME)
    return path if path.is_file() else None


def preparse_config_path(argv: list[str] | None) -> Path | None:
    """Resolve config path from argv (--config) or config.json in the cwd."""
    if argv is None:
        return find_default_config()
    for i, arg in enumerate(argv):
        if arg == "--config" and i + 1 < len(argv):
            return Path(argv[i + 1])
        if arg.startswith("--config="):
            return Path(arg.split("=", 1)[1])
    return find_default_config()


def normalize_config(data: dict[str, object]) -> dict[str, object]:
    """Map config.json keys to argparse destination names."""
    out: dict[str, object] = {}
    for key, value in data.items():
        if key == "committees":
            continue
        dest = CONFIG_KEY_ALIASES.get(key, key)
        if dest in CONFIG_ARG_DESTS:
            out[dest] = value

    committees = data.get("committees")
    if "committee_ids" not in out and committees is not None:
        if isinstance(committees, dict):
            out["committee_ids"] = list(committees.values())
        elif isinstance(committees, list):
            out["committee_ids"] = committees
        else:
            raise ValueError('"committees" must be an object or array of committee IDs')

    return out


def load_config_file(path: Path) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in config file {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Config file must contain a JSON object: {path}")
    return normalize_config(raw)


def config_defaults_for_argparse(path: Path) -> dict[str, object]:
    defaults = load_config_file(path)
    return {k: v for k, v in defaults.items() if v is not None}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    config_path = preparse_config_path(argv)
    config_defaults: dict[str, object] = {}
    if config_path is not None:
        if not config_path.is_file():
            raise SystemExit(f"Config file not found: {config_path}")
        try:
            config_defaults = config_defaults_for_argparse(config_path)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        config_defaults["config"] = config_path

    parser = argparse.ArgumentParser(
        description="Export BoardDocs agendas and attachments to nested PDFs."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=config_path,
        help=(
            f"JSON settings file (default: ./{DEFAULT_CONFIG_NAME} when present). "
            "CLI flags override config values."
        ),
    )
    parser.add_argument(
        "--site",
        default=DEFAULT_SITE,
        help="BoardDocs site path, e.g. pa/phoe (default: %(default)s)",
    )
    parser.add_argument(
        "--public-url",
        default=DEFAULT_PUBLIC_URL,
        help="Public landing page URL (default: %(default)s)",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help="Output directory (default: %(default)s)",
    )
    parser.add_argument(
        "--since",
        help="Earliest meeting date YYYYMMDD or YYYY-MM-DD",
    )
    parser.add_argument(
        "--until",
        help="Latest meeting date YYYYMMDD or YYYY-MM-DD",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Max meetings per committee (newest first)",
    )
    parser.add_argument(
        "--committee-id",
        action="append",
        dest="committee_ids",
        help="Only export these committee IDs (repeatable)",
    )
    parser.add_argument(
        "--public-only",
        action="store_true",
        help="Skip private/login export",
    )
    parser.add_argument(
        "--private-only",
        action="store_true",
        help="Skip public export",
    )
    parser.add_argument(
        "--login-url",
        help="BoardDocs login URL (required for private export unless --cookies-file is set)",
    )
    parser.add_argument(
        "--username",
        help="BoardDocs username (login is prompted when private export runs)",
    )
    parser.add_argument(
        "--cookies-file",
        help="JSON file with cookies from a logged-in browser session",
    )
    parser.add_argument(
        "--headed-login",
        action="store_true",
        help="Show browser during Playwright login",
    )
    parser.add_argument(
        "--pdf-engine",
        choices=("auto", "story", "playwright"),
        default="auto",
        help=(
            "How to render agenda HTML to PDF (default: auto). "
            "Use playwright if you see AssertionError from PyMuPDF."
        ),
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=REQUEST_DELAY_SEC,
        metavar="SECONDS",
        help=(
            "Seconds to wait between BoardDocs API requests (default: %(default)s). "
            "Increase if the server rate-limits you; use 0 to disable."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument(
        "--survey-content",
        action="store_true",
        help=(
            "Discover Public/Administrative/Executive content sections and probe "
            "file endpoints (requires login; writes JSON under output/discovery/)"
        ),
    )
    if config_defaults:
        parser.set_defaults(**config_defaults)
    return parser.parse_args(argv)


def prompt_login_secret(username: str) -> str:
    """Prompt interactively for the BoardDocs login credential."""
    secret = getpass.getpass(f"BoardDocs login for {username}: ")
    if not secret:
        raise ValueError("Login is required for private export")
    return secret


def build_private_session(args: argparse.Namespace) -> requests.Session:
    if args.cookies_file:
        return load_cookies_file(Path(args.cookies_file))
    if args.username:
        login_url = resolve_login_url(
            args.login_url or args.public_url.replace("/Public", "")
        )
        LOG.info("Logging in at %s", login_url)
        return login_with_playwright(
            login_url,
            args.username,
            prompt_login_secret(args.username),
            headless=not args.headed_login,
        )
    raise ValueError(
        "Private access requires --username or --cookies-file"
    )


def load_cookies_file(path: Path) -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    data = json.loads(path.read_text(encoding="utf-8"))
    for cookie in data:
        session.cookies.set(
            cookie["name"],
            cookie["value"],
            domain=cookie.get("domain"),
            path=cookie.get("path", "/"),
        )
    return session


def merge_committees(*groups: list[Committee]) -> list[Committee]:
    """Combine committee lists; prefer a human-readable name over a bare ID."""
    merged: dict[str, Committee] = {}
    for group in groups:
        for committee in group:
            key = committee.committee_id.upper()
            prev = merged.get(key)
            if prev is None:
                merged[key] = committee
            elif prev.name == prev.committee_id and committee.name != committee.committee_id:
                merged[key] = committee
    return list(merged.values())


def filter_committees(all_committees: list[Committee], ids: list[str] | None) -> list[Committee]:
    if not ids:
        return all_committees
    wanted = {i.upper() for i in ids}
    return [c for c in all_committees if c.committee_id.upper() in wanted]


def has_private_credentials(args: argparse.Namespace) -> bool:
    return bool(args.username or args.cookies_file)


def apply_public_only_default(args: argparse.Namespace) -> None:
    """Export public agendas only when no login is configured (unless --private-only)."""
    if args.public_only or args.private_only:
        return
    if has_private_credentials(args):
        return
    LOG.info(
        "No username or cookies file configured; exporting public agendas only "
        "(set username or --cookies-file, or use --private-only for logged-in export)"
    )
    args.public_only = True


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    apply_public_only_default(args)
    if args.config:
        LOG.info("Using config file %s", Path(args.config).resolve())

    output_root = Path(args.output).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    public_client = BoardDocsClient(args.site)
    committees: list[Committee] = []

    if not args.private_only:
        committees = public_client.discover_committees(args.public_url)
        if committees:
            LOG.info("Discovered %d committees from public view", len(committees))

    private_client: BoardDocsClient | None = None
    if not args.public_only:
        try:
            private_session = build_private_session(args)
        except ValueError as exc:
            LOG.error("%s", exc)
            return 1

        private_client = BoardDocsClient(args.site, session=private_session)
        private_url = f"{private_client.base_url}/Private"
        private_committees = private_client.discover_committees(private_url)
        if private_committees:
            LOG.info(
                "Discovered %d committees from private view", len(private_committees)
            )
        committees = merge_committees(committees, private_committees)

    committees = filter_committees(committees, args.committee_ids)

    if not committees and args.committee_ids:
        committees = [Committee(cid, cid) for cid in args.committee_ids]
        LOG.warning(
            "Requested committee ID(s) not listed on BoardDocs navigation; "
            "exporting by ID anyway: %s",
            ", ".join(args.committee_ids),
        )

    if not committees:
        sources = []
        if not args.private_only:
            sources.append(args.public_url)
        if not args.public_only:
            sources.append(f"{public_client.base_url}/Private (authenticated)")
        LOG.error("No committees discovered from %s", " or ".join(sources))
        return 1

    LOG.info("Using %d committee(s)", len(committees))

    if args.survey_content:
        if args.public_only or private_client is None:
            LOG.error("--survey-content requires private login (omit --public-only)")
            return 1
        discovery_dir = output_root / DISCOVERY_DIR
        discovery_dir.mkdir(parents=True, exist_ok=True)
        survey_limit = args.limit or 1
        for committee in committees:
            report = run_content_survey(
                private_client,
                committee,
                limit_meetings=survey_limit,
                request_delay_sec=args.request_delay,
            )
            district = district_id_from_site(args.site)
            slug = sanitize_path_component(committee.name)
            out_path = (
                discovery_dir
                / f"content-survey-{district}-{slug}-{committee.committee_id}.json"
            )
            out_path.write_text(
                json.dumps(report, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            LOG.info("Wrote content survey %s", out_path)
        return 0

    if args.request_delay < 0:
        LOG.error("--request-delay must be >= 0")
        return 1
    if args.request_delay > 0:
        LOG.info("Request delay: %.2f s between API calls", args.request_delay)
    else:
        LOG.info("Request delay disabled")

    total = 0

    if not args.private_only:
        total += export_scope(
            public_client,
            committees=committees,
            output_root=output_root,
            visibility="Public",
            since=args.since,
            until=args.until,
            limit_per_committee=args.limit,
            private=False,
            pdf_engine=args.pdf_engine,
            request_delay_sec=args.request_delay,
        )

    if not args.public_only:
        assert private_client is not None
        total += export_scope(
            private_client,
            committees=committees,
            output_root=output_root,
            visibility="Private",
            since=args.since,
            until=args.until,
            limit_per_committee=args.limit,
            private=True,
            pdf_engine=args.pdf_engine,
            request_delay_sec=args.request_delay,
        )

    LOG.info("Finished. Wrote %d agenda PDF(s) under %s", total, output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
