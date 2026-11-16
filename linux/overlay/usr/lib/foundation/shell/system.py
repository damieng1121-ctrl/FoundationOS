"""Read and change system state: network, Wi-Fi, Bluetooth, volume, brightness, battery, power."""
import glob
import os
import re
import shutil
import subprocess


def _run(*cmd, timeout=4):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def network():
    """-> (kind, name, signal) kind in wifi|ethernet|none"""
    out = _run("nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "device")
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and parts[1] == "connected":
            if parts[0] == "wifi":
                sig = 0
                for l in _run("nmcli", "-t", "-f", "ACTIVE,SIGNAL", "device", "wifi").splitlines():
                    if l.startswith("yes:"):
                        sig = int(l.split(":")[1] or 0)
                return "wifi", parts[2], sig
            if parts[0] == "ethernet":
                return "ethernet", parts[2], 100
    return "none", "", 0


def network_icon():
    kind, _, sig = network()
    if kind == "ethernet":
        return "network-wired-symbolic"
    if kind == "wifi":
        lvl = "excellent" if sig > 75 else "good" if sig > 50 else "ok" if sig > 25 else "weak"
        return f"network-wireless-signal-{lvl}-symbolic"
    return "network-offline-symbolic"


def wifi_enabled():
    return _run("nmcli", "radio", "wifi").strip() == "enabled"


def has_wifi():
    return "wifi" in _run("nmcli", "-t", "-f", "TYPE", "device")


def set_wifi(on):
    _run("nmcli", "radio", "wifi", "on" if on else "off")


def wifi_networks():
    out = _run("nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "auto",
               timeout=10)
    nets = {}
    for line in out.splitlines():
        m = re.match(r"^(\*?):(.*):(\d+):(.*)$", line)
        if not m or not m.group(2):
            continue
        ssid = m.group(2).replace("\\:", ":")
        sig = int(m.group(3))
        if ssid not in nets or sig > nets[ssid]["signal"]:
            nets[ssid] = {"ssid": ssid, "signal": sig, "secure": bool(m.group(4).strip()), "active": m.group(1) == "*"}
    return sorted(nets.values(), key=lambda n: (not n["active"], -n["signal"]))


def wifi_connect(ssid, password=None):
    cmd = ["nmcli", "device", "wifi", "connect", ssid]
    if password:
        cmd += ["password", password]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    return r.returncode == 0, (r.stderr or r.stdout).strip()


def known_connection(ssid):
    return ssid in _run("nmcli", "-t", "-f", "NAME", "connection").splitlines()


def airplane():
    return _run("nmcli", "radio", "all").strip().split(":")[-1:] == ["disabled"] or \
        "enabled" not in _run("nmcli", "-t", "radio", "all")


def set_airplane(on):
    _run("nmcli", "radio", "all", "off" if on else "on")


def bluetooth():
    """None when there is no adapter, else True/False for powered."""
    if not shutil.which("bluetoothctl"):
        return None
    out = _run("bluetoothctl", "show", timeout=3)
    if "Controller" not in out:
        return None
    return "Powered: yes" in out


def set_bluetooth(on):
    _run("bluetoothctl", "power", "on" if on else "off")


def volume():
    """-> (0..100, muted) or None"""
    out = _run("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@")
    m = re.search(r"([\d.]+)", out)
    if not m:
        return None
    return int(round(float(m.group(1)) * 100)), "MUTED" in out


def set_volume(pct):
    _run("wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{max(0, min(100, pct)) / 100:.2f}")


def toggle_mute():
    _run("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle")


def volume_icon():
    v = volume()
    if not v:
        return "audio-volume-muted-symbolic"
    pct, muted = v
    if muted or pct == 0:
        return "audio-volume-muted-symbolic"
    return "audio-volume-" + ("high" if pct > 66 else "medium" if pct > 33 else "low") + "-symbolic"


def brightness():
    if not shutil.which("brightnessctl"):
        return None
    out = _run("brightnessctl", "-m", "-c", "backlight")
    parts = out.strip().split(",")
    if len(parts) >= 4 and parts[3].endswith("%"):
        return int(parts[3][:-1])
    return None


def set_brightness(pct):
    _run("brightnessctl", "-q", "-c", "backlight", "set", f"{max(1, pct)}%")


def battery():
    """-> (percent, charging) or None"""
    for b in sorted(glob.glob("/sys/class/power_supply/BAT*")):
        try:
            cap = int(open(os.path.join(b, "capacity")).read().strip())
            status = open(os.path.join(b, "status")).read().strip()
            return cap, status in ("Charging", "Full")
        except (OSError, ValueError):
            continue
    return None


def battery_icon():
    b = battery()
    if not b:
        return None
    cap, charging = b
    level = min(100, (cap + 5) // 10 * 10)
    return f"battery-level-{level}{'-charging' if charging else ''}-symbolic"


def power(action):
    cmds = {
        "lock": ["foundation-lock"],
        "sleep": ["systemctl", "suspend"],
        "signout": ["labwc", "--exit"],
        "restart": ["systemctl", "reboot"],
        "shutdown": ["systemctl", "poweroff"],
    }
    subprocess.Popen(cmds[action], start_new_session=True)


def is_live():
    try:
        return "boot=casper" in open("/proc/cmdline").read().split()
    except OSError:
        return False


def updates_count():
    out = _run("fpkg", "updates", "--count", timeout=20).strip()
    return int(out) if out.isdigit() else 0
