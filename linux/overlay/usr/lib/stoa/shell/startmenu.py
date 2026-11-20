"""The Stoa menu."""
import re
import datetime
import os
import pwd
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urlparse

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

import apps
import system
import theme
from popup import Popup

COLS = 6


def app_icon(a, size=36):
    return apps.sized_icon(apps.icon_for(a), size)


def recent_files(limit=6):
    path = os.path.join(GLib.get_user_data_dir(), "recently-used.xbel")
    items = []
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return items
    for bm in root.findall("bookmark"):
        href = bm.get("href", "")
        if not href.startswith("file://"):
            continue
        p = unquote(urlparse(href).path)
        if not os.path.exists(p) or os.path.isdir(p):
            continue
        items.append((bm.get("modified") or bm.get("visited") or "", p))
    items.sort(reverse=True)
    return [p for _, p in items[:limit]]


def when(path):
    t = datetime.datetime.fromtimestamp(os.path.getmtime(path))
    d = (datetime.datetime.now() - t)
    if d.days == 0:
        return "Today, " + t.strftime("%H:%M")
    if d.days == 1:
        return "Yesterday"
    return t.strftime("%-d %b")


class StartMenu(Popup):
    def __init__(self, shell):
        super().__init__("start", 640, 700, h_anchor="left")
        self.shell = shell
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        body.set_border_width(22)
        self.search = theme.css(Gtk.SearchEntry(placeholder_text="Search apps, settings and files"), "fs-search")
        self.search.connect("search-changed", self._on_search)
        self.search.connect("activate", self._activate_first)
        body.pack_start(self.search, False, False, 0)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=120)
        self.stack.set_size_request(-1, 470)
        body.pack_start(self.stack, True, True, 0)
        self.panel.pack_start(body, True, True, 0)
        self.panel.pack_end(self._footer(), False, False, 0)

        self.home = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.stack.add_named(self.home, "home")
        self.all = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.stack.add_named(self.all, "all")
        self.results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.stack.add_named(self.results, "search")

    # ---------------------------------------------------------------- building
    def _section(self, title, link=None, cb=None):
        row = Gtk.Box()
        row.pack_start(theme.css(Gtk.Label(label=title, xalign=0), "fs-h2"), True, True, 0)
        if link:
            b = theme.css(Gtk.Button(label=link), "fs-link")
            b.connect("clicked", cb)
            row.pack_end(b, False, False, 0)
        return row

    def _tile(self, a):
        b = theme.css(Gtk.Button(), "fs-tile")
        b.set_size_request(94, 84)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        v.pack_start(app_icon(a, 36), False, False, 0)
        lbl = theme.css(Gtk.Label(label=a.get_name(), max_width_chars=10, ellipsize=Pango.EllipsizeMode.END,
                                  justify=Gtk.Justification.CENTER), "fs-tile-label")
        v.pack_start(lbl, False, False, 0)
        b.add(v)
        b.connect("clicked", lambda *_: self._launch(a))
        b.connect("button-press-event", lambda w, e: self._context(e, a))
        return b

    def _row(self, a, sub=None, size=24):
        b = theme.css(Gtk.Button(), "fs-row")
        h = Gtk.Box(spacing=12)
        h.pack_start(app_icon(a, size), False, False, 0)
        t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        t.pack_start(Gtk.Label(label=a.get_name(), xalign=0, ellipsize=Pango.EllipsizeMode.END), False, False, 0)
        if sub:
            t.pack_start(theme.css(Gtk.Label(label=sub, xalign=0, ellipsize=Pango.EllipsizeMode.END), "fs-muted"),
                         False, False, 0)
        h.pack_start(t, True, True, 0)
        b.add(h)
        b.connect("clicked", lambda *_: self._launch(a))
        b.connect("button-press-event", lambda w, e: self._context(e, a))
        return b

    def _build_home(self):
        for c in self.home.get_children():
            c.destroy()
        self.home.pack_start(self._section("Pinned", "All apps  ›", lambda *_: self._show_all()), False, False, 0)
        grid = Gtk.Grid(row_spacing=4, column_spacing=4)
        for i, a in enumerate(apps.pins("start")[:COLS * 3]):
            grid.attach(self._tile(a), i % COLS, i // COLS, 1, 1)
        self.home.pack_start(grid, False, False, 0)
        self.home.pack_start(self._section("Recommended"), False, False, 6)
        rec = Gtk.Grid(column_homogeneous=True, row_spacing=2, column_spacing=8)
        files = recent_files()
        if not files:
            rec.attach(theme.css(Gtk.Label(label="Files you open recently will appear here.", xalign=0), "fs-muted"),
                       0, 0, 2, 1)
        for i, p in enumerate(files):
            b = theme.css(Gtk.Button(), "fs-row")
            h = Gtk.Box(spacing=10)
            ct, _ = Gio.content_type_guess(p, None)
            img = apps.sized_icon(Gio.content_type_get_icon(ct), 28)
            h.pack_start(img, False, False, 0)
            t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            t.pack_start(Gtk.Label(label=os.path.basename(p), xalign=0, max_width_chars=24,
                                   ellipsize=Pango.EllipsizeMode.MIDDLE), False, False, 0)
            t.pack_start(theme.css(Gtk.Label(label=when(p), xalign=0), "fs-muted"), False, False, 0)
            h.pack_start(t, True, True, 0)
            b.add(h)
            b.connect("clicked", lambda _b, p=p: self._open_file(p))
            rec.attach(b, i % 2, i // 2, 1, 1)
        self.home.pack_start(rec, False, False, 0)

    def _build_all(self):
        for c in self.all.get_children():
            c.destroy()
        self.all.pack_start(self._section("All apps", "‹  Back", lambda *_: self.stack.set_visible_child_name("home")),
                            False, False, 0)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        lst = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        letter = None
        for a in apps.all_apps():
            first = a.get_name()[:1].upper()
            first = first if first.isalpha() else "#"
            if first != letter:
                letter = first
                lst.pack_start(theme.css(Gtk.Label(label=letter, xalign=0), "fs-letter"), False, False, 0)
            lst.pack_start(self._row(a), False, False, 0)
        sw.add(lst)
        self.all.pack_start(sw, True, True, 0)

    def _footer(self):
        foot = theme.css(Gtk.Box(spacing=12), "fs-footer")
        try:
            pw = pwd.getpwuid(os.getuid())
            name = (pw.pw_gecos.split(",")[0] or pw.pw_name)
        except KeyError:
            name = os.environ.get("USER", "User")
        av = theme.css(Gtk.Label(label=name[:1].upper()), "fs-avatar")
        user = Gtk.Box(spacing=10)
        user.pack_start(av, False, False, 0)
        user.pack_start(Gtk.Label(label=name, xalign=0), False, False, 0)
        ub = theme.css(Gtk.Button(), "fs-row")
        ub.add(user)
        ub.connect("clicked", lambda *_: self._run("stoa-settings accounts"))
        foot.pack_start(ub, False, False, 0)
        if system.is_live():
            inst = theme.css(Gtk.Button(label="Install Stoa"), "fs-qs-tile", "fs-install")
            inst.connect("clicked", lambda *_: self._run("stoa-installer"))
            foot.pack_start(inst, False, False, 0)
        pb = theme.css(Gtk.Button(), "fs-power-btn")
        img = Gtk.Image.new_from_icon_name("system-shutdown-symbolic", Gtk.IconSize.BUTTON)
        img.set_pixel_size(18)
        pb.add(img)
        pb.connect("clicked", lambda b: self.shell.power_menu(b))
        foot.pack_end(pb, False, False, 0)
        return foot

    # ---------------------------------------------------------------- behaviour
    def on_open(self):
        self.search.set_text("")
        self._build_home()
        self.stack.set_visible_child_name("home")

    def after_show(self):
        self.search.grab_focus()

    def open_search(self):
        self.open_popup()

    def _show_all(self):
        self._build_all()
        self.all.show_all()
        self.stack.set_visible_child_name("all")

    def _on_search(self, entry):
        q = entry.get_text().strip().lower()
        if not q:
            self.stack.set_visible_child_name("home")
            return
        for c in self.results.get_children():
            c.destroy()
        self.matches = []
        for a in apps.all_apps():
            hay = " ".join(filter(None, [a.get_name(), a.get_description() or "", a.get_id() or "",
                                         " ".join(a.get_keywords() if hasattr(a, "get_keywords") else [])])).lower()
            if q in hay:
                score = 0 if a.get_name().lower().startswith(q) else 1
                self.matches.append((score, a))
        self.matches.sort(key=lambda m: (m[0], m[1].get_name().lower()))
        self.results.pack_start(theme.css(Gtk.Label(label="Best matches" if self.matches else "No apps found",
                                                    xalign=0), "fs-h2"), False, False, 4)
        for _, a in self.matches[:8]:
            self.results.pack_start(self._row(a, a.get_description(), 28), False, False, 0)
        q_raw = entry.get_text().strip()
        ask = ("stoa-ai-symbolic" if Gtk.IconTheme.get_default().has_icon("stoa-ai-symbolic") else "starred-symbolic",
               f'Ask Stoa AI: "{q_raw}"',
               lambda: apps.run_command(f"stoa-assistant --ask {GLib.shell_quote(q_raw)}"))
        # A question or a request ("how do I...", "make me...", several words) is usually for Stoa AI.
        looks_like_request = q_raw.endswith("?") or len(q_raw.split()) >= 3 or bool(re.match(
            r"(?i)^(how|what|why|when|where|who|can|could|make|build|create|help|fix|install|find|show|turn|set|"
            r"write|explain|summari[sz]e)\b", q_raw))
        self.ask_first = looks_like_request and not self.matches
        extra = [
            ("system-search-symbolic", f'Search files for "{entry.get_text().strip()}"',
             lambda: apps.run_command(f"thunar --search {GLib.shell_quote(entry.get_text().strip())} 2>/dev/null"
                                      f" || thunar ~")),
            ("system-software-install-symbolic", f'Find "{entry.get_text().strip()}" in the Stoa Store',
             lambda: apps.run_command(f"stoa-store --search {GLib.shell_quote(entry.get_text().strip())}")),
        ]
        extra.insert(0 if looks_like_request else len(extra), ask)
        for icon_name, label, fn in extra:
            b = theme.css(Gtk.Button(), "fs-row")
            h = Gtk.Box(spacing=12)
            img = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.DND)
            img.set_pixel_size(24)
            h.pack_start(img, False, False, 0)
            h.pack_start(Gtk.Label(label=label, xalign=0, ellipsize=Pango.EllipsizeMode.END), True, True, 0)
            b.add(h)
            b.connect("clicked", lambda _b, fn=fn: (fn(), self.close_popup()))
            self.results.pack_start(b, False, False, 0)
        self.results.show_all()
        self.stack.set_visible_child_name("search")

    def _activate_first(self, *_):
        if self.stack.get_visible_child_name() == "search" and getattr(self, "matches", None):
            self._launch(self.matches[0][1])
        elif self.stack.get_visible_child_name() == "search" and getattr(self, "ask_first", False):
            apps.run_command(f"stoa-assistant --ask {GLib.shell_quote(self.search.get_text().strip())}")
            self.close_popup()

    def _launch(self, a):
        self.close_popup()
        apps.launch(a)

    def _run(self, cmd):
        self.close_popup()
        apps.run_command(cmd)

    def _open_file(self, p):
        self.close_popup()
        Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(p).get_uri(), None)

    def _context(self, ev, a):
        if ev.button != 3:
            return False
        m = Gtk.Menu()
        aid = a.get_id()
        for kind, on_label, off_label in [("start", "Unpin from Stoa menu", "Pin to Stoa menu"),
                                          ("taskbar", "Unpin from bar", "Pin to bar")]:
            pinned = apps.is_pinned(kind, aid)
            it = Gtk.MenuItem(label=on_label if pinned else off_label)
            it.connect("activate", lambda _i, k=kind, p=pinned: (apps.set_pinned(k, aid, not p),
                                                                  self._build_home(), self.home.show_all(),
                                                                  self.shell.taskbar.refresh_apps()))
            m.append(it)
        m.show_all()
        m.popup_at_pointer(ev)
        return True
