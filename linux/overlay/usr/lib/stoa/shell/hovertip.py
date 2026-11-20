"""Hover labels for the taskbar, drawn by Stoa instead of GTK tooltips.

GTK3 tooltips on Wayland are pop-ups that can't be moved, so GTK destroys and re-creates them while the pointer
travels, re-checking on every motion event. With a 1000 Hz gaming mouse that floods the compositor and the
pointer lags over the taskbar and menus. These labels appear once after a pause, never follow the pointer, and
take no input at all.
"""
import cairo
import gi

gi.require_version("GtkLayerShell", "0.1")
from gi.repository import GLib, Gtk, GtkLayerShell  # noqa: E402

import theme  # noqa: E402

DELAY_MS = 550


class HoverTip:
    def __init__(self, bottom_margin, left_offset):
        self.bottom, self.left = bottom_margin, left_offset
        self.win = None
        self.timer = None
        self.owner = None

    def _build(self):
        w = Gtk.Window()
        w.set_title("stoa-hovertip")
        theme.transparent(w)
        GtkLayerShell.init_for_window(w)
        GtkLayerShell.set_namespace(w, "stoa-hovertip")
        GtkLayerShell.set_layer(w, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(w, GtkLayerShell.KeyboardMode.NONE)
        GtkLayerShell.set_exclusive_zone(w, -1)
        for e in (GtkLayerShell.Edge.BOTTOM, GtkLayerShell.Edge.LEFT):
            GtkLayerShell.set_anchor(w, e, True)
        GtkLayerShell.set_margin(w, GtkLayerShell.Edge.BOTTOM, self.bottom)
        box = theme.css(Gtk.Box(), "fs-glass", "fs-hovertip")
        self.label = Gtk.Label()
        self.label.set_xalign(0)
        box.pack_start(self.label, False, False, 0)
        w.add(box)
        # Never take the pointer: clicks and motion go straight through to whatever is underneath.
        w.connect("realize", lambda win: win.input_shape_combine_region(cairo.Region()))
        self.win = w

    def attach(self, widget, text):
        """Show `text` (a string, or a function returning one) when the pointer rests on `widget`."""
        widget.stoa_tip = text
        if getattr(widget, "stoa_tip_attached", False):
            return
        widget.stoa_tip_attached = True
        widget.connect("enter-notify-event", self._enter)
        widget.connect("leave-notify-event", self._leave)
        widget.connect("button-press-event", self._leave)
        widget.connect("destroy", self._leave)

    def _enter(self, widget, _ev=None):
        self._cancel()
        self.owner = widget
        self.timer = GLib.timeout_add(DELAY_MS, self._show, widget)
        return False

    def _leave(self, widget, _ev=None):
        if widget is self.owner:
            self.hide()
        return False

    def _cancel(self):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None

    def _show(self, widget):
        self.timer = None
        if widget is not self.owner or not widget.get_mapped():
            return False
        text = widget.stoa_tip() if callable(widget.stoa_tip) else widget.stoa_tip
        if not text:
            return False
        if self.win is None:
            self._build()
        # One line per item, long window titles shortened (no wrapping: it squeezed labels to one word per line).
        self.label.set_text("\n".join(line if len(line) <= 60 else line[:57] + "…" for line in text.splitlines()))
        top = widget.get_toplevel()
        x, _y = widget.translate_coordinates(top, 0, 0)
        self.win.show_all()
        width = self.win.get_preferred_width()[1]
        centre = self.left + x + widget.get_allocated_width() // 2
        try:
            from gi.repository import Gdk
            screen_w = Gdk.Display.get_default().get_monitor_at_window(top.get_window()).get_geometry().width
        except Exception:  # noqa: BLE001
            screen_w = 1 << 16
        GtkLayerShell.set_margin(self.win, GtkLayerShell.Edge.LEFT,
                                 max(4, min(centre - width // 2, screen_w - width - 4)))
        return False

    def hide(self):
        self._cancel()
        self.owner = None
        if self.win is not None:
            self.win.hide()
