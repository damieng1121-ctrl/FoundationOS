"""Applications: lookup, pinning, launching and matching windows to apps."""
import json
import os
import subprocess

from gi.repository import Gio, GLib

CONFIG = os.path.join(GLib.get_user_config_dir(), "stoa")
PINS_FILE = os.path.join(CONFIG, "pinned.json")
DEFAULT_TASKBAR_PINS = ["thunar.desktop", "org.gnome.Epiphany.desktop", "google-chrome.desktop",
                        "stoa-store.desktop", "org.codeberg.dnkl.foot.desktop"]
DEFAULT_START_PINS = ["stoa-assistant.desktop", "thunar.desktop", "org.gnome.Epiphany.desktop", "google-chrome.desktop",
                      "stoa-store.desktop", "stoa-settings.desktop", "org.xfce.mousepad.desktop",
                      "org.gnome.Calculator.desktop", "org.xfce.ristretto.desktop", "stoa-taskmgr.desktop",
                      "org.codeberg.dnkl.foot.desktop", "atril.desktop", "vlc.desktop", "fpkg-webapp-microsoft-word.desktop",
                      "fpkg-webapp-microsoft-excel.desktop", "fpkg-webapp-google-drive.desktop"]


def all_apps():
    seen, res = set(), []
    for a in Gio.AppInfo.get_all():
        if not a.should_show():
            continue
        key = a.get_name()
        if key in seen:
            continue
        seen.add(key)
        res.append(a)
    res.sort(key=lambda a: a.get_name().lower())
    return res


def app(desktop_id):
    try:
        return Gio.DesktopAppInfo.new(desktop_id)
    except TypeError:
        return None


def _load():
    try:
        with open(PINS_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def pins(kind):
    data = _load()
    default = DEFAULT_TASKBAR_PINS if kind == "taskbar" else DEFAULT_START_PINS
    ids = data.get(kind, default)
    out, seen = [], set()
    for i in ids:
        a = app(i)
        if a and i not in seen:
            seen.add(i)
            out.append(a)
    return out


def set_pinned(kind, desktop_id, pinned):
    data = _load()
    default = DEFAULT_TASKBAR_PINS if kind == "taskbar" else DEFAULT_START_PINS
    ids = list(data.get(kind, default))
    if pinned and desktop_id not in ids:
        ids.append(desktop_id)
    if not pinned and desktop_id in ids:
        ids.remove(desktop_id)
    data[kind] = ids
    os.makedirs(CONFIG, exist_ok=True)
    with open(PINS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def is_pinned(kind, desktop_id):
    return any(a.get_id() == desktop_id for a in pins(kind))


def launch(a):
    try:
        a.launch([], None)
    except GLib.Error:
        cmd = a.get_commandline() or ""
        if cmd:
            subprocess.Popen(cmd.split("%")[0].split(), start_new_session=True)


def run_command(cmd):
    subprocess.Popen(["sh", "-c", cmd], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


_wmclass_cache = {}


def for_app_id(app_id):
    """Best desktop entry for a window's app_id (Wayland) / WM_CLASS (X11)."""
    if not app_id:
        return None
    if app_id in _wmclass_cache:
        return _wmclass_cache[app_id]
    found = None
    for cand in (app_id, app_id.lower()):
        found = app(cand + ".desktop")
        if found:
            break
    if not found:
        low = app_id.lower()
        best, best_score = None, 0
        for a in Gio.AppInfo.get_all():
            if not isinstance(a, Gio.DesktopAppInfo):
                continue
            wm = (a.get_startup_wm_class() or "").lower()
            aid = (a.get_id() or "").lower().removesuffix(".desktop")
            exe = os.path.basename((a.get_executable() or "")).lower()
            score = 0
            if wm == low:
                score = 50
            elif aid == low or aid.endswith("." + low):
                score = 40
            elif exe == low:
                score = 30
            elif low in aid.split(".")[-1].split("-"):
                score = 10
            if not score:
                continue
            if a.should_show():
                score += 5
            if any(w in aid for w in ("settings", "preferences", "prefs", "server", "client")):
                score -= 8
            if score > best_score:
                best, best_score = a, score
        found = best
    _wmclass_cache[app_id] = found
    return found


_ICON_CACHE = {}


def sized_icon(gicon, size):
    """A Gtk.Image of exactly size x size pixels, whatever sizes the icon's files come in (cached)."""
    from gi.repository import Gtk
    key = (gicon.to_string() if gicon else "", size)
    pb = _ICON_CACHE.get(key)
    if pb is None:
        img = _sized_icon_uncached(gicon, size)
        pb = img.get_pixbuf()
        if pb is None:
            return img
        if len(_ICON_CACHE) > 400:
            _ICON_CACHE.clear()
        _ICON_CACHE[key] = pb
    img = Gtk.Image.new_from_pixbuf(pb)
    img.set_size_request(size, size)
    return img


def _sized_icon_uncached(gicon, size):
    from gi.repository import GdkPixbuf, Gtk
    theme = Gtk.IconTheme.get_default()
    pb = None
    try:
        info = theme.lookup_by_gicon(gicon, size, Gtk.IconLookupFlags.FORCE_SIZE) if gicon else None
        if info:
            pb = info.load_icon()
    except GLib.Error:
        pb = None
    if pb is None:
        try:
            pb = theme.load_icon("application-x-executable", size, Gtk.IconLookupFlags.FORCE_SIZE)
        except GLib.Error:
            return Gtk.Image.new_from_icon_name("application-x-executable", Gtk.IconSize.DIALOG)
    if pb.get_width() != size or pb.get_height() != size:
        pb = pb.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
    img = Gtk.Image.new_from_pixbuf(pb)
    img.set_size_request(size, size)
    return img


def icon_for(a, fallback="application-x-executable"):
    if a and a.get_icon():
        return a.get_icon()
    return Gio.ThemedIcon.new(fallback)
