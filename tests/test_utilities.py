"""Tests for path, committee, CLI, and login helpers."""

from __future__ import annotations

import export_boarddocs as bd


def test_sanitize_path_component():
    assert bd.sanitize_path_component('Finance / "Personnel"') == "Finance - -Personnel-"
    assert bd.sanitize_path_component("   ") == "unknown"


def test_district_id_from_site():
    assert bd.district_id_from_site("pa/phoe") == "pa-phoe"


def test_unique_bookmark_name_avoids_collisions():
    used: set[str] = set()
    first = bd.unique_bookmark_name("Report.pdf", "FILE1111111111", used)
    second = bd.unique_bookmark_name("Report.pdf", "FILE222222222222", used)
    assert first == "Report.pdf"
    assert first != second
    assert "FILE222" in second or "(" in second


def test_resolve_login_url():
    assert bd.resolve_login_url(
        "https://go.boarddocs.com/pa/phoe/Board.nsf/Private?open&login"
    ).endswith("Private?open&login")

    public = "https://go.boarddocs.com/pa/phoe/Board.nsf/Public"
    resolved = bd.resolve_login_url(public)
    assert resolved.endswith("/Private?open&login")
    assert "/Public" not in resolved

    bare = "https://go.boarddocs.com/pa/phoe/Board.nsf"
    assert bd.resolve_login_url(bare).endswith("/Board.nsf/Private?open&login")


def test_merge_committees_prefers_human_name():
    bare = bd.Committee("ABC123", "ABC123")
    named = bd.Committee("ABC123", "Curriculum Committee")
    merged = bd.merge_committees([bare], [named])
    assert len(merged) == 1
    assert merged[0].name == "Curriculum Committee"

    # Named entry should not be replaced by bare ID
    merged2 = bd.merge_committees([named], [bare])
    assert merged2[0].name == "Curriculum Committee"


def test_filter_committees_case_insensitive():
    committees = [
        bd.Committee("abc111", "A"),
        bd.Committee("def222", "B"),
    ]
    filtered = bd.filter_committees(committees, ["ABC111"])
    assert len(filtered) == 1
    assert filtered[0].committee_id == "abc111"


def test_parse_args_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = bd.parse_args([])
    assert args.site == bd.DEFAULT_SITE
    assert args.output == bd.DEFAULT_OUTPUT
    assert args.pdf_engine == "auto"
    assert args.request_delay == bd.REQUEST_DELAY_SEC
    assert args.refresh_recent_days == bd.DEFAULT_REFRESH_RECENT_DAYS


def test_meeting_is_within_recent_days():
    today = bd.date(2026, 6, 16)
    recent = bd.Meeting("u1", "Board Meeting", "20260610", "id1")
    old = bd.Meeting("u2", "Board Meeting", "20260101", "id2")

    assert bd.meeting_is_within_recent_days(recent, days=30, reference=today)
    assert not bd.meeting_is_within_recent_days(old, days=30, reference=today)
    assert not bd.meeting_is_within_recent_days(recent, days=0, reference=today)
    assert bd.meeting_is_within_recent_days(
        bd.Meeting("u3", "Board Meeting", "20260517", "id3"),
        days=30,
        reference=today,
    )
    assert not bd.meeting_is_within_recent_days(
        bd.Meeting("u4", "Board Meeting", "20260516", "id4"),
        days=30,
        reference=today,
    )


def test_parse_args_refresh_recent_days_from_config(tmp_path):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(
        '{"refresh_recent_days": 7}',
        encoding="utf-8",
    )
    args = bd.parse_args(["--config", str(cfg)])
    assert args.refresh_recent_days == 7


def test_cli_overrides_refresh_recent_days(tmp_path):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(
        '{"refresh_recent_days": 7}',
        encoding="utf-8",
    )
    args = bd.parse_args(["--config", str(cfg), "--refresh-recent-days", "0"])
    assert args.refresh_recent_days == 0
