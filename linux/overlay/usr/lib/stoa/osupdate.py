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
import tempfile
import time
import urllib.error
import urllib.request

DEFAULT_URL = "https://github.com/damieng1121-ctrl/foundationos/releases/download/stoa-update/latest.json"
CONF = "/etc/stoa/update.conf"
AUTO_FLAG = "/etc/stoa/auto-update"
WHATS_NEW = "/usr/share/stoa/whats-new.txt"
# Updates must be signed by this key once Stoa has it (it arrives inside a signed build). Without it (older
# installs) the published SHA-256 is the only check.
PUBKEY = "/usr/share/stoa/update-key.pem"
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


class SignatureError(ValueError):
    pass


def _get(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": "Stoa updater"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def verify_signature(data, sig):
    """True if sig is a valid Ed25519 signature of data by Stoa's update key."""
    with tempfile.TemporaryDirectory() as td:
        d, s = os.path.join(td, "data"), os.path.join(td, "sig")
        open(d, "wb").write(data)
        open(s, "wb").write(sig)
        r = subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", PUBKEY, "-rawin", "-in", d,
                            "-sigfile", s], capture_output=True)
        return r.returncode == 0


def fetch_signed(name, timeout=15):
    """Fetch latest.json / kernel.json from the update address, checking its signature when Stoa has the key."""
    url = update_url().rsplit("/", 1)[0] + "/" + name
    data = _get(url, timeout)
    if os.path.exists(PUBKEY):
        try:
            sig = _get(url + ".sig", timeout)
        except OSError:
            raise SignatureError(f"{name} isn't signed, so it wasn't trusted")
        if not verify_signature(data, sig):
            raise SignatureError(f"{name} has an invalid signature, so it wasn't trusted")
    return json.loads(data.decode("utf-8"))


def fetch_manifest(timeout=15):
    m = fetch_signed(update_url().rsplit("/", 1)[1], timeout)
    if not all(k in m for k in ("version", "url", "sha256")):
        raise ValueError("incomplete update description")
    return m


def fetch_kernel(timeout=15):
    """The newest Stoa kernel (security fixes): {"release", "packages": [{file, url, sha256}], ...} or None."""
    try:
        k = fetch_signed("kernel.json", timeout)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # no kernel published yet
        raise
    if not k.get("packages") or not all({"file", "url", "sha256", "package", "version"} <= set(p) for p in k["packages"]):
        raise ValueError("incomplete kernel description")
    return k


LAST_ERROR = ""


def secure_boot_on():
    import glob
    for f in glob.glob("/sys/firmware/efi/efivars/SecureBoot-*"):
        try:
            return open(f, "rb").read()[-1:] == b"\x01"
        except OSError:
            return False
    return False


def kernel_needed(k):
    """Packages from the kernel description that aren't installed at that version. None with Secure Boot on:
    those PCs start Ubuntu's signed kernel, which gets its security updates from Ubuntu."""
    if secure_boot_on():
        return []
    need = []
    for p in k["packages"]:
        r = subprocess.run(["dpkg-query", "-W", "-f", "${Version}", p["package"]], capture_output=True, text=True)
        if r.returncode or r.stdout.strip() != p["version"]:
            need.append(p)
    return need


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
    k = None
    if m is None:
        global LAST_ERROR
        try:
            m = fetch_manifest(timeout)
            LAST_ERROR = ""
        except SignatureError as e:
            LAST_ERROR = f"An update was found but not installed: {e}. This can mean it was tampered with."
            return None
        except (OSError, ValueError):
            return None
        try:
            k = fetch_kernel(timeout)
        except (OSError, ValueError):
            k = None
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            json.dump({"t": time.time(), "manifest": m, "kernel": k}, open(path, "w"))
        except OSError:
            pass
    else:
        try:
            k = json.load(open(path)).get("kernel")
        except (OSError, ValueError):
            k = None
    desktop = newer(m["version"], installed_version())
    kernel = bool(k) and bool(kernel_needed(k))
    if not desktop and not kernel:
        return None
    out = dict(m) if desktop else {"version": installed_version(), "notes": []}
    if kernel:
        out["kernel"] = k["release"]
        out["notes"] = [f"Security update for the Stoa kernel ({k['release']}) - restart afterwards"] + \
            list(out.get("notes") or [])
    out["desktop"] = desktop
    return out


def forget_cache():
    try:
        os.remove(_cache_path())
    except OSError:
        pass


def download_verified(m, dest):  # m: anything with url and sha256
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
