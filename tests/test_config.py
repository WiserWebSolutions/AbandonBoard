"""Tests for config file loading."""

from __future__ import annotations

import argparse
import json

import pytest

import export_boarddocs as bd


def _args(**kwargs: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "public_only": False,
        "private_only": False,
        "username": None,
        "cookies_file": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_normalize_config_committees_dict():
    raw = {
        "site": "zz/aa",
        "committees": {"Board": "ID1111111111", "Policy": "ID2222222222"},
    }
    out = bd.normalize_config(raw)
    assert out["site"] == "zz/aa"
    assert out["committee_ids"] == ["ID1111111111", "ID2222222222"]


def test_normalize_config_committee_ids_take_precedence():
    raw = {
        "committee_ids": ["ONLY11111111"],
        "committees": {"Ignored": "ID2222222222"},
    }
    out = bd.normalize_config(raw)
    assert out["committee_ids"] == ["ONLY11111111"]


def test_normalize_config_kebab_case_keys():
    raw = {"public-url": "https://example.com/x", "private-only": True}
    out = bd.normalize_config(raw)
    assert out["public_url"] == "https://example.com/x"
    assert out["private_only"] is True


def test_load_config_file(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text(
        json.dumps({"site": "st/te", "username": "u"}),
        encoding="utf-8",
    )
    loaded = bd.load_config_file(path)
    assert loaded["site"] == "st/te"
    assert loaded["username"] == "u"


def test_unrecognized_config_keys_are_ignored(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text(
        json.dumps({"username": "u", "not_a_setting": 1, "password": "x"}),
        encoding="utf-8",
    )
    loaded = bd.load_config_file(path)
    assert loaded == {"username": "u"}


def test_prompt_login_secret(monkeypatch):
    monkeypatch.setattr(bd.getpass, "getpass", lambda _prompt: "typed-secret")
    assert bd.prompt_login_secret("alice") == "typed-secret"


def test_prompt_login_secret_rejects_empty(monkeypatch):
    monkeypatch.setattr(bd.getpass, "getpass", lambda _prompt: "")
    with pytest.raises(ValueError, match="Login is required"):
        bd.prompt_login_secret("alice")


def test_load_config_file_invalid_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid JSON"):
        bd.load_config_file(path)


def test_parse_args_reads_config_file(tmp_path):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(
        json.dumps({"site": "xx/yy", "limit": 5, "verbose": True}),
        encoding="utf-8",
    )
    args = bd.parse_args(["--config", str(cfg)])
    assert args.site == "xx/yy"
    assert args.limit == 5
    assert args.verbose is True
    assert args.config == cfg
    assert not hasattr(args, "password")


def test_cli_overrides_config_file(tmp_path):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"site": "xx/yy", "limit": 9}), encoding="utf-8")
    args = bd.parse_args(["--config", str(cfg), "--site", "aa/bb", "--limit", "2"])
    assert args.site == "aa/bb"
    assert args.limit == 2


def test_parse_args_defaults_without_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = bd.parse_args([])
    assert args.site == bd.DEFAULT_SITE
    assert args.config is None
    assert not hasattr(args, "password")


def test_apply_public_only_default_without_credentials():
    args = _args()
    bd.apply_public_only_default(args)
    assert args.public_only is True


def test_apply_public_only_default_with_username():
    args = _args(username="alice")
    bd.apply_public_only_default(args)
    assert args.public_only is False


def test_apply_public_only_default_with_cookies_file():
    args = _args(cookies_file="cookies.json")
    bd.apply_public_only_default(args)
    assert args.public_only is False


def test_apply_public_only_default_respects_explicit_flags():
    args = _args(public_only=True)
    bd.apply_public_only_default(args)
    assert args.public_only is True

    args = _args(private_only=True)
    bd.apply_public_only_default(args)
    assert args.public_only is False


def test_apply_public_only_default_skips_when_already_public_only():
    args = _args(public_only=True, username="alice")
    bd.apply_public_only_default(args)
    assert args.public_only is True
