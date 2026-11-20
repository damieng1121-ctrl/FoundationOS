"""Open-window tracking through the stoa-toplevels helper."""
import json
import os
import shutil
import subprocess

from gi.repository import GLib

HELPER = shutil.which("stoa-toplevels") or "/usr/lib/stoa/stoa-toplevels"


class Windows:
    def __init__(self, on_change):
        self.on_change = on_change
        self.wins = {}  # id -> dict
        self.order = []  # ids, oldest first
        self.proc = None
        self._pending = None
        self._start()

    def _changed(self):
        # Wayland reports each window change as several events (title, app id, state, done); a busy app can
        # change its title many times a second. Coalesce them into one taskbar update every 150 ms at most.
        if self._pending is None:
            self._pending = GLib.timeout_add(150, self._flush)

    def _flush(self):
        self._pending = None
        self.on_change()
        return False

    def _start(self):
        if not os.path.exists(HELPER) and not shutil.which("stoa-toplevels"):
            return
        self.proc = subprocess.Popen([HELPER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.buf = b""
        GLib.unix_fd_add_full(GLib.PRIORITY_DEFAULT, self.proc.stdout.fileno(), GLib.IOCondition.IN | GLib.IOCondition.HUP,
                              self._read)

    def _read(self, fd, cond):
        # Read raw bytes: a buffered readline() would leave queued lines unprocessed.
        try:
            data = os.read(fd, 65536)
        except OSError:
            data = b""
        if not data:
            GLib.timeout_add_seconds(2, lambda: (self._start(), False)[1])
            return False
        self.buf += data
        *lines, self.buf = self.buf.split(b"\n")
        for line in lines:
            self._handle(line)
        return True

    def _handle(self, line):
        try:
            ev = json.loads(line)
        except ValueError:
            return
        if ev.get("ev") == "update":
            wid = ev["id"]
            if wid not in self.wins:
                self.order.append(wid)
            if self.wins.get(wid) == ev:
                return  # nothing actually changed
            self.wins[wid] = ev
            self._changed()
        elif ev.get("ev") == "closed":
            self.wins.pop(ev["id"], None)
            if ev["id"] in self.order:
                self.order.remove(ev["id"])
            self._changed()

    def send(self, op, wid):
        if self.proc and self.proc.stdin:
            try:
                self.proc.stdin.write(f"{op} {wid}\n")
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError):
                pass

    def by_app(self):
        groups = {}
        for wid in self.order:
            w = self.wins.get(wid)
            if w:
                groups.setdefault(w.get("app_id") or "unknown", []).append(w)
        return groups
