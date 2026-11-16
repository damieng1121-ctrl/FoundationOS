"""The Stoa bar: a floating glass bar with the Stoa menu, search, apps, status and clock."""
import datetime

import gi

gi.require_version("GtkLayerShell", "0.1")
from gi.repository import GdkPixbuf, GLib, Gtk, GtkLayerShell  # noqa: E402

import apps  # noqa: E402
import system  # noqa: E402
import theme  # noqa: E402
from flyouts import bg  # noqa: E402
from windows import Windows  # noqa: E402

BAR_HEIGHT = 52
MARGIN = 8


def sym(name, size=18):
    img = Gtk.Image.new_from_icon_name(name, Gtk.IconSize.BUTTON)
    img.set_pixel_size(size)
    return img


class Taskbar(Gtk.Window):
    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.set_title("stoa-taskbar")
        theme.transparent(self)
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "stoa-taskbar")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        for e in (GtkLayerShell.Edge.BOTTOM, GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, e, True)
            GtkLayerShell.set_margin(self, e, MARGIN)
        GtkLayerShell.set_exclusive_zone(self, BAR_HEIGHT + MARGIN)
        self.set_size_request(-1, BAR_HEIGHT)

        bar = theme.css(Gtk.Box(), "fs-glass", "fs-taskbar")
        self.add(bar)

        # Left: Start + search
        left = Gtk.Box(spacing=6)
        start = theme.css(Gtk.Button(), "fs-tb-btn", "fs-start")
        pb = GdkPixbuf.Pixbuf.new_from_file_at_size("/usr/share/stoa/logo-round-96.png", 34, 34)
        start.add(Gtk.Image.new_from_pixbuf(pb))
        start.set_tooltip_text("Stoa menu (Super+Space)")
        start.set_valign(Gtk.Align.CENTER)
        start.connect("clicked", lambda *_: shell.start.toggle())
        left.pack_start(start, False, False, 0)
        search = theme.css(Gtk.Button(), "fs-tb-btn", "fs-search-pill")
        sb = Gtk.Box(spacing=8)
        sb.pack_start(sym("system-search-symbolic", 16), False, False, 0)
        sb.pack_start(Gtk.Label(label="Search", xalign=0), False, False, 0)
        search.add(sb)
        search.connect("clicked", lambda *_: shell.start.open_search())
        left.pack_start(search, False, False, 0)
        self.search_pill = search
        ai = theme.css(Gtk.Button(label="✦"), "fs-tb-btn", "fs-ai")
        ai.set_tooltip_text("Stoa AI (Super+C)")
        ai.set_valign(Gtk.Align.CENTER)
        ai.set_size_request(38, 38)
        ai.connect("clicked", lambda *_: apps.run_command("stoa-assistant"))
        left.pack_start(ai, False, False, 0)
        bar.pack_start(left, False, False, 0)

        # Centre: apps
        self.app_box = Gtk.Box(spacing=2)
        bar.set_center_widget(self.app_box)

        # Right: install (live), updates, status pill, clock
        right = Gtk.Box(spacing=4)
        if system.is_live():
            inst = theme.css(Gtk.Button(label="Install Stoa"), "fs-qs-tile", "fs-install")
            inst.connect("clicked", lambda *_: apps.run_command("stoa-installer"))
            right.pack_start(inst, False, False, 4)
        self.upd = theme.css(Gtk.Button(), "fs-tb-btn")
        self.upd.add(sym("software-update-available-symbolic", 18))
        self.upd.connect("clicked", lambda *_: apps.run_command("stoa-updates"))
        self.upd.set_no_show_all(True)
        right.pack_start(self.upd, False, False, 0)

        status = theme.css(Gtk.Button(), "fs-tb-btn", "fs-pill")
        sbox = Gtk.Box(spacing=10)
        self.i_net = sym("network-wired-symbolic")
        self.i_vol = sym("audio-volume-high-symbolic")
        self.i_bat = sym("battery-level-100-symbolic")
        self.i_bat.set_no_show_all(True)
        for i in (self.i_net, self.i_vol, self.i_bat):
            sbox.pack_start(i, False, False, 0)
        status.add(sbox)
        status.set_tooltip_text("Quick settings")
        status.connect("clicked", lambda *_: shell.quick.toggle())
        status.connect("scroll-event", self._scroll_volume)
        right.pack_start(status, False, False, 0)

        clock = theme.css(Gtk.Button(), "fs-tb-btn", "fs-pill")
        cbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.l_time = theme.css(Gtk.Label(xalign=1), "fs-clock-time")
        self.l_date = theme.css(Gtk.Label(xalign=1), "fs-clock-date")
        cbox.pack_start(self.l_time, False, False, 0)
        cbox.pack_start(self.l_date, False, False, 0)
        clock.add(cbox)
        clock.connect("clicked", lambda *_: shell.calendar.toggle())
        right.pack_start(clock, False, False, 0)
        bar.pack_end(right, False, False, 0)

        self.cycle = {}
        self.windows = Windows(self.refresh_apps)
        self.refresh_apps()
        self._tick()
        GLib.timeout_add_seconds(1, self._tick)
        self._status()
        GLib.timeout_add_seconds(4, self._status)
        GLib.timeout_add_seconds(20, self._updates)
        GLib.timeout_add_seconds(1800, self._updates)
        self.connect("size-allocate", self._on_size)

    # ---------------------------------------------------------------- clock & status
    def _tick(self):
        now = datetime.datetime.now()
        self.l_time.set_text(now.strftime("%H:%M"))
        self.l_date.set_text(now.strftime("%d/%m/%Y"))
        return True

    def _status(self):
        def read():
            return system.network_icon(), system.volume_icon(), system.battery_icon(), system.network()

        def show(r):
            net, vol, bat, (kind, name, _) = r
            self.i_net.set_from_icon_name(net, Gtk.IconSize.BUTTON)
            self.i_vol.set_from_icon_name(vol, Gtk.IconSize.BUTTON)
            if bat:
                self.i_bat.set_from_icon_name(bat, Gtk.IconSize.BUTTON)
                self.i_bat.show()
            tip = {"wifi": f"Wi-Fi: {name}", "ethernet": f"Ethernet: {name}"}.get(kind, "Not connected")
            self.i_net.get_parent().get_parent().set_tooltip_text(tip + " · Quick settings")
        bg(read, show)
        return True

    def _updates(self):
        def show(n):
            self.upd.set_visible(n > 0)
            self.upd.set_tooltip_text(f"{n} update{'s' if n != 1 else ''} ready to install")
        bg(system.updates_count, show)
        return True

    def _scroll_volume(self, w, ev):
        from gi.repository import Gdk
        v = system.volume()
        if v:
            step = 5 if ev.direction == Gdk.ScrollDirection.UP else -5 if ev.direction == Gdk.ScrollDirection.DOWN else 0
            system.set_volume(v[0] + step)
            self.i_vol.set_from_icon_name(system.volume_icon(), Gtk.IconSize.BUTTON)
        return True

    def _on_size(self, w, alloc):
        self.search_pill.set_visible(alloc.width > 900)

    # ---------------------------------------------------------------- apps
    def refresh_apps(self):
        for c in self.app_box.get_children():
            c.destroy()
        groups = self.windows.by_app()
        entries = []  # (desktop_app or None, key, [windows])
        used = set()
        for a in apps.pins("taskbar"):
            ws = []
            for app_id, wl in groups.items():
                if app_id in used:
                    continue
                match = apps.for_app_id(app_id)
                if match and match.get_id() == a.get_id():
                    ws += wl
                    used.add(app_id)
            entries.append((a, a.get_id(), ws))
        for app_id, wl in groups.items():
            if app_id in used:
                continue
            entries.append((apps.for_app_id(app_id), app_id, wl))
        for a, key, ws in entries:
            self.app_box.pack_start(self._app_button(a, key, ws), False, False, 0)
        self.app_box.show_all()

    def _app_button(self, a, key, ws):
        b = theme.css(Gtk.Button(), "fs-tb-btn")
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        img = Gtk.Image.new_from_gicon(apps.icon_for(a), Gtk.IconSize.LARGE_TOOLBAR)
        img.set_pixel_size(26)
        v.pack_start(img, False, False, 0)
        dot = theme.css(Gtk.Box(), "fs-dot")
        dot.set_halign(Gtk.Align.CENTER)
        active = any(w.get("active") and not w.get("minimized") for w in ws)
        if active:
            dot.get_style_context().add_class("fs-active")
            b.get_style_context().add_class("fs-active")
        dot.set_opacity(1 if ws else 0)
        v.pack_start(dot, False, False, 0)
        b.add(v)
        title = (a.get_name() if a else key)
        if ws:
            title += "\n" + "\n".join("• " + (w.get("title") or "") for w in ws[:5])
        b.set_tooltip_text(title)
        b.connect("clicked", lambda *_: self._click(a, key, ws))
        b.connect("button-press-event", lambda w, e: self._press(e, a, key, ws))
        return b

    def _click(self, a, key, ws):
        if not ws:
            if a:
                apps.launch(a)
            return
        if len(ws) == 1:
            self.windows.send("toggle", ws[0]["id"])
            return
        i = (self.cycle.get(key, -1) + 1) % len(ws)
        self.cycle[key] = i
        self.windows.send("activate", ws[i]["id"])

    def _press(self, ev, a, key, ws):
        if ev.button == 2 and a:
            apps.launch(a)
            return True
        if ev.button != 3:
            return False
        m = Gtk.Menu()
        if a:
            open_new = Gtk.MenuItem(label=a.get_name() if not ws else "New window")
            open_new.connect("activate", lambda *_: apps.launch(a))
            m.append(open_new)
            pinned = apps.is_pinned("taskbar", a.get_id())
            p = Gtk.MenuItem(label="Unpin from bar" if pinned else "Pin to bar")
            p.connect("activate", lambda *_: (apps.set_pinned("taskbar", a.get_id(), not pinned), self.refresh_apps()))
            m.append(p)
        if ws:
            c = Gtk.MenuItem(label="Close window" if len(ws) == 1 else "Close all windows")
            c.connect("activate", lambda *_: [self.windows.send("close", w["id"]) for w in ws])
            m.append(c)
        m.show_all()
        m.popup_at_pointer(ev)
        return True
