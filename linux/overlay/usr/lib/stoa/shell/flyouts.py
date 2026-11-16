"""Quick Settings, Calendar and Run flyouts."""
import datetime
import os
import shlex
import subprocess
import threading

from gi.repository import Gio, GLib, Gtk

import apps
import system
import theme
from popup import Popup


def icon(name, size=20):
    img = Gtk.Image.new_from_icon_name(name, Gtk.IconSize.BUTTON)
    img.set_pixel_size(size)
    return img


def bg(fn, done):
    """Run fn() in a thread and call done(result) on the main loop."""
    def work():
        r = fn()
        GLib.idle_add(lambda: (done(r), False)[1])
    threading.Thread(target=work, daemon=True).start()


class QuickSettings(Popup):
    def __init__(self, shell):
        super().__init__("quick-settings", 380, 520, h_anchor="right")
        self.shell = shell
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT, vhomogeneous=False)
        self.panel.pack_start(self.stack, True, True, 0)
        self._build_main()
        self._build_wifi()

    # ---------------------------------------------------------------- main page
    def _build_main(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        page.set_border_width(18)
        grid = Gtk.Grid(column_spacing=10, row_spacing=10, column_homogeneous=True)
        self.t_wifi = self._tile("network-wireless-symbolic", "Wi-Fi", self._toggle_wifi, more=self._show_wifi)
        self.t_bt = self._tile("bluetooth-active-symbolic", "Bluetooth", self._toggle_bt)
        self.t_air = self._tile("airplane-mode-symbolic", "Airplane mode", self._toggle_air)
        grid.attach(self.t_wifi, 0, 0, 1, 1)
        grid.attach(self.t_bt, 1, 0, 1, 1)
        grid.attach(self.t_air, 2, 0, 1, 1)
        page.pack_start(grid, False, False, 0)

        self.vol_row, self.vol_scale, self.vol_icon = self._slider("audio-volume-high-symbolic", system.set_volume,
                                                                   on_icon=system.toggle_mute)
        page.pack_start(self.vol_row, False, False, 0)
        self.bri_row, self.bri_scale, _ = self._slider("display-brightness-symbolic", system.set_brightness)
        page.pack_start(self.bri_row, False, False, 0)

        foot = theme.css(Gtk.Box(spacing=8), "fs-footer")
        self.batt = theme.css(Gtk.Label(xalign=0), "fs-muted")
        foot.pack_start(self.batt, True, True, 0)
        for name, tip, cb in [("emblem-system-symbolic", "All settings", lambda *_: self._run("stoa-settings")),
                              ("system-shutdown-symbolic", "Power", lambda b: self.shell.power_menu(b))]:
            b = theme.css(Gtk.Button(), "fs-power-btn")
            b.add(icon(name, 18))
            b.set_tooltip_text(tip)
            b.connect("clicked", cb)
            foot.pack_end(b, False, False, 0)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.pack_start(page, True, True, 0)
        outer.pack_end(foot, False, False, 0)
        self.stack.add_named(outer, "main")

    def _tile(self, icon_name, label, cb, more=None):
        box = Gtk.Box(spacing=0)
        b = theme.css(Gtk.Button(), "fs-qs-tile")
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        b.icon = icon(icon_name, 18)
        inner.pack_start(b.icon, False, False, 0)
        b.label = Gtk.Label(label=label, xalign=0.5, max_width_chars=11, ellipsize=3)
        theme.css(b.label, "fs-tile-label")
        inner.pack_start(b.label, False, False, 0)
        b.add(inner)
        b.connect("clicked", cb)
        b.title = label
        box.pack_start(b, True, True, 0)
        box.button = b
        if more:
            m = theme.css(Gtk.Button(label="›"), "fs-qs-tile")
            m.set_tooltip_text("Choose a network")
            m.connect("clicked", lambda *_: more())
            box.pack_start(m, False, False, 0)
            box.more = m
        return box

    def _slider(self, icon_name, setter, on_icon=None):
        row = Gtk.Box(spacing=10)
        ib = theme.css(Gtk.Button(), "fs-power-btn")
        ic = icon(icon_name, 18)
        ib.add(ic)
        if on_icon:
            ib.connect("clicked", lambda *_: (on_icon(), self.refresh()))
        row.pack_start(ib, False, False, 0)
        sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        sc.set_draw_value(False)
        sc.set_hexpand(True)
        sc.handler = sc.connect("value-changed", lambda s: setter(int(s.get_value())))
        row.pack_start(sc, True, True, 0)
        return row, sc, ic

    def _set_tile(self, box, on, sub=None):
        b = box.button
        ctx = b.get_style_context()
        (ctx.add_class if on else ctx.remove_class)("fs-on")
        if hasattr(box, "more"):
            (box.more.get_style_context().add_class if on else box.more.get_style_context().remove_class)("fs-on")
        b.label.set_text(sub or b.title)

    def refresh(self):
        def read():
            return {
                "wifi": system.wifi_enabled(), "has_wifi": system.has_wifi(), "net": system.network(),
                "bt": system.bluetooth(), "air": system.airplane(), "vol": system.volume(),
                "bri": system.brightness(), "bat": system.battery(),
            }

        def show(s):
            kind, name, _ = s["net"]
            self._set_tile(self.t_wifi, s["wifi"], name if kind == "wifi" else ("Wi-Fi" if s["has_wifi"] else "No Wi-Fi"))
            self.t_wifi.set_sensitive(s["has_wifi"])
            self.t_bt.set_visible(s["bt"] is not None)
            self._set_tile(self.t_bt, bool(s["bt"]))
            self._set_tile(self.t_air, s["air"])
            if s["vol"]:
                pct, muted = s["vol"]
                with_block(self.vol_scale, pct)
                self.vol_icon.set_from_icon_name(system.volume_icon(), Gtk.IconSize.BUTTON)
            self.vol_row.set_visible(s["vol"] is not None)
            self.bri_row.set_visible(s["bri"] is not None)
            if s["bri"] is not None:
                with_block(self.bri_scale, s["bri"])
            if s["bat"]:
                cap, ch = s["bat"]
                self.batt.set_text(f"Battery {cap}%" + (" · charging" if ch else ""))
            elif kind == "ethernet":
                self.batt.set_text(f"Connected · {name}")
            else:
                self.batt.set_text("Not connected" if kind == "none" else f"Connected to {name}")
        bg(read, show)

    def _toggle_wifi(self, *_):
        bg(lambda: system.set_wifi(not system.wifi_enabled()), lambda r: self.refresh())

    def _toggle_bt(self, *_):
        bg(lambda: system.set_bluetooth(not system.bluetooth()), lambda r: self.refresh())

    def _toggle_air(self, *_):
        bg(lambda: system.set_airplane(not system.airplane()), lambda r: self.refresh())

    def _run(self, cmd):
        self.close_popup()
        apps.run_command(cmd)

    # ---------------------------------------------------------------- wifi page
    def _build_wifi(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page.set_border_width(14)
        head = Gtk.Box(spacing=8)
        back = theme.css(Gtk.Button(label="‹"), "fs-link")
        back.connect("clicked", lambda *_: self.stack.set_visible_child_name("main"))
        head.pack_start(back, False, False, 0)
        head.pack_start(theme.css(Gtk.Label(label="Wi-Fi", xalign=0), "fs-h2"), True, True, 0)
        page.pack_start(head, False, False, 0)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_min_content_height(300)
        self.wifi_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        sw.add(self.wifi_list)
        page.pack_start(sw, True, True, 0)
        more = theme.css(Gtk.Button(label="More Wi-Fi and network settings"), "fs-link")
        more.connect("clicked", lambda *_: self._run("nm-connection-editor"))
        page.pack_end(more, False, False, 0)
        self.stack.add_named(page, "wifi")

    def _show_wifi(self):
        self.stack.set_visible_child_name("wifi")
        for c in self.wifi_list.get_children():
            c.destroy()
        self.wifi_list.add(theme.css(Gtk.Label(label="Looking for networks…", xalign=0), "fs-muted"))
        self.wifi_list.show_all()
        bg(system.wifi_networks, self._fill_wifi)

    def _fill_wifi(self, nets):
        for c in self.wifi_list.get_children():
            c.destroy()
        if not nets:
            self.wifi_list.add(theme.css(Gtk.Label(label="No networks found", xalign=0), "fs-muted"))
        for n in nets:
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            b = theme.css(Gtk.Button(), "fs-row")
            line = Gtk.Box(spacing=10)
            lvl = "excellent" if n["signal"] > 75 else "good" if n["signal"] > 50 else "ok" if n["signal"] > 25 else "weak"
            line.pack_start(icon(f"network-wireless-signal-{lvl}-symbolic", 18), False, False, 0)
            txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            txt.pack_start(Gtk.Label(label=n["ssid"], xalign=0), False, False, 0)
            status = "Connected" if n["active"] else ("Secured" if n["secure"] else "Open")
            txt.pack_start(theme.css(Gtk.Label(label=status, xalign=0), "fs-muted"), False, False, 0)
            line.pack_start(txt, True, True, 0)
            b.add(line)
            row.pack_start(b, False, False, 0)
            pw_box = Gtk.Box(spacing=6)
            pw = Gtk.Entry(visibility=False, placeholder_text="Password")
            go = theme.css(Gtk.Button(label="Connect"), "fs-qs-tile", "fs-on")
            pw_box.pack_start(pw, True, True, 0)
            pw_box.pack_start(go, False, False, 0)
            pw_box.set_no_show_all(True)
            row.pack_start(pw_box, False, False, 4)

            def connect(_w, n=n, pw=pw, pw_box=pw_box):
                if n["active"]:
                    return
                if n["secure"] and not system.known_connection(n["ssid"]) and not pw.get_text():
                    pw_box.show_all()
                    pw.grab_focus()
                    return
                b_label = pw.get_text() or None
                self.wifi_list.foreach(lambda c: c.set_sensitive(False))
                bg(lambda: system.wifi_connect(n["ssid"], b_label), self._connected)

            b.connect("clicked", connect)
            go.connect("clicked", connect)
            pw.connect("activate", connect)
            self.wifi_list.pack_start(row, False, False, 0)
        self.wifi_list.show_all()

    def _connected(self, res):
        ok, msg = res
        if ok:
            self.stack.set_visible_child_name("main")
            self.refresh()
        else:
            self._fill_wifi(system.wifi_networks())
            self.wifi_list.pack_start(theme.css(Gtk.Label(label=msg[:120], xalign=0, wrap=True), "fs-muted"),
                                      False, False, 4)
            self.wifi_list.show_all()

    def on_open(self):
        self.stack.set_visible_child_name("main")
        self.refresh()


def with_block(scale, value):
    scale.handler_block(scale.handler)
    scale.set_value(value)
    scale.handler_unblock(scale.handler)


class CalendarFlyout(Popup):
    def __init__(self, shell):
        super().__init__("calendar", 340, 420, h_anchor="right")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_border_width(18)
        self.time = theme.css(Gtk.Label(xalign=0), "fs-big-time")
        self.date = theme.css(Gtk.Label(xalign=0), "fs-big-date")
        box.pack_start(self.time, False, False, 0)
        box.pack_start(self.date, False, False, 0)
        self.cal = Gtk.Calendar()
        self.cal.set_margin_top(12)
        box.pack_start(self.cal, False, False, 0)
        self.panel.pack_start(box, True, True, 0)

    def on_open(self):
        now = datetime.datetime.now()
        self.time.set_text(now.strftime("%H:%M"))
        self.date.set_text(now.strftime("%A %-d %B %Y"))
        self.cal.select_month(now.month - 1, now.year)
        self.cal.select_day(now.day)


class RunDialog(Popup):
    def __init__(self, shell):
        super().__init__("run", 440, 160, h_anchor="left")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(18)
        box.pack_start(theme.css(Gtk.Label(label="Go To", xalign=0), "fs-h1"), False, False, 0)
        box.pack_start(theme.css(Gtk.Label(
            label="Type an app, folder, file or website and Stoa will take you there.",
            xalign=0, wrap=True, max_width_chars=48), "fs-muted"), False, False, 0)
        self.entry = theme.css(Gtk.Entry(placeholder_text="e.g. files, ~/Documents, stoa.app"), "fs-search")
        self.entry.connect("activate", self._go)
        box.pack_start(self.entry, False, False, 0)
        self.err = theme.css(Gtk.Label(xalign=0), "fs-muted")
        box.pack_start(self.err, False, False, 0)
        self.panel.pack_start(box, True, True, 0)

    # Stoa names first; common names from other systems also work for people switching over.
    ALIASES = {"files": "thunar", "editor": "mousepad", "text": "mousepad", "terminal": "foot",
               "settings": "stoa-settings", "store": "stoa-store", "monitor": "gnome-system-monitor",
               "ai": "stoa-assistant", "calculator": "gnome-calculator",
               "notepad": "mousepad", "explorer": "thunar", "cmd": "foot", "powershell": "foot",
               "control": "stoa-settings", "taskmgr": "gnome-system-monitor", "calc": "gnome-calculator",
               "mspaint": "stoa-store", "regedit": "stoa-settings", "winver": "stoa-settings about"}

    def on_open(self):
        self.err.set_text("")
        self.entry.set_text("")

    def after_show(self):
        self.entry.grab_focus()

    def _go(self, *_):
        text = os.path.expanduser(self.entry.get_text().strip())
        if not text:
            return
        if text.startswith(("http://", "https://", "www.")):
            target = text if "://" in text else "https://" + text
            Gio.AppInfo.launch_default_for_uri(target, None)
        elif os.path.exists(text):
            Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(text).get_uri(), None)
        else:
            word = text.split()[0].lower().removesuffix(".exe")
            cmd = self.ALIASES.get(word)
            if cmd:
                text = cmd
            elif not GLib.find_program_in_path(shlex.split(text)[0]):
                self.err.set_text(f"Stoa can't find '{text}'. Check the name and try again.")
                return
            apps.run_command(text)
        self.close_popup()
