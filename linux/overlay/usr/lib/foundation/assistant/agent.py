"""Foundation AI: the agent loop (Claude API + tools that act on Foundation OS).

The UI talks to Agent through callbacks; every callback is invoked from the worker thread,
so the UI must hop back to the GTK main loop itself.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading

sys.path.insert(0, "/usr/lib/foundation/vendor")
sys.path.insert(0, os.environ.get("FOUNDATION_SHELL_DIR", "/usr/lib/foundation/shell"))

import anthropic  # noqa: E402

MODEL = "claude-opus-5-5"
HOME = os.path.expanduser("~")
CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.join(HOME, ".config")), "foundation")
CONFIG = os.path.join(CONFIG_DIR, "assistant.json")
DATA = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.join(HOME, ".local/share")))
APPS_DIR = os.path.join(DATA, "foundation", "ai-apps")
DESKTOP_DIR = os.path.join(DATA, "applications")

ICONS = ["accessories-calculator", "accessories-text-editor", "office-calendar", "appointment-soon",
         "applications-games", "applications-graphics", "applications-multimedia", "applications-science",
         "applications-education", "applications-utilities", "applications-office", "accessories-dictionary",
         "weather-few-clouds", "internet-web-browser", "folder", "help-browser", "emblem-favorite",
         "x-office-spreadsheet", "media-playback-start", "preferences-desktop"]

SYSTEM_PROMPT = """You are Foundation AI, the assistant built into Foundation OS - a desktop operating system \
designed around giving people exactly what they need, when they need it.

You can act on the computer with your tools: build apps, install software, open apps, change \
settings (volume, Wi-Fi, Bluetooth, airplane mode, brightness) and read system information. Use a tool \
whenever it gets the person what they asked for; don't just describe how they could do it themselves.

Building apps
- When someone asks for a tool, utility, tracker, calculator, game, dashboard or anything else that \
doesn't already exist on their computer, build it with build_app. They watch it being written and it \
opens as soon as it's ready, so keep the chat message before the build to one short sentence.
- An app is a single self-contained HTML file: inline CSS and JavaScript, no external scripts, fonts, \
images or CDNs, and no network requests unless the person explicitly asks for live online data. \
Persist the person's data with localStorage so it survives restarts.
- Make it polished and finished, never a stub: a complete, working feature set, keyboard support where \
natural, sensible empty states, and input validation.
- Match Foundation's look: dark navy background (#121829), panels #1a2238 with 1px rgba(255,255,255,0.08) \
borders and 12-16px rounded corners, text #e9edf7, muted text #8f9bb7, accent #4f8cff, secondary accent \
#7a4fe0, success #3fb37f, danger #e0567a, font-family "Inter", "Noto Sans", sans-serif. Layout must adapt \
to window sizes from 420px to 1600px wide.
- To change an app you built before, call read_app first, then build_app again with the same name and \
the complete updated HTML.

Software and settings
- For well-known software (browsers, Office, Zoom, Spotify...), search_software first to find the exact \
catalog id, then install_software. The person is asked to approve every installation.
- Windows programs can be installed from a downloaded .exe/.msi with install_software too.

