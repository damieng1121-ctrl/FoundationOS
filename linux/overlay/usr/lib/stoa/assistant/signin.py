"""Sign in to an AI service in the browser instead of pasting an API key (OAuth 2.0 with PKCE).

The person signs in on the service's own website (with Google, GitHub, email... whatever that site
offers), approves Stoa, and the browser hands a one-time code back to a listener on 127.0.0.1. Stoa
swaps the code for a key that only this computer holds. Stoa never sees the person's password.

  OpenRouter    no registration needed; a key for this computer, revocable at openrouter.ai/settings/keys.
  Hugging Face  needs an OAuth app's client id (public, no secret) in /etc/stoa/signin.json or
                STOA_HF_CLIENT_ID; access tokens are refreshed automatically.

Endpoints can be overridden with STOA_SIGNIN_<SERVICE>_<FIELD> environment variables (for testing, or if
a service moves them).
"""
import base64
import hashlib
import http.server
import json
import os
import secrets
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request

SITE_CONF = "/etc/stoa/signin.json"
PORTS = (3000, 3001, 8765, 0)  # OpenRouter documents http://localhost:3000 for local apps; others as fallback

SERVICES = {
    "openrouter": {
        "flow": "openrouter",
        "authorize": "https://openrouter.ai/auth",
        "exchange": "https://openrouter.ai/api/v1/auth/keys",
        "host": "localhost",
    },
    "huggingface": {
        "flow": "oauth2",
        "authorize": "https://huggingface.co/oauth/authorize",
        "token": "https://huggingface.co/oauth/token",
        "scope": "openid profile inference-api",
        "host": "127.0.0.1",
    },
}

DONE_PAGE = """<!doctype html><meta charset=utf-8><title>Stoa AI</title>
<body style="font-family:Inter,sans-serif;background:#121829;color:#e9edf7;display:grid;place-items:center;height:90vh">
<div style="text-align:center"><div style="font-size:48px">{icon}</div><h2>{title}</h2>
<p style="color:#8f9bb7">{text}</p></div></body>"""


class SignInError(Exception):
    pass


def service(name):
    s = dict(SERVICES[name])
    try:
        with open(SITE_CONF) as f:
            s.update(json.load(f).get(name, {}))
    except (OSError, ValueError):
        pass
    if name == "huggingface" and os.environ.get("STOA_HF_CLIENT_ID"):
        s["client_id"] = os.environ["STOA_HF_CLIENT_ID"]
    for k in list(s) + ["client_id"]:
        v = os.environ.get(f"STOA_SIGNIN_{name.upper()}_{k.upper()}")
        if v:
            s[k] = v
    return s


def available(name):
    """(usable, reason). Hugging Face needs a client id set up once by whoever builds Stoa."""
    s = service(name)
    if s["flow"] == "oauth2" and not s.get("client_id"):
        return False, "Hugging Face sign-in isn't set up on this computer yet (no OAuth client id)."
    return True, ""


def _pkce():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _post(url, data, form=False):
    body = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded" if form else "application/json",
        "Accept": "application/json", "User-Agent": "Stoa-AI"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise SignInError(f"The service refused the sign-in ({e.code}). {detail}") from None
    except OSError as e:
        raise SignInError(f"Couldn't reach the service: {e}") from None


def _listen(host):
    for port in PORTS:
        srv_sock = socket.socket()
        try:
            srv_sock.bind(("127.0.0.1", port))
            port = srv_sock.getsockname()[1]
            srv_sock.close()
            return port
        except OSError:
            srv_sock.close()
    raise SignInError("No free local port to receive the sign-in.")


def _wait_for_code(host, port, state, open_url, timeout):
    """Run a one-shot web server on 127.0.0.1:port, open the browser, return the code it receives."""
    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            ok = "code" in q and (state is None or q.get("state", [None])[0] == state)
            if "code" in q and not ok:
                result["error"] = "The sign-in reply didn't match this request."
            elif ok:
                result["code"] = q["code"][0]
            elif "error" in q:
                result["error"] = q.get("error_description", q["error"])[0]
            else:
                self.send_response(404)
                self.end_headers()
                return
            page = DONE_PAGE.format(
                icon="✓" if ok else "✕", title="You're signed in" if ok else "Sign-in didn't finish",
                text="You can close this tab and go back to Stoa." if ok else result.get("error", ""))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page.encode())

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", port), Handler)
    srv.timeout = 1
    open_url()
    deadline = time.time() + timeout
    while not result and time.time() < deadline:
        srv.handle_request()
    srv.server_close()
    if "error" in result:
        raise SignInError(result["error"])
    if "code" not in result:
        raise SignInError("Sign-in timed out. Try again.")
    return result["code"]


def _open_browser(url):
    subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def sign_in(name, timeout=300, opener=None):
    """Sign in to service `name`. Returns credentials to store: {"api_key", "refresh_token", "expires_at"}."""
    ok, why = available(name)
    if not ok:
        raise SignInError(why)
    opener = opener or _open_browser
    s = service(name)
    verifier, challenge = _pkce()
    host = s.get("host", "127.0.0.1")
    port = _listen(host)
    redirect = f"http://{host}:{port}/callback" if s["flow"] == "oauth2" else f"http://{host}:{port}"
    if s["flow"] == "openrouter":
        url = s["authorize"] + "?" + urllib.parse.urlencode(
            {"callback_url": redirect, "code_challenge": challenge, "code_challenge_method": "S256"})
        code = _wait_for_code(host, port, None, lambda: opener(url), timeout)
        r = _post(s["exchange"], {"code": code, "code_verifier": verifier, "code_challenge_method": "S256"})
        if not r.get("key"):
            raise SignInError("The service didn't return a key.")
        return {"api_key": r["key"], "refresh_token": "", "expires_at": 0}
    state = secrets.token_urlsafe(16)
    url = s["authorize"] + "?" + urllib.parse.urlencode({
        "client_id": s["client_id"], "redirect_uri": redirect, "response_type": "code", "scope": s["scope"],
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})
    code = _wait_for_code(host, port, state, lambda: opener(url), timeout)
    r = _post(s["token"], {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect,
                           "client_id": s["client_id"], "code_verifier": verifier}, form=True)
    return _tokens(r)


def _tokens(r):
    if not r.get("access_token"):
        raise SignInError("The service didn't return an access token.")
    return {"api_key": r["access_token"], "refresh_token": r.get("refresh_token", ""),
            "expires_at": int(time.time()) + int(r.get("expires_in") or 0) if r.get("expires_in") else 0}


def refresh(name, refresh_token):
    """New credentials from a refresh token (OAuth services whose access tokens expire)."""
    s = service(name)
    if s["flow"] != "oauth2" or not refresh_token:
        raise SignInError("Sign in again.")
    r = _post(s["token"], {"grant_type": "refresh_token", "refresh_token": refresh_token,
                           "client_id": s.get("client_id", "")}, form=True)
    out = _tokens(r)
    out["refresh_token"] = out["refresh_token"] or refresh_token
    return out


def sign_in_async(name, done):
    """Run sign_in in a thread; call done(creds, error_message)."""
    def run():
        try:
            done(sign_in(name), None)
        except SignInError as e:
            done(None, str(e))
        except Exception as e:  # noqa: BLE001
            done(None, f"Sign-in failed: {e}")
    threading.Thread(target=run, daemon=True).start()
