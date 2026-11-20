"""Stoa Doctor: health checks that spot common problems early, with one-click fixes.

Each check returns None (all good) or an Issue. Fixes run as the person where possible and through
fpkg-helper (pkexec) when they need administrator rights. Anything Stoa can't fix by itself goes to Stoa AI
with the details attached.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import time

HELPER = "/usr/lib/stoa/fpkg-helper"
HOME = os.path.expanduser("~")
STATE = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.join(HOME, ".cache"), "stoa", "doctor.json")


def _run(*cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.SubprocessError) as e:
        return 127, "", str(e)


def _human(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u in ("B", "KB") else f"{n:.1f} {u}"
        n /= 1024


class Issue(dict):
    """id, title (short), detail (plain words), severity (warning|problem), fix_label (None = ask Stoa AI)."""

    def __init__(self, id, title, detail, severity="warning", fix_label=None, ai_context=""):
        super().__init__(id=id, title=title, detail=detail, severity=severity, fix_label=fix_label,
                         ai_context=ai_context)


# ------------------------------------------------------------------ checks

def check_disk():
    for path, name in (("/", "Stoa's drive"), (HOME, "your home folder")):
        try:
            u = shutil.disk_usage(path)
        except OSError:
            continue
        if u.free < 5 * 2**30 or u.free / u.total < 0.08:
            return Issue("disk", f"{name.capitalize()} is almost full",
                         f"Only {_human(u.free)} of {_human(u.total)} is free. Updates can fail and apps can stop "
                         "working when it runs out. Stoa can clear the bin, caches, old logs and leftover update "
                         "files.", "problem" if u.free < 2 * 2**30 else "warning", "Free up space")
    return None


def check_packages():
    if not shutil.which("dpkg"):
        return None
    rc, out, _ = _run("dpkg", "--audit")
    if out.strip() or os.path.exists("/var/lib/dpkg/updates") and os.listdir("/var/lib/dpkg/updates"):
        return Issue("packages", "An update was interrupted",
                     "Some software didn't finish installing or updating (perhaps the PC turned off mid-update). "
                     "Until it's finished, installing and updating apps can fail.", "problem", "Finish it now",
                     out[-1500:])
    return None


def _failed(user):
    rc, out, _ = _run("systemctl", *(["--user"] if user else []), "--failed", "--no-legend", "--plain")
    units = [line.split()[0] for line in out.splitlines() if line.strip()]
    ignore = re.compile(r"^(systemd-networkd-wait-online|NetworkManager-wait-online|plymouth|apport|"
                        r"casper|snapd\.|motd-news|secureboot-db|ua-|ubuntu-advantage)")
    return [u for u in units if not ignore.match(u)]


def check_services():
    sys_units, user_units = _failed(False), _failed(True)
    if not sys_units and not user_units:
        return None
    names = ", ".join((sys_units + user_units)[:4])
    log = ""
    for u in (sys_units + user_units)[:2]:
        _rc, out, _ = _run("journalctl", *(["--user"] if u in user_units else []), "-u", u, "-n", "15",
                           "--no-pager", "-o", "cat")
        log += f"--- {u}\n{out[-800:]}\n"
    return Issue("services", "Part of the system stopped working",
                 f"These background services failed: {names}. Stoa can try restarting them.", "warning",
                 "Restart them", log)


def check_internet():
    if not shutil.which("nmcli"):
        return None
    _rc, out, _ = _run("nmcli", "-t", "-f", "TYPE,STATE", "device")
    devices = [line.split(":") for line in out.splitlines() if line.count(":") >= 1]
    if not any(t in ("wifi", "ethernet") for t, *_ in devices):
        return None
    _rc, conn, _ = _run("nmcli", "networking", "connectivity", "check", timeout=20)
    conn = conn.strip()
    if conn == "portal":
        return Issue("portal", "This Wi-Fi needs you to sign in",
                     "You're connected, but the network (hotel, café, train...) wants you to accept its terms or "
                     "sign in on a web page first.", "warning", "Open the sign-in page")
    if conn in ("none", "limited") and any(s.startswith("connected") for _t, s, *_ in devices):
        return Issue("internet", "Connected, but no internet",
                     "The PC is connected to the network but can't reach the internet. Reconnecting often fixes "
                     "it; if not, restart the router.", "problem", "Reconnect")
    return None


def check_audio():
    if not shutil.which("wpctl"):
        return None
    rc, out, _ = _run("wpctl", "status")
    if rc != 0:
        return Issue("audio", "Sound isn't working",
                     "The sound system isn't running, so nothing can play audio.", "problem", "Restart sound")
    sinks = re.search(r"Sinks:\n(.*?)\n\s*[│├└ ]*\n", out, re.S)
    if sinks and "Dummy Output" in sinks.group(1) and "*" in sinks.group(1):
        return Issue("audio", "No speakers or headphones found",
                     "Sound is going to a 'dummy' device, so you won't hear anything. Restarting sound usually "
                     "finds your speakers again.", "warning", "Restart sound")
    return None


def check_memory():
    try:
        line = open("/proc/pressure/memory").readline()
    except OSError:
        return None
    m = re.search(r"avg60=([\d.]+)", line)
    if m and float(m.group(1)) > 25:
        return Issue("memory", "The PC is running out of memory",
                     "Programs are waiting for memory, which makes everything slow. Closing a big app or browser "
                     "tabs helps; Task Manager shows what's using the most.", "warning", "Show what's using it")
    return None


def check_temperature():
    for d in glob.glob("/sys/class/hwmon/hwmon*"):
        if open(os.path.join(d, "name")).read().strip() not in ("k10temp", "coretemp", "zenpower", "cpu_thermal"):
            continue
        temps = []
        for f in glob.glob(os.path.join(d, "temp*_input")):
            try:
                temps.append(int(open(f).read()) / 1000)
            except (OSError, ValueError):
                pass
        if temps and max(temps) >= 92:
            return Issue("heat", "The processor is very hot",
                         f"It's at {max(temps):.0f} °C. The PC slows itself down to cool off, and may switch off. "
                         "Check the fans and vents aren't blocked or dusty.", "warning", None,
                         f"CPU temperature {max(temps):.0f} C")
    return None


def check_virus_signatures():
    files = glob.glob("/var/lib/clamav/daily.c?d")
    if not shutil.which("clamscan"):
        return None
    newest = max((os.path.getmtime(f) for f in files), default=0)
    if time.time() - newest > 8 * 86400:
        return Issue("signatures", "Virus protection is out of date",
                     "Stoa Protect hasn't downloaded new virus signatures for over a week, so it can miss new "
                     "threats.", "warning", "Update now")
    return None


def check_restart():
    if os.path.exists("/var/run/reboot-required"):
        return Issue("restart", "Restart to finish a security update",
                     "Security fixes have been installed and take effect when the PC restarts. Save your work, then "
                     "restart when it suits you.", "warning", "Restart now")
    return None


def check_crashes():
    recent = [f for f in glob.glob("/var/crash/*.crash") if time.time() - os.path.getmtime(f) < 86400]
    if not recent:
        return None
    apps = sorted({os.path.basename(f).split("_", 2)[1] if "_" in os.path.basename(f) else os.path.basename(f)
                   for f in recent})
    return Issue("crashes", "An app crashed",
                 f"{', '.join(apps[:3])} crashed today. If it keeps happening, Stoa AI can look into why.",
                 "warning", None, "Crash reports: " + ", ".join(os.path.basename(f) for f in recent[:5]))


CHECKS = [check_restart, check_disk, check_packages, check_services, check_internet, check_audio, check_memory,
          check_temperature, check_virus_signatures, check_crashes]
NAMES = {"check_restart": "Security updates", "check_disk": "Storage space", "check_packages": "Software updates", "check_services": "System services",
         "check_internet": "Internet", "check_audio": "Sound", "check_memory": "Memory",
         "check_temperature": "Temperature", "check_virus_signatures": "Virus protection",
         "check_crashes": "App crashes"}


def run_checks():
    """[(name, Issue or None)]"""
    out = []
    for c in CHECKS:
        try:
            out.append((NAMES[c.__name__], c()))
        except Exception as e:  # noqa: BLE001 - a broken check must not hide the others
            out.append((NAMES[c.__name__], None))
            print(f"stoa-doctor: {c.__name__}: {e}")
    return out


# ------------------------------------------------------------------ fixes

def _root(*args):
    rc, out, err = _run("pkexec", HELPER, *args, timeout=900)
    if rc == 126:
        return False, "Cancelled."
    return rc == 0, (out + err).strip()[-400:]


def fix(issue_id):
    """-> (ok, message)"""
    if issue_id == "disk":
        before = shutil.disk_usage(HOME).free
        for p in (os.path.join(HOME, ".local/share/Trash/files"), os.path.join(HOME, ".local/share/Trash/info"),
                  os.path.join(HOME, ".cache/thumbnails")):
            shutil.rmtree(p, ignore_errors=True)
        _run("flatpak", "uninstall", "--user", "--unused", "-y", "--noninteractive", timeout=300)
        ok, msg = _root("cleanup")
        freed = shutil.disk_usage(HOME).free - before
        return True, f"Freed {_human(max(0, freed))}." + ("" if ok else " (System files weren't cleaned: " + msg + ")")
    if issue_id == "packages":
        ok, msg = _root("repair")
        return ok, "Finished the interrupted update." if ok else f"That didn't work: {msg}"
    if issue_id == "services":
        for u in _failed(True):
            _run("systemctl", "--user", "reset-failed", u)
            _run("systemctl", "--user", "restart", u)
        units = _failed(False)
        if units:
            ok, msg = _root("restart-service", *units)
        left = _failed(False) + _failed(True)
        return not left, "Everything's running again." if not left else \
            f"{', '.join(left)} still failed. Ask Stoa AI to look at it."
    if issue_id == "internet":
        dev = next((line.split(":")[0] for line in _run("nmcli", "-t", "-f", "DEVICE,STATE", "device")[1].splitlines()
                    if ":connected" in line), None)
        if dev:
            _run("nmcli", "device", "reapply", dev)
            _run("nmcli", "device", "disconnect", dev)
            _run("nmcli", "device", "connect", dev, timeout=40)
        time.sleep(3)
        ok = _run("nmcli", "networking", "connectivity", "check", timeout=20)[1].strip() == "full"
        return ok, "Back online." if ok else "Still no internet. Try restarting your router, or ask Stoa AI."
    if issue_id == "portal":
        subprocess.Popen(["xdg-open", "http://neverssl.com"], start_new_session=True)
        return True, "Opened the sign-in page in your browser."
    if issue_id == "audio":
        _run("systemctl", "--user", "restart", "wireplumber", "pipewire", "pipewire-pulse")
        time.sleep(2)
        return check_audio() is None, "Sound restarted."
    if issue_id == "memory":
        subprocess.Popen(["stoa-taskmgr"], start_new_session=True)
        return True, "Task Manager is open, sorted by what's using the most."
    if issue_id == "restart":
        subprocess.Popen(["systemctl", "reboot"], start_new_session=True)
        return True, "Restarting..."
    if issue_id == "signatures":
        ok, msg = _root("restart-service", "clamav-freshclam")
        return ok, "Downloading new virus signatures now." if ok else msg
    return False, "Stoa can't fix this by itself. Ask Stoa AI."


def ask_ai(issue):
    text = (f"Stoa's health check found a problem: {issue['title']}. {issue['detail']}\n"
            f"Details: {issue.get('ai_context', '')[:1500]}\nPlease find out why and fix it if you can.")
    subprocess.Popen(["stoa-assistant", "--ask", text], start_new_session=True)


# ------------------------------------------------------------------ background watcher

def _load_state():
    try:
        return json.load(open(STATE))
    except (OSError, ValueError):
        return {}


def watch(interval=600):
    """Check every 10 minutes; tell the person once a day about each new problem (not during Game Mode)."""
    time.sleep(120)
    while True:
        quiet = os.path.exists(os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "stoa-gamemode"))
        if not quiet:
            state = _load_state()
            for _name, issue in run_checks():
                if not issue or time.time() - state.get(issue["id"], 0) < 86400:
                    continue
                state[issue["id"]] = time.time()
                if shutil.which("notify-send"):
                    subprocess.Popen(["sh", "-c", 'a=$(notify-send -a "Stoa" -i dialog-warning -A default=Open '
                                      '--wait "$1" "$2"); [ "$a" = default ] && stoa-taskmgr health', "sh",
                                      issue["title"], issue["detail"] + "\nClick to fix it."], start_new_session=True)
            try:  # new Stoa features: say so once per version
                import osupdate
                m = osupdate.check()
                if m and state.get("announced") != m["version"] and shutil.which("notify-send"):
                    state["announced"] = m["version"]
                    first = (m.get("notes") or ["Improvements and fixes"])[0]
                    subprocess.Popen(["sh", "-c", 'a=$(notify-send -a "Stoa" -i system-software-update -A default=Open '
                                      '--wait "$1" "$2"); [ "$a" = default ] && stoa-updates', "sh",
                                      "New Stoa features are ready", f"{first}\nClick to update."],
                                     start_new_session=True)
            except Exception:  # noqa: BLE001
                pass
            os.makedirs(os.path.dirname(STATE), exist_ok=True)
            json.dump(state, open(STATE, "w"))
        time.sleep(interval)
