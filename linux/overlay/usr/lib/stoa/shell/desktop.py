"""The Stoa desktop: wallpaper, desktop icons and the desktop context menu."""
import os
import shutil
import subprocess

import gi

gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, GtkLayerShell, Pango  # noqa: E402

import apps  # noqa: E402
import theme  # noqa: E402

CELL_W, CELL_H = 96, 104
DEFAULT_WALLPAPER = "/usr/share/stoa/wallpaper.jpg"


def wallpaper_path():
    f = os.path.join(GLib.get_user_config_dir(), "stoa", "wallpaper")
    try:
        p = open(f).read().strip()
        if os.path.exists(p):
            return p
    except OSError:
        pass
    return DEFAULT_WALLPAPER


def desktop_dir():
    d = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DESKTOP) or os.path.expanduser("~/Desktop")
    os.makedirs(d, exist_ok=True)
    return d


class Item:
    def __init__(self, name, gicon, open_fn, path=None, system=False):
        self.name, self.gicon, self.open_fn, self.path, self.system = name, gicon, open_fn, path, system


class Desktop(Gtk.Window):
    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.set_title("stoa-desktop")
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "stoa-desktop")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.BACKGROUND)
        for e in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM, GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, e, True)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)

        self.overlay = Gtk.Overlay()
        self.add(self.overlay)
        self.canvas = Gtk.DrawingArea()
        self.canvas.connect("draw", self._draw)
        self.canvas.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.canvas.connect("button-press-event", self._bg_press)
        self.overlay.add(self.canvas)
        self.fixed = Gtk.Fixed()
        self.fixed.set_halign(Gtk.Align.START)
        self.fixed.set_valign(Gtk.Align.START)
        self.overlay.add_overlay(self.fixed)
        self.overlay.set_overlay_pass_through(self.fixed, False)

        self._pix = None
        self._pix_size = None
        self.selected = None
        self.load_wallpaper()
        self.connect("size-allocate", lambda w, a: self._layout())
        mon = Gio.File.new_for_path(desktop_dir()).monitor_directory(Gio.FileMonitorFlags.NONE, None)
        mon.connect("changed", lambda *a: GLib.timeout_add(300, self._refresh_once))
        self._mon = mon
        self._pending = False
        self.refresh()

    # ---------------------------------------------------------------- wallpaper
    def load_wallpaper(self):
        try:
            self._src = GdkPixbuf.Pixbuf.new_from_file(wallpaper_path())
        except GLib.Error:
            self._src = GdkPixbuf.Pixbuf.new_from_file(DEFAULT_WALLPAPER)
        self._pix = None
        self.canvas.queue_draw()

    def _draw(self, w, cr):
        alloc = w.get_allocation()
        size = (alloc.width, alloc.height)
        if self._pix is None or self._pix_size != size:
            sw, sh = self._src.get_width(), self._src.get_height()
            scale = max(size[0] / sw, size[1] / sh)
            nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
            scaled = self._src.scale_simple(nw, nh, GdkPixbuf.InterpType.BILINEAR)
            self._pix = scaled
            self._pix_off = ((size[0] - nw) // 2, (size[1] - nh) // 2)
            self._pix_size = size
        Gdk.cairo_set_source_pixbuf(cr, self._pix, *self._pix_off)
        cr.paint()
        return False

    # ---------------------------------------------------------------- icons
    def _items(self):
        home = os.path.expanduser("~")
        docs = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOCUMENTS) or os.path.join(home, "Documents")
        items = [
            Item("This PC", Gio.ThemedIcon.new("computer"), lambda: apps.run_command("thunar /"), system=True),
            Item("Documents", Gio.ThemedIcon.new("folder-documents"), lambda: apps.run_command(f"thunar {GLib.shell_quote(docs)}"), system=True),
            Item("Recycle Bin", Gio.ThemedIcon.new("user-trash-full" if self._trash_full() else "user-trash"),
                 lambda: apps.run_command("thunar trash:///"), system=True),
        ]
        store = apps.app("stoa-store.desktop")
        if store:
            items.append(Item("Stoa Store", apps.icon_for(store), lambda: apps.launch(store), system=True))
        d = desktop_dir()
        for name in sorted(os.listdir(d), key=str.lower):
            if name.startswith("."):
                continue
            p = os.path.join(d, name)
            if name.endswith(".desktop"):
                a = Gio.DesktopAppInfo.new_from_filename(p)
                if a:
                    items.append(Item(a.get_name(), apps.icon_for(a), lambda a=a: apps.launch(a), path=p))
                    continue
            f = Gio.File.new_for_path(p)
            try:
                info = f.query_info("standard::icon,standard::display-name", Gio.FileQueryInfoFlags.NONE, None)
                gicon, label = info.get_icon(), info.get_display_name()
            except GLib.Error:
                gicon, label = Gio.ThemedIcon.new("text-x-generic"), name
            items.append(Item(label, gicon, lambda p=p: Gio.AppInfo.launch_default_for_uri(
                Gio.File.new_for_path(p).get_uri(), None), path=p))
        return items

    def _trash_full(self):
        t = os.path.join(GLib.get_user_data_dir(), "Trash", "files")
        return os.path.isdir(t) and bool(os.listdir(t))

    def _refresh_once(self):
        self.refresh()
        return False

    def refresh(self):
        for c in self.fixed.get_children():
            c.destroy()
        self.items = self._items()
        self.buttons = []
        for it in self.items:
            ev = theme.css(Gtk.EventBox(), "fs-desk-icon")
            ev.set_visible_window(False)
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            v.set_size_request(CELL_W - 8, CELL_H - 8)
            frame = theme.css(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4), "fs-desk-icon")
            img = Gtk.Image.new_from_gicon(it.gicon, Gtk.IconSize.DIALOG)
            img.set_pixel_size(48)
            frame.pack_start(img, False, False, 2)
            lbl = theme.css(Gtk.Label(label=it.name, max_width_chars=12, lines=2, wrap=True,
                                      wrap_mode=Pango.WrapMode.WORD_CHAR, ellipsize=Pango.EllipsizeMode.END,
                                      justify=Gtk.Justification.CENTER), "fs-desk-label")
            frame.pack_start(lbl, False, False, 0)
            v.pack_start(frame, False, False, 0)
            ev.add(v)
            ev.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
            ev.connect("button-press-event", self._item_press, it, frame)
            ev.frame = frame
            self.fixed.put(ev, 0, 0)
            self.buttons.append(ev)
        self._layout()
        self.fixed.show_all()

    def _layout(self):
        h = self.get_allocated_height() or 800
        rows = max(1, (h - 90) // CELL_H)
        for i, b in enumerate(getattr(self, "buttons", [])):
            self.fixed.move(b, 12 + (i // rows) * CELL_W, 12 + (i % rows) * CELL_H)

    def _select(self, frame):
        if self.selected:
            self.selected.get_style_context().remove_class("fs-selected")
        self.selected = frame
        if frame:
            frame.get_style_context().add_class("fs-selected")

    def _item_press(self, w, ev, it, frame):
        self._select(frame)
        if ev.type == Gdk.EventType._2BUTTON_PRESS and ev.button == 1:
            it.open_fn()
            self._select(None)
        elif ev.button == 3:
            m = Gtk.Menu()
            o = Gtk.MenuItem(label="Open")
            o.connect("activate", lambda *_: it.open_fn())
            m.append(o)
            if it.name == "Recycle Bin":
                e = Gtk.MenuItem(label="Empty Recycle Bin")
                e.connect("activate", lambda *_: (apps.run_command("gio trash --empty"),
                                                   GLib.timeout_add(800, self._refresh_once)))
                m.append(e)
            if it.path:
                d = Gtk.MenuItem(label="Delete")
                d.connect("activate", lambda *_: (Gio.File.new_for_path(it.path).trash(None), self.refresh()))
                m.append(d)
            m.show_all()
            m.popup_at_pointer(ev)
        return True

    # ---------------------------------------------------------------- background menu
    def _bg_press(self, w, ev):
        self._select(None)
        if ev.button != 3:
            return False
        d = desktop_dir()
        m = Gtk.Menu()

        def add(label, fn):
            it = Gtk.MenuItem(label=label)
            it.connect("activate", lambda *_: fn())
            m.append(it)

        def new_folder():
            n, i = os.path.join(d, "New folder"), 2
            while os.path.exists(n):
                n, i = os.path.join(d, f"New folder ({i})"), i + 1
            os.makedirs(n)

        def new_text():
            n, i = os.path.join(d, "New Text Document.txt"), 2
            while os.path.exists(n):
                n, i = os.path.join(d, f"New Text Document ({i}).txt"), i + 1
            open(n, "w").close()

        add("Refresh", self.refresh)
        m.append(Gtk.SeparatorMenuItem())
        add("New folder", new_folder)
        add("New text document", new_text)
        m.append(Gtk.SeparatorMenuItem())
        add("Open in Terminal", lambda: apps.run_command(f"foot --working-directory={GLib.shell_quote(d)}"))
        add("Open Desktop folder", lambda: apps.run_command(f"thunar {GLib.shell_quote(d)}"))
        m.append(Gtk.SeparatorMenuItem())
        add("Display settings", lambda: apps.run_command("stoa-settings display"))
        add("Personalise", lambda: apps.run_command("stoa-settings personalise"))
        m.show_all()
        m.popup_at_pointer(ev)
        return True
