"""Stoa's own feature updates, delivered online.

Every Stoa build publishes its update package and a small description (latest.json: version, file, sha256,
what's new) to a fixed web address. Stoa checks it every few hours; the Updates app, the taskbar and a
notification say when new features are ready, and installing is one click (or automatic, if turned on).

The address is in /etc/stoa/update.conf (UPDATE_URL=...), so a company or school can point PCs at its own copy.
"""
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.request

DEFAULT_URL = "https://github.com/damieng1121-ctrl/foundationos/releases/download/stoa-update/latest.json"
CONF = "/etc/stoa/update.conf"
AUTO_FLAG = "/etc/stoa/auto-update"
WHATS_NEW = "/usr/share/stoa/whats-new.txt"
CACHE_TTL = 6 * 3600


def update_url():
    try:
        m = re.search(r"^UPDATE_URL=(\S+)", open(CONF).read(), re.M)
        if m:
            return m.group(1).strip("\"'")
    except OSError:
        pass
    return DEFAULT_URL


def installed_version():
    try:
        return open("/usr/share/stoa/VERSION").read().strip()
    except OSError:
        return "0"


def newer(a, b):
    """Is version a newer than b? (Debian version rules, e.g. 0.3.0+212 > 0.3.0+198)"""
    return subprocess.run(["dpkg", "--compare-versions", a, "gt", b]).returncode == 0


def fetch_manifest(timeout=15):
    req = urllib.request.Request(update_url(), headers={"User-Agent": "Stoa updater"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        m = json.loads(r.read().decode("utf-8"))
    if not all(k in m for k in ("version", "url", "sha256")):
        raise ValueError("incomplete update description")
    return m


def _cache_path():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "stoa", "os-update.json")


def check(force=False, timeout=15):
    """The available update as a dict (version, notes, size...), or None when Stoa is up to date/offline.
    Results are cached for six hours so the taskbar and Updates app stay fast."""
    path = _cache_path()
    m = None
    if not force:
        try:
            c = json.load(open(path))
            if time.time() - c.get("t", 0) < CACHE_TTL:
                m = c.get("manifest")
        except (OSError, ValueError):
            pass
    if m is None:
        try:
            m = fetch_manifest(timeout)
        except (OSError, ValueError):
            return None
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            json.dump({"t": time.time(), "manifest": m}, open(path, "w"))
        except OSError:
            pass
    return m if m and newer(m["version"], installed_version()) else None


def forget_cache():
    try:
        os.remove(_cache_path())
    except OSError:
        pass


def download_verified(m, dest):
    """Download the package and check it's exactly the published file (SHA-256). Raises on any mismatch."""
    req = urllib.request.Request(m["url"], headers={"User-Agent": "Stoa updater"})
    h = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
            f.write(chunk)
    if h.hexdigest() != m["sha256"].lower():
        os.remove(dest)
        raise ValueError("the downloaded update didn't match its published checksum, so it wasn't installed")
    return dest


def auto_enabled():
    return os.path.exists(AUTO_FLAG)


def whats_new():
    try:
        return open(WHATS_NEW).read().strip()
    except OSError:
        return ""
