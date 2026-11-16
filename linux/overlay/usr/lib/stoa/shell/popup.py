"""Base class for shell popups (Start, Quick Settings, Calendar, Run): glass panels above the
taskbar that close on Escape or when you click anywhere else."""
import gi

gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, Gtk, GtkLayerShell  # noqa: E402

import theme  # noqa: E402

TASKBAR_SPACE = 68


class Catcher(Gtk.Window):
    """Invisible full-screen surface under an open popup; a click on it closes the popup."""

    def __init__(self, on_click):
        super().__init__()
        theme.transparent(self)
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        for e in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM, GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, e, True)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_namespace(self, "stoa-catcher")
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("button-press-event", lambda *a: (on_click(), True)[1])
        self.connect("draw", self._draw)

    def _draw(self, w, cr):
        cr.set_source_rgba(0, 0, 0, 0.01)  # (nearly) invisible but still receives input
        cr.paint()
        return False


class Popup(Gtk.Window):
    current = None

    def __init__(self, name, width, height, h_anchor="left", margin=8):
        super().__init__()
        self.set_title(name)
        theme.transparent(self)
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, f"stoa-{name}")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        if h_anchor in ("left", "right"):
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT if h_anchor == "left" else GtkLayerShell.Edge.RIGHT, True)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT if h_anchor == "left" else GtkLayerShell.Edge.RIGHT, margin)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, TASKBAR_SPACE)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        self.set_size_request(width, -1)
        self.panel = theme.css(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "fs-glass", "fs-glass-strong")
        self.add(self.panel)
        self.connect("key-press-event", self._key)
        self.catcher = None
        self.max_height = height

    def _key(self, w, ev):
        if ev.keyval == Gdk.KEY_Escape:
            self.close_popup()
            return True
        return False

    def open_popup(self):
        if Popup.current and Popup.current is not self:
            Popup.current.close_popup()
        Popup.current = self
        self.catcher = Catcher(self.close_popup)
        self.catcher.show_all()
        self.on_open()
        self.show_all()
        self.after_show()
        self.present()

    def toggle(self):
        if self.get_visible():
            self.close_popup()
        else:
            self.open_popup()

    def close_popup(self):
        if self.catcher:
            self.catcher.destroy()
            self.catcher = None
        self.hide()
        if Popup.current is self:
            Popup.current = None

    def on_open(self):
        pass

    def after_show(self):
        pass
