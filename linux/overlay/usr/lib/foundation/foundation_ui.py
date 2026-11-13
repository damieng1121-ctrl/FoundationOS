"""Shared look & helpers for Foundation's GTK apps."""
import os
import subprocess

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

ACCENT = "#4f8cff"
CSS = b"""
window.background { background-color: #121829; color: #e8ecf5; }
.f-dark { background: #121829; color: #e8ecf5; }
.f-panel { background: #161d2e; color: #e8ecf5; border-radius: 14px; border: 1px solid #2a3550; }
.f-header { background: linear-gradient(135deg, #1e3a7a, #4f3f9c); color: white; border-radius: 14px 14px 0 0; padding: 18px; }
.f-title { font-size: 20px; font-weight: 800; }
.f-subtitle { color: #c9d3ea; }
.f-muted { color: #8a93aa; }
.f-h2 { font-size: 15px; font-weight: 700; }
.f-search { background: #0d1322; color: #ffffff; border: 1px solid #2a3550; border-radius: 10px; padding: 8px 12px; font-size: 14px; }
.f-app { background: transparent; color: #e8ecf5; border: none; border-radius: 10px; padding: 8px; }
.f-app:hover, .f-app:focus { background: #2a3550; }
.f-primary { background: #4f8cff; color: white; border: none; border-radius: 8px; padding: 6px 16px; font-weight: 700; }
.f-primary:hover { background: #3b6fe0; }
.f-green { background: #3fb37f; color: white; border: none; border-radius: 8px; padding: 6px 16px; font-weight: 700; }
.f-danger { background: #8c2f39; color: white; border: none; border-radius: 8px; padding: 6px 16px; }
.f-ghost { background: #232c44; color: #e8ecf5; border: none; border-radius: 8px; padding: 6px 14px; }
.f-ghost:hover { background: #2f3e60; }
.f-card { background: #1a2238; border-radius: 12px; border: 1px solid #263150; padding: 14px; }
.f-badge { background: #263150; color: #9ab4ff; border-radius: 6px; padding: 1px 8px; font-size: 11px; }
.f-side row { padding: 10px 14px; color: #c9d3ea; }
.f-side row:selected { background: #2a3550; color: white; border-radius: 8px; }
.f-log { font-family: monospace; font-size: 12px; background: #0d1117; color: #c9d1d9; }
.f-log text { background: #0d1117; color: #c9d1d9; }
"""


def apply_css():
    p = Gtk.CssProvider()
    p.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), p, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    s = Gtk.Settings.get_default()
    if s:
        s.set_property("gtk-application-prefer-dark-theme", True)


def css(widget, *classes):
    ctx = widget.get_style_context()
    for c in classes:
        ctx.add_class(c)
    return widget


def fit_size(width, height, margin=60):
    """Requested window size, shrunk to fit the current screen (small VM windows, netbooks)."""
    try:
        disp = Gdk.Display.get_default()
        mon = disp.get_primary_monitor() or disp.get_monitor(0)
        geo = mon.get_workarea()
        return max(320, min(width, geo.width - margin)), max(240, min(height, geo.height - margin))
    except Exception:  # noqa: BLE001
        return width, height


def is_live():
    try:
        with open("/proc/cmdline") as f:
            return "boot=casper" in f.read().split()
    except OSError:
        return False


def spawn(*cmd):
    subprocess.Popen(list(cmd), start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def logo_image(size=40):
    from gi.repository import GdkPixbuf
    pb = GdkPixbuf.Pixbuf.new_from_file_at_size("/usr/share/foundation/logo-white.png", size, size)
    return Gtk.Image.new_from_pixbuf(pb)


class CommandRunner(Gtk.Dialog):
    """Runs a command, streaming its output into a log view."""

    def __init__(self, parent, title, cmd, on_done=None):
        super().__init__(title=title, transient_for=parent, modal=True)
        self.set_default_size(720, 420)
        self.on_done = on_done
        box = self.get_content_area()
        box.set_spacing(10)
        box.set_border_width(12)
        self.status = Gtk.Label(label=title + "…", xalign=0)
        css(self.status, "f-h2")
        box.pack_start(self.status, False, False, 0)
        self.spinner = Gtk.ProgressBar()
        self.spinner.pulse()
        box.pack_start(self.spinner, False, False, 0)
        sw = Gtk.ScrolledWindow()
        sw.set_vexpand(True)
        self.view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        css(self.view, "f-log")
        sw.add(self.view)
        box.pack_start(sw, True, True, 0)
        self.close_btn = self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.close_btn.set_sensitive(False)
        self.connect("response", lambda *a: self.destroy())
        self.show_all()
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
        GLib.io_add_watch(self.proc.stdout, GLib.IO_IN | GLib.IO_HUP, self._read)
        self._pulse = GLib.timeout_add(120, lambda: (self.spinner.pulse(), True)[1])

    def _read(self, src, cond):
        line = src.readline()
        if line:
            buf = self.view.get_buffer()
            text = line.decode(errors="replace")
            import re
            text = re.sub(r"\x1b\[[0-9;]*m", "", text)
            buf.insert(buf.get_end_iter(), text)
            self.view.scroll_to_iter(buf.get_end_iter(), 0, False, 0, 0)
            return True
        rc = self.proc.wait()
        GLib.source_remove(self._pulse)
        self.spinner.set_fraction(1.0)
        self.status.set_text("Done" if rc == 0 else f"Failed (exit code {rc})")
        self.close_btn.set_sensitive(True)
        if self.on_done:
            self.on_done(rc)
        return False
