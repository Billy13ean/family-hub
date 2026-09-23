"""OAuth for a single personal Google account, with the token stored outside the repo."""

import os

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from .config import Paths

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


class AuthError(Exception):
    pass


def load_credentials(paths: Paths, interactive: bool = False) -> Credentials:
    """Return valid credentials, refreshing the saved token if needed.

    Only `interactive=True` (the `auth` command) opens a browser; the scheduled
    job fails with a clear message instead of hanging on a sign-in page.
    """
    creds = None
    if paths.token.exists():
        creds = Credentials.from_authorized_user_file(str(paths.token), SCOPES)
        if not set(SCOPES) <= set(creds.scopes or []):
            creds = None  # token predates a scope change; sign in again

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(paths, creds)
            return creds
        except RefreshError as e:
            if not interactive:
                raise AuthError(
                    f"Saved sign-in was rejected ({e}). "
                    "Run `uv run python -m home_manager auth` to sign in again."
                ) from e

    if not interactive:
        raise AuthError("Not signed in. Run `uv run python -m home_manager auth` first.")

    if not paths.client_secret.exists():
        raise AuthError(
            f"Missing {paths.client_secret}. Download the OAuth client JSON "
            "from Google Cloud (see README, step 5) and save it there."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(paths.client_secret), SCOPES)
    creds = flow.run_local_server(port=0)
    _save_token(paths, creds)
    return creds


def _save_token(paths: Paths, creds: Credentials) -> None:
    paths.dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(paths.token, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(creds.to_json())
