"""Stoa Shell visual design: one stylesheet for every shell surface."""
from gi.repository import Gdk, Gtk

ACCENT = "#4f8cff"

CSS = b"""
/* No hover/press animations in the shell: each one redraws the bar or menu for ~200 ms per widget the pointer
   crosses, which made the pointer feel sluggish over the taskbar and menus on slower PCs. */
* { font-family: "Inter", "Noto Sans", sans-serif; transition: none; animation: none; }
window.fs-transparent, .fs-transparent { background-color: transparent; }
/* Our buttons draw their own look: drop the GTK theme's gradients, borders and shadows. */
button.fs-tb-btn, button.fs-qs-tile, button.fs-tile, button.fs-row, button.fs-link, button.fs-power-btn {
  background-image: none; border-image: none; box-shadow: none; text-shadow: none; outline-color: rgba(79,140,255,0.6);
}
button.fs-install { background-color: #3fb37f; color: white; font-weight: 700; border-radius: 12px; padding: 4px 14px; }
button.fs-install:hover { background-color: #34a06f; }

/* ---------- glass surfaces ---------- */
.fs-glass {
  background-color: rgba(17, 23, 39, 0.90);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  color: #e9edf7;
}
.fs-glass-strong { background-color: rgba(19, 25, 42, 0.985); }

/* ---------- taskbar ---------- */
.fs-taskbar { padding: 4px 6px; }
.fs-tb-btn {
  background: transparent; border: none; border-radius: 10px;
  padding: 4px 8px; min-height: 36px; min-width: 36px; color: #e9edf7;
  box-shadow: none; text-shadow: none;
}
.fs-tb-btn:hover { background-color: rgba(255, 255, 255, 0.08); }
.fs-tb-btn:active, .fs-tb-btn.fs-pressed { background-color: rgba(255, 255, 255, 0.14); }
.fs-tb-btn.fs-active { background-color: rgba(79, 140, 255, 0.18); }
button.fs-app { padding: 0; min-width: 46px; min-height: 44px; }
button.fs-start {
  border-radius: 50%; padding: 2px; min-width: 38px; min-height: 38px; margin: 0 4px;
  background-color: transparent;
}
button.fs-start:hover { background-color: rgba(122, 79, 224, 0.35); }
button.fs-start:active { background-color: rgba(122, 79, 224, 0.55); }
button.fs-ai {
  border-radius: 50%; min-width: 38px; min-height: 38px; padding: 0; font-size: 17px; font-weight: 800;
  color: white; background-image: linear-gradient(135deg, #4f8cff, #7a4fe0);
}
button.fs-ai:hover { background-image: linear-gradient(135deg, #6a9dff, #8e66ec); }
button.fs-ai.fs-busy { opacity: 0.6; }
.fs-search-pill {
  background-color: rgba(255, 255, 255, 0.07); border-radius: 18px; padding: 4px 14px;
  color: #aab4cc; min-width: 170px;
}
.fs-search-pill:hover { background-color: rgba(255, 255, 255, 0.12); }
.fs-dot { background-color: #8a96b3; border-radius: 2px; min-height: 3px; min-width: 6px; margin-bottom: 1px; }
.fs-dot.fs-active { background-color: #4f8cff; min-width: 16px; }
.fs-pill { border-radius: 12px; padding: 4px 12px; }
.fs-clock-time { font-weight: 700; font-size: 13px; }
.fs-clock-date { font-size: 11px; color: #aab4cc; }
.fs-status-label { font-size: 13px; }

/* ---------- desktop ---------- */
.fs-desk-icon {
  background: transparent; border-radius: 10px; padding: 8px 4px; border: 1px solid transparent;
}
.fs-desk-icon:hover { background-color: rgba(255, 255, 255, 0.10); }
.fs-desk-icon.fs-selected { background-color: rgba(79, 140, 255, 0.30); border-color: rgba(79, 140, 255, 0.6); }
.fs-desk-label { color: white; font-size: 12px; text-shadow: 0 1px 3px rgba(0,0,0,0.9); }

/* ---------- menus & flyouts ---------- */
.fs-h1 { font-size: 18px; font-weight: 800; color: #ffffff; }
.fs-h2 { font-size: 13px; font-weight: 700; color: #ffffff; }
.fs-muted { color: #8f9bb7; font-size: 12px; }
.fs-search {
  background-color: rgba(255,255,255,0.07); color: #ffffff; border: 1px solid rgba(255,255,255,0.10);
  border-radius: 22px; padding: 10px 16px; font-size: 14px; caret-color: #4f8cff; box-shadow: none;
}
.fs-search:focus { border-color: #4f8cff; }
.fs-tile {
  background: transparent; border: none; border-radius: 12px; padding: 10px 4px; color: #e9edf7;
  box-shadow: none;
}
.fs-tile:hover, .fs-tile:focus { background-color: rgba(255, 255, 255, 0.08); }
.fs-tile-label { font-size: 12px; }
.fs-link {
  background: rgba(255,255,255,0.06); border: none; border-radius: 8px; padding: 4px 12px;
  color: #e9edf7; font-size: 12px; box-shadow: none;
}
.fs-link:hover { background: rgba(255,255,255,0.12); }
.fs-row {
  background: transparent; border: none; border-radius: 8px; padding: 6px 10px; color: #e9edf7; box-shadow: none;
}
.fs-row:hover, .fs-row:focus { background-color: rgba(255,255,255,0.08); }
.fs-letter { color: #4f8cff; font-weight: 800; font-size: 13px; padding: 10px 10px 2px 10px; }
.fs-footer { background-color: rgba(255,255,255,0.04); border-radius: 0 0 16px 16px; padding: 10px 18px; }
.fs-avatar { background-color: #4f8cff; color: white; border-radius: 18px; min-width: 36px; min-height: 36px;
  font-weight: 800; font-size: 15px; }
.fs-qs-tile {
  background-color: rgba(255,255,255,0.07); border: none; border-radius: 12px; padding: 10px 12px;
  color: #e9edf7; box-shadow: none; min-height: 44px;
}
.fs-qs-tile:hover { background-color: rgba(255,255,255,0.12); }
.fs-qs-tile.fs-on { background-color: #4f8cff; color: white; }
.fs-qs-tile.fs-on:hover { background-color: #3b6fe0; }
scale trough { background-color: rgba(255,255,255,0.15); border-radius: 4px; min-height: 4px; }
scale highlight { background-color: #4f8cff; border-radius: 4px; }
scale slider { background-color: #ffffff; border-radius: 10px; min-width: 18px; min-height: 18px; border: none;
  box-shadow: 0 1px 3px rgba(0,0,0,0.5); }
.fs-power-btn { background: transparent; border: none; border-radius: 18px; padding: 6px; box-shadow: none; color: #e9edf7; }
.fs-power-btn:hover { background-color: rgba(255,255,255,0.10); }
calendar { background: transparent; color: #e9edf7; border: none; padding: 4px; }
calendar:selected { background-color: #4f8cff; color: white; border-radius: 16px; }
calendar.header { color: white; }
calendar.button { color: #e9edf7; }
calendar:indeterminate { color: #55607a; }
.fs-big-time { font-size: 34px; font-weight: 300; color: white; }
.fs-big-date { font-size: 14px; color: #aab4cc; }
menu, .menu { background-color: #161d2e; color: #e9edf7; border-radius: 10px; padding: 6px; }
menuitem { padding: 6px 12px; border-radius: 6px; }
menuitem:hover { background-color: #2a3550; }
.fs-hovertip { padding: 6px 10px; border-radius: 8px; color: #e9edf7; font-size: 12px; }
"""


def apply():
    prov = Gtk.CssProvider()
    prov.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                             Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 10)
    settings = Gtk.Settings.get_default()
    if settings:
        settings.set_property("gtk-application-prefer-dark-theme", True)
        settings.set_property("gtk-enable-animations", False)


def css(widget, *classes):
    ctx = widget.get_style_context()
    for c in classes:
        ctx.add_class(c)
    return widget


def transparent(window):
    """Give a window an RGBA visual so rounded glass corners are see-through."""
    screen = window.get_screen()
    visual = screen.get_rgba_visual()
    if visual:
        window.set_visual(visual)
    window.set_app_paintable(True)
    css(window, "fs-transparent")
