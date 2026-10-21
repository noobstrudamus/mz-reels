"""Instagram Graph API client shared by everything in ops/.

Credentials come from the environment: INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_BUSINESS_ACCOUNT_ID
(optional INSTAGRAM_API_BASE, default https://graph.facebook.com/v24.0).

SAFETY: every call that creates, publishes or sends something is a *write*. Writes are only
performed when the client was created with live=True AND the kill switch allows it
(config/settings.json "auto_publish": true and env MZ_KILL is not set). Otherwise the call is
recorded in client.dry_log and a {"dry_run": true} stub is returned.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CONFIG = ROOT / "config"
RETRY_CODES = {1, 2, 4, 17, 32, 341, 613, 80001, 80002}   # transient / rate limiting


class GraphError(Exception):
    def __init__(self, status, payload):
        err = (payload or {}).get("error", {}) if isinstance(payload, dict) else {}
        self.status, self.code, self.subcode = status, err.get("code"), err.get("error_subcode")
        self.message = err.get("message") or str(payload)
        super().__init__(f"HTTP {status} code={self.code}/{self.subcode}: {self.message}")


class TokenExpired(GraphError):
    """code 190: the access token is expired or invalid; nothing will work until it is replaced."""


def settings():
    p = CONFIG / "settings.json"
    return json.loads(p.read_text()) if p.exists() else {}


def writes_allowed():
    return bool(settings().get("auto_publish")) and not os.environ.get("MZ_KILL")


class IG:
    def __init__(self, live=False, token=None, ig_id=None, base=None):
        self.token = token or os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
        self.ig_id = ig_id or os.environ.get("INSTAGRAM_BUSINESS_ACCOUNT_ID", "")
        self.base = (base or os.environ.get("INSTAGRAM_API_BASE") or "https://graph.facebook.com/v24.0").rstrip("/")
        self.live = live and writes_allowed()
        self.dry_log = []
        if not self.token or not self.ig_id:
            raise SystemExit("INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_BUSINESS_ACCOUNT_ID must be set")

    # ---------- transport ----------
    def _send(self, method, url, params=None, body=None, headers=None, retries=4):
        params = dict(params or {})
        headers = dict(headers or {})
        if "Authorization" not in headers:
            params.setdefault("access_token", self.token)
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        for attempt in range(retries + 1):
            req = urllib.request.Request(url, data=body, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    raw = r.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                raw = e.read()
                try:
                    payload = json.loads(raw)
                except ValueError:
                    payload = {"error": {"message": raw[:300].decode("utf-8", "replace")}}
                err = GraphError(e.code, payload)
                if err.code == 190:
                    raise TokenExpired(e.code, payload)
                if attempt < retries and (e.code >= 500 or e.code == 429 or err.code in RETRY_CODES):
                    time.sleep(min(60, 2 ** (attempt + 1)))
                    continue
                raise err
            except urllib.error.URLError:
                if attempt < retries:
                    time.sleep(min(60, 2 ** (attempt + 1)))
                    continue
                raise

    def get(self, path, **params):
        return self._send("GET", f"{self.base}/{path.lstrip('/')}", params)

    def paginate(self, path, limit=None, **params):
        url, n = f"{self.base}/{path.lstrip('/')}", 0
        page = self._send("GET", url, params)
        while True:
            for item in page.get("data", []):
                yield item
                n += 1
                if limit and n >= limit:
                    return
            nxt = page.get("paging", {}).get("next")
            if not nxt:
                return
            page = self._send("GET", nxt)   # next URL already carries the token

    def post(self, path, *, what, url=None, params=None, body=None, headers=None):
        """A write. `what` is a short human description used in the dry-run log."""
        target = url or f"{self.base}/{path.lstrip('/')}"
        if not self.live:
            safe = {k: v for k, v in (params or {}).items() if k != "access_token"}
            self.dry_log.append({"what": what, "url": target, "params": safe,
                                 "body_bytes": len(body) if body else 0})
            return {"dry_run": True, "what": what}
        # writes are never retried blindly: a timeout after Instagram accepted the call would double-post
        return self._send("POST", target, params, body, headers, retries=0)

    # ---------- helpers ----------
    def check_token(self):
        """Raises TokenExpired if the token no longer works; returns the account's username."""
        return self.get(self.ig_id, fields="username")["username"]


def append_jsonl(name, rec):
    DATA.mkdir(exist_ok=True)
    with open(DATA / name, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read_jsonl(name):
    p = DATA / name
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
