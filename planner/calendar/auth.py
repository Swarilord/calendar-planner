"""Google OAuth for the calendar: log in once, then refresh silently.

credentials.json  the app's identity (OAuth client from Google Cloud)
token.json        the user's permission (access + refresh token)

Both are git-ignored and never printed. In Testing mode Google's refresh tokens
expire after 7 days; then refreshing fails and the user must log in again:
    uv run python -m planner.calendar.auth
"""

import os
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from planner.calendar.backend import CalendarError

SCOPES = [
    # Create the app's own "Study plan" calendar and write events only there.
    "https://www.googleapis.com/auth/calendar.app.created",
    # Read events on all calendars (lectures may be in a subscribed calendar).
    "https://www.googleapis.com/auth/calendar.events.readonly",
    # See which calendars exist (to find them; changes nothing).
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
]
CREDENTIALS_FILE = Path("credentials.json")
TOKEN_FILE = Path("token.json")


class LoginRequiredError(CalendarError):
    """No usable token: the user must log in (again)."""


def load_credentials(
    token_file: Path = TOKEN_FILE, scopes: list[str] = SCOPES
) -> Credentials | None:
    """Saved credentials, refreshed if needed; None if a new login is needed."""
    if not token_file.exists():
        return None
    # No scopes argument: it would replace the saved scopes, and the check
    # below would then pass even for a token made with other scopes.
    creds: Credentials = Credentials.from_authorized_user_file(str(token_file))
    if not creds.has_scopes(scopes):  # scopes changed since the last login
        return None
    if creds.valid:
        return creds
    if not creds.refresh_token:
        return None
    try:
        creds.refresh(Request())
    except RefreshError:  # expired (7 days in Testing mode) or revoked
        return None
    save(creds, token_file)
    return creds


def login(
    credentials_file: Path = CREDENTIALS_FILE,
    token_file: Path = TOKEN_FILE,
    scopes: list[str] = SCOPES,
) -> Credentials:
    """Open the browser for Google's consent screen and save the new token."""
    if not credentials_file.exists():
        raise LoginRequiredError(
            f"{credentials_file} not found: download the OAuth client (Desktop "
            "app) from Google Cloud and save it under this name."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), scopes)
    creds: Credentials = flow.run_local_server(port=0)  # port 0: any free port
    save(creds, token_file)
    return creds


def get_credentials(token_file: Path = TOKEN_FILE) -> Credentials:
    """Credentials for API calls, or LoginRequiredError (never opens a browser:
    a server or a test must not block waiting for a login)."""
    creds = load_credentials(token_file)
    if creds is None:
        raise LoginRequiredError(
            "Google login needed: run `uv run python -m planner.calendar.auth`."
        )
    return creds


def save(creds: Credentials, token_file: Path) -> None:
    """Write the token readable by this user only (it grants calendar access)."""
    fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)  # the mode above only applies to a new file
    with os.fdopen(fd, "w") as file:
        file.write(creds.to_json())


if __name__ == "__main__":
    login()
    print(f"Logged in. Token saved to {TOKEN_FILE} (git-ignored).")
