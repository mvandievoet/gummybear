"""Strava OAuth2 browser handshake, auto-refreshing token store, and `.fit`/`.gpx` uploader."""

import http.server
import json
import time
import urllib.parse
import urllib.request
import uuid
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

DEFAULT_TOKEN_PATH = Path.home() / ".config" / "gummybear" / "strava_tokens.json"
STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_UPLOADS_URL = "https://www.strava.com/api/v3/uploads"


@dataclass
class StravaUploadResult:
    upload_id: int
    status: str
    activity_id: Optional[int]
    error: Optional[str]


def _post_form(url: str, fields: Dict[str, str]) -> Dict[str, object]:
    encoded = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def authorize_interactive(
    client_id: str,
    client_secret: str,
    port: int = 8765,
    token_path: Path = DEFAULT_TOKEN_PATH,
) -> Path:
    """Open browser for one-time Strava OAuth2 approval (`activity:write`) and save tokens."""
    redirect_uri = f"http://localhost:{port}/callback"
    params = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "approval_prompt": "auto",
            "scope": "activity:write,read",
        }
    )
    auth_url = f"{STRAVA_AUTH_URL}?{params}"
    captured: Dict[str, str] = {}

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            if "code" in qs:
                captured["code"] = qs["code"][0]
                body = b"<h2>Gummybear Strava Auth Complete! You can close this tab.</h2>"
                self.send_response(200)
            else:
                captured["error"] = qs.get("error", ["unknown"])[0]
                body = b"<h2>Strava authorization cancelled or failed.</h2>"
                self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

    print(f"Opening browser for Strava authorization:\n  {auth_url}")
    webbrowser.open(auth_url)

    with http.server.HTTPServer(("127.0.0.1", port), CallbackHandler) as httpd:
        httpd.handle_request()

    if "code" not in captured:
        raise RuntimeError(f"Did not receive OAuth code from Strava: {captured}")

    token_resp = _post_form(
        STRAVA_TOKEN_URL,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": captured["code"],
            "grant_type": "authorization_code",
        },
    )
    stored = {
        "client_id": client_id,
        "client_secret": client_secret,
        "access_token": token_resp["access_token"],
        "refresh_token": token_resp["refresh_token"],
        "expires_at": token_resp["expires_at"],
    }
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(json.dumps(stored, indent=2), encoding="utf-8")
    token_path.chmod(0o600)
    return token_path


def get_valid_access_token(token_path: Path = DEFAULT_TOKEN_PATH) -> str:
    """Return a valid Strava access token, refreshing automatically if within 5 min of expiry."""
    if not token_path.exists():
        raise FileNotFoundError(
            f"No Strava credentials at {token_path}. Run `python3 -m gummybear strava-auth` first."
        )
    stored = json.loads(token_path.read_text(encoding="utf-8"))
    if int(stored.get("expires_at", 0)) > int(time.time()) + 300:
        return str(stored["access_token"])

    refreshed = _post_form(
        STRAVA_TOKEN_URL,
        {
            "client_id": str(stored["client_id"]),
            "client_secret": str(stored["client_secret"]),
            "grant_type": "refresh_token",
            "refresh_token": str(stored["refresh_token"]),
        },
    )
    stored["access_token"] = refreshed["access_token"]
    stored["refresh_token"] = refreshed["refresh_token"]
    stored["expires_at"] = refreshed["expires_at"]
    token_path.write_text(json.dumps(stored, indent=2), encoding="utf-8")
    return str(stored["access_token"])


def _build_multipart(
    fields: Dict[str, str], file_field: str, filename: str, file_bytes: bytes
) -> Tuple[str, bytes]:
    boundary = f"----GummybearBoundary{uuid.uuid4().hex}"
    parts = []
    for k, v in fields.items():
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{k}"\r\n\r\n'
            f"{v}\r\n".encode("utf-8")
        )
    parts.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8")
        + file_bytes
        + f"\r\n--{boundary}--\r\n".encode("utf-8")
    )
    return f"multipart/form-data; boundary={boundary}", b"".join(parts)


def upload_activity_to_strava(
    activity_file: Path,
    name: Optional[str] = None,
    description: Optional[str] = None,
    external_id: Optional[str] = None,
    token_path: Path = DEFAULT_TOKEN_PATH,
    poll_seconds: int = 25,
) -> StravaUploadResult:
    """Upload a `.fit` or `.gpx` file to Strava and poll until processing completes."""
    access_token = get_valid_access_token(token_path=token_path)
    suffix = activity_file.suffix.lower().lstrip(".")
    if suffix not in ("fit", "gpx"):
        raise ValueError(f"Unsupported Strava upload extension .{suffix}; expected .fit or .gpx")

    fields: Dict[str, str] = {
        "data_type": suffix,
        "activity_type": "run",
    }
    if name:
        fields["name"] = name
    if description:
        fields["description"] = description
    if external_id:
        fields["external_id"] = external_id

    content_type, body = _build_multipart(
        fields, "file", activity_file.name, activity_file.read_bytes()
    )
    req = urllib.request.Request(
        STRAVA_UPLOADS_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": content_type,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    upload_id = int(payload["id"])
    status = str(payload.get("status", ""))
    activity_id = payload.get("activity_id")
    err = payload.get("error")

    deadline = time.time() + poll_seconds
    while activity_id is None and not err and time.time() < deadline:
        time.sleep(2.0)
        poll_req = urllib.request.Request(
            f"{STRAVA_UPLOADS_URL}/{upload_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        with urllib.request.urlopen(poll_req, timeout=15) as resp:
            poll_data = json.loads(resp.read().decode("utf-8"))
        status = str(poll_data.get("status", ""))
        activity_id = poll_data.get("activity_id")
        err = poll_data.get("error")

    return StravaUploadResult(
        upload_id=upload_id,
        status=status,
        activity_id=int(activity_id) if activity_id is not None else None,
        error=str(err) if err else None,
    )