Style: friendly, brief and plain-spoken. British English. No markdown tables. After a tool finishes, \
say in one or two sentences what happened and what the person can do next."""

TOOLS = [
    {
        "name": "build_app",
        "description": "Create (or replace) an app for the person and open it immediately. The app is a single "
                       "self-contained HTML file with inline CSS/JS. It is added to the Start menu. Re-using an "
                       "existing name replaces that app.",
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Short app name shown in Start, e.g. 'Pomodoro Timer'"},
                "description": {"type": "string", "description": "One sentence describing the app"},
                "icon": {"type": "string", "enum": ICONS, "description": "Icon for the Start menu"},
                "html": {"type": "string", "description": "The complete HTML document"},
            },
            "required": ["name", "description", "icon", "html"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_apps",
        "description": "List the apps Foundation AI has built for this person.",
        "eager_input_streaming": True,
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "read_app",
        "description": "Return the current HTML of an app Foundation AI built, so it can be modified.",
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": {"app_id": {"type": "string", "description": "The id from list_apps"}},
            "required": ["app_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "delete_app",
        "description": "Delete an app Foundation AI built (asks the person to confirm).",
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": {"app_id": {"type": "string"}},
            "required": ["app_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_software",
        "description": "Search the Foundation Store catalog (browsers, Microsoft 365, Google apps, Zoom, Spotify, "
                       "games, developer tools, Windows apps...). Returns catalog ids.",
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "install_software",
        "description": "Install software: a catalog id from search_software, 'flatpak:<app-id>', 'apt:<package>', "
                       "or the full path of a downloaded .exe/.msi/.deb/.AppImage/.fpkg file. The person must "
                       "approve, and may be asked for their password.",
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": {"target": {"type": "string"}},
            "required": ["target"],
            "additionalProperties": False,
        },
    },
    {
        "name": "open_app",
        "description": "Open an installed app by name (e.g. 'File Explorer', 'Notepad', 'Google Chrome').",
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "change_setting",
        "description": "Change a system setting. volume/brightness take 0-100; wifi/bluetooth/airplane_mode take "
                       "'on' or 'off'.",
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "setting": {"type": "string", "enum": ["volume", "brightness", "wifi", "bluetooth", "airplane_mode"]},
                "value": {"type": "string"},
            },
            "required": ["setting", "value"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_system_info",
        "description": "Foundation version, memory, disk space, network, battery and uptime.",
        "eager_input_streaming": True,
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]

REQUIRED = {t["name"]: t["input_schema"].get("required", []) for t in TOOLS}


def load_key():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    try:
        with open(CONFIG) as f:
            return json.load(f).get("api_key") or None
    except (OSError, ValueError):
        return None


def save_key(key):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    fd = os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"api_key": key.strip()}, f)


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "app"


def strip_ansi(s):
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


class Agent:
    def __init__(self, ui):
        self.ui = ui
        self.messages = []
        self.busy = False
        self.client = None

    # ------------------------------------------------------------------ lifecycle
    def ready(self):
        key = load_key()
        if not key:
            return False
        self.client = anthropic.Anthropic(api_key=key, max_retries=3)
        return True

    def reset(self):
        self.messages = []

    def send(self, text):
        if self.busy or not self.client:
            return
        self.busy = True
        self.messages.append({"role": "user", "content": text})
        threading.Thread(target=self._run, daemon=True).start()

    # ------------------------------------------------------------------ agent loop
    def _run(self):
        try:
            self._loop()
        except anthropic.AuthenticationError:
            self.ui.on_error("That API key wasn't accepted. Open the menu (⋯) and choose 'Change API key'.")
        except anthropic.PermissionDeniedError:
            self.ui.on_error("This API key doesn't have access to the model Foundation AI uses.")
        except anthropic.RateLimitError:
            self.ui.on_error("Foundation AI is busy right now (rate limited). Try again in a minute.")
        except anthropic.APIStatusError as e:
            self.ui.on_error(f"The AI service returned an error ({e.status_code}). Try again shortly.")
        except anthropic.APIConnectionError:
            self.ui.on_error("Can't reach the AI service. Check your internet connection.")
        finally:
            self.busy = False
            self.ui.on_done()

    def _loop(self):
        json_retries = 0
        while True:
            try:
                with self.client.beta.messages.stream(
                    model=MODEL,
                    max_tokens=64000,
                    system=SYSTEM_PROMPT,
                    tools=TOOLS,
                    messages=self.messages,
                    output_config={"effort": "medium"},
                    cache_control={"type": "ephemeral"},
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                ) as stream:
                    current_tool = None
                    chars = 0
                    for event in stream:
                        if event.type == "content_block_start":
                            if event.content_block.type == "tool_use":
                                current_tool, chars = event.content_block.name, 0
                                self.ui.on_tool_start(current_tool)
                            elif event.content_block.type == "text":
                                self.ui.on_text_start()
                        elif event.type == "text":
                            self.ui.on_text(event.text)
                        elif event.type == "input_json":
                            chars += len(event.partial_json)
                            self.ui.on_tool_progress(current_tool, chars, event.partial_json)
                    response = stream.get_final_message()
                json_retries = 0
            except ValueError:
                # Tool input the SDK could not parse at all: re-issue the turn (bounded).
                json_retries += 1
                if json_retries > 2:
                    self.ui.on_error("Foundation AI produced an unreadable response. Please try again.")
                    return
                continue

            if response.stop_reason == "refusal":
                self.ui.on_error("Foundation AI can't help with that request.")
                return
            if response.stop_reason == "pause_turn":
                self.messages.append({"role": "assistant", "content": response.content})
                continue

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            self.messages.append({"role": "assistant", "content": response.content})
            if not tool_uses:
                return
            if response.stop_reason == "max_tokens":
                self.ui.on_error("That was too big to finish in one go. Try asking for a smaller version.")
                self.messages.pop()
                return

            results = []
            for block in tool_uses:
                args = block.input if isinstance(block.input, dict) else None
                missing = [k for k in REQUIRED.get(block.name, []) if not isinstance((args or {}).get(k), str)]
                if args is None or missing:
                    results.append({"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                                    "content": json.dumps({"INVALID_JSON": json.dumps(block.input)})})
                    continue
                try:
                    out = self._execute(block.name, args)
                    is_error = False
                except Exception as e:  # noqa: BLE001 - report tool failures back to the model
                    out, is_error = f"Error: {e}", True
                self.ui.on_tool_done(block.name, args, out, is_error)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": out,
                                **({"is_error": True} if is_error else {})})
            self.messages.append({"role": "user", "content": results})

    # ------------------------------------------------------------------ tools
    def _execute(self, name, a):
        return getattr(self, "t_" + name)(a)

    def t_build_app(self, a):
        app_id = slug(a["name"])
        d = os.path.join(APPS_DIR, app_id)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as f:
            f.write(a["html"])
        icon = a["icon"] if a["icon"] in ICONS else "applications-utilities"
        with open(os.path.join(d, "app.json"), "w") as f:
            json.dump({"id": app_id, "name": a["name"], "description": a["description"], "icon": icon}, f)
        os.makedirs(DESKTOP_DIR, exist_ok=True)
        with open(os.path.join(DESKTOP_DIR, f"foundation-ai-{app_id}.desktop"), "w") as f:
            f.write("[Desktop Entry]\nType=Application\n"
                    f"Name={a['name']}\nComment={a['description']}\nIcon={icon}\n"
                    f"Exec=foundation-ai-app {app_id}\nStartupWMClass=foundation-ai-{app_id}\n"
                    "Categories=Utility;\nKeywords=foundation;ai;\nX-Foundation-AI-App=true\n")
        subprocess.Popen(["foundation-ai-app", app_id], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"Built '{a['name']}' (app id {app_id}, {len(a['html']):,} characters). It is open now and in the Start menu."

    def t_list_apps(self, a):
        apps = []
        if os.path.isdir(APPS_DIR):
            for app_id in sorted(os.listdir(APPS_DIR)):
                try:
                    with open(os.path.join(APPS_DIR, app_id, "app.json")) as f:
                        apps.append(json.load(f))
                except (OSError, ValueError):
                    continue
        return json.dumps(apps) if apps else "No apps built yet."

    def _app_dir(self, app_id):
        d = os.path.realpath(os.path.join(APPS_DIR, slug(app_id)))
        if not d.startswith(os.path.realpath(APPS_DIR) + os.sep) or not os.path.isdir(d):
            raise ValueError(f"no app with id '{app_id}'")
        return d

    def t_read_app(self, a):
        with open(os.path.join(self._app_dir(a["app_id"]), "index.html"), encoding="utf-8") as f:
            return f.read()

    def t_delete_app(self, a):
        d = self._app_dir(a["app_id"])
        if not self.ui.ask_approval(f"Delete the app '{os.path.basename(d)}' and its saved data?", "Delete"):
            return "The person chose not to delete it."
        shutil.rmtree(d)
        p = os.path.join(DESKTOP_DIR, f"foundation-ai-{os.path.basename(d)}.desktop")
        if os.path.exists(p):
            os.remove(p)
        return "Deleted."

    def t_search_software(self, a):
        r = subprocess.run(["fpkg", "search", a["query"]], capture_output=True, text=True, timeout=30)
        out = strip_ansi(r.stdout).strip()
        return out or "Nothing in the catalog matched. Try another word, or install_software with flatpak:<id> or apt:<package>."

    def t_install_software(self, a):
        target = a["target"].strip()
        if not self.ui.ask_approval(f"Install {target}?", "Install"):
            return "The person declined the installation."
        r = subprocess.run(["fpkg", "install", "-y", target], capture_output=True, text=True, timeout=3600)
        tail = "\n".join(strip_ansi(r.stdout + r.stderr).strip().splitlines()[-15:])
        if r.returncode != 0:
            raise RuntimeError(f"installation failed (exit {r.returncode}):\n{tail}")
        return f"Installed.\n{tail}"

    def t_open_app(self, a):
        import apps
        want = a["name"].lower()
        best = None
        for app in apps.all_apps():
            n = app.get_name().lower()
            if n == want:
                best = app
                break
            if want in n or n in want:
                best = best or app
        if not best:
            raise ValueError(f"no installed app called '{a['name']}'")
        apps.launch(best)
        return f"Opened {best.get_name()}."

    def t_change_setting(self, a):
        import system
        s, v = a["setting"], a["value"].strip().lower()
        on = v in ("on", "true", "yes", "1", "enable", "enabled")
        if s in ("volume", "brightness"):
            pct = int(re.sub(r"[^0-9]", "", v) or 0)
            (system.set_volume if s == "volume" else system.set_brightness)(pct)
            return f"{s.title()} set to {pct}%."
        {"wifi": system.set_wifi, "bluetooth": system.set_bluetooth, "airplane_mode": system.set_airplane}[s](on)
        return f"{s.replace('_', ' ').title()} turned {'on' if on else 'off'}."

    def t_get_system_info(self, a):
        def sh(*c):
            try:
                return subprocess.run(c, capture_output=True, text=True, timeout=10).stdout.strip()
            except OSError:
                return ""
        ver = sh("sh", "-c", ". /etc/os-release; echo $PRETTY_NAME")
        import system
        bat = system.battery()
        kind, net, _ = system.network()
        return "\n".join([
            f"System: {ver} (Linux {os.uname().release})",
            f"Uptime: {sh('uptime', '-p')}",
            f"Memory:\n{sh('free', '-h')}",
            f"Disk (/):\n{sh('df', '-h', '/')}",
            f"Network: {kind} {net}".strip(),
            f"Battery: {bat[0]}%{' charging' if bat[1] else ''}" if bat else "Battery: none (desktop or VM)",
        ])
