"""Tests for Google OAuth handling. Fake token files only: no network, no Google."""

import json
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

from planner.calendar.auth import (
    SCOPES,
    LoginRequiredError,
    get_credentials,
    load_credentials,
    login,
)

FUTURE = "2099-01-01T00:00:00Z"
PAST = "2000-01-01T00:00:00Z"


def write_token(path: Path, expiry: str = FUTURE, scopes: list[str] = SCOPES) -> Path:
    """A token.json as the login writes it (placeholder values, not real ones)."""
    token = path / "token.json"
    info: dict[str, Any] = {
        "token": "access-placeholder",
        "refresh_token": "refresh-placeholder",
        "client_id": "client-placeholder",
        "client_secret": "placeholder",
        "scopes": scopes,
        "expiry": expiry,
    }
    token.write_text(json.dumps(info))
    return token


@pytest.fixture
def no_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(self: Credentials, request: Any) -> None:
        raise AssertionError("refresh must not be called")

    monkeypatch.setattr(Credentials, "refresh", fail)


def test_no_token_file_means_login_required(tmp_path: Path) -> None:
    assert load_credentials(tmp_path / "token.json") is None
    with pytest.raises(LoginRequiredError, match="planner.calendar.auth"):
        get_credentials(tmp_path / "token.json")


@pytest.mark.usefixtures("no_refresh")
def test_valid_token_is_used_without_refreshing(tmp_path: Path) -> None:
    creds = load_credentials(write_token(tmp_path))
    assert creds is not None and creds.token == "access-placeholder"


@pytest.mark.usefixtures("no_refresh")
def test_token_with_other_scopes_needs_a_new_login(tmp_path: Path) -> None:
    # Made before we added a scope: must not be used with the new scope list.
    token = write_token(tmp_path, scopes=SCOPES[:1])
    assert load_credentials(token) is None


def test_expired_token_is_refreshed_and_saved_privately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refresh(self: Credentials, request: Any) -> None:
        self.token = "new-access-placeholder"
        self.expiry = datetime(2099, 1, 1)  # google-auth uses naive UTC

    monkeypatch.setattr(Credentials, "refresh", refresh)
    token = write_token(tmp_path, expiry=PAST)
    creds = load_credentials(token)
    assert creds is not None and creds.token == "new-access-placeholder"
    assert json.loads(token.read_text())["token"] == "new-access-placeholder"
    assert stat.S_IMODE(token.stat().st_mode) == 0o600  # only this user can read


def test_failed_refresh_means_login_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # In Testing mode Google lets refresh tokens expire after 7 days.
    def refresh(self: Credentials, request: Any) -> None:
        raise RefreshError("invalid_grant: Token has been expired or revoked.")

    monkeypatch.setattr(Credentials, "refresh", refresh)
    token = write_token(tmp_path, expiry=PAST)
    with pytest.raises(LoginRequiredError):
        get_credentials(token)


def test_login_without_client_file_explains_what_to_do(tmp_path: Path) -> None:
    with pytest.raises(LoginRequiredError, match="Desktop"):
        login(tmp_path / "credentials.json", tmp_path / "token.json")
