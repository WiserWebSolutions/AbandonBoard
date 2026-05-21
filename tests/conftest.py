"""Shared fixtures for AbandonBoard unit tests."""

from __future__ import annotations

import pytest

SITE = "pa/phoe"
BASE_URL = f"https://go.boarddocs.com/{SITE}/Board.nsf"


@pytest.fixture
def site() -> str:
    return SITE


@pytest.fixture
def base_url() -> str:
    return BASE_URL
