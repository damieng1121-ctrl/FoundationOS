"""Stoa AI: the agent loop (any supported AI provider + tools that act on Stoa).

Providers: Claude (Anthropic SDK), and ChatGPT / Gemini / Ollama / any OpenAI-compatible service
(OpenAI SDK with a base URL). The tools are the same for every provider.

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

sys.path.insert(0, "/usr/lib/stoa/vendor")
sys.path.insert(0, os.environ.get("STOA_SHELL_DIR", "/usr/lib/stoa/shell"))

import anthropic  # noqa: E402

try:
    import openai  # noqa: E402
except ImportError:  # pragma: no cover - only Claude is available then
    openai = None

MODEL = "claude-opus-5-5"

PROVIDERS = {
    "claude": {"label": "Claude (Anthropic)", "kind": "anthropic", "base_url": None, "needs_key": True,
               "model": MODEL, "key_hint": "sk-ant-…", "key_url": "https://console.anthropic.com/",
               "privacy": "What you type is sent to Anthropic."},
    "openai": {"label": "ChatGPT (OpenAI)", "kind": "openai", "base_url": None, "needs_key": True,
               "model": "gpt-5", "key_hint": "sk-…", "key_url": "https://platform.openai.com/api-keys",
               "privacy": "What you type is sent to OpenAI."},
    "gemini": {"label": "Gemini (Google AI Studio)", "kind": "openai",
               "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "needs_key": True,
               "model": "gemini-2.5-flash", "key_hint": "AIza…", "key_url": "https://aistudio.google.com/apikey",
               "privacy": "What you type is sent to Google."},
    "ollama": {"label": "On this computer (Ollama)", "kind": "openai", "base_url": "http://localhost:11434/v1",
               "needs_key": False, "model": "llama3.1", "key_hint": "", "key_url": "https://ollama.com/download",
               "privacy": "Everything stays on this computer. Needs Ollama and a downloaded model."},
    "custom": {"label": "Other OpenAI-compatible service", "kind": "openai", "base_url": "", "needs_key": True,
               "model": "", "key_hint": "API key", "key_url": "",
               "privacy": "What you type is sent to the service you enter."},
}
HOME = os.path.expanduser("~")
CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.join(HOME, ".config")), "stoa")
CONFIG = os.path.join(CONFIG_DIR, "assistant.json")
DATA = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.join(HOME, ".local/share")))
APPS_DIR = os.path.join(DATA, "stoa", "ai-apps")
DESKTOP_DIR = os.path.join(DATA, "applications")

ICONS = ["accessories-calculator", "accessories-text-editor", "office-calendar", "appointment-soon",
         "applications-games", "applications-graphics", "applications-multimedia", "applications-science",
         "applications-education", "applications-utilities", "applications-office", "accessories-dictionary",
         "weather-few-clouds", "internet-web-browser", "folder", "help-browser", "emblem-favorite",
         "x-office-spreadsheet", "media-playback-start", "preferences-desktop"]

SYSTEM_PROMPT = """You are Stoa AI, the assistant built into Stoa - a desktop operating system \
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
- Match Stoa's look: dark navy background (#121829), panels #1a2238 with 1px rgba(255,255,255,0.08) \
borders and 12-16px rounded corners, text #e9edf7, muted text #8f9bb7, accent #4f8cff, secondary accent \
#7a4fe0, success #3fb37f, danger #e0567a, font-family "Inter", "Noto Sans", sans-serif. Layout must adapt \
to window sizes from 420px to 1600px wide.
- To change an app you built before, call read_app first, then build_app again with the same name and \
the complete updated HTML.

Software and settings
- For well-known software (browsers, Office, Zoom, Spotify...), search_software first to find the exact \
catalog id, then install_software. The person is asked to approve every installation.
- Games: Steam (most Windows games run through Proton), Heroic (Epic, GOG, Amazon), Lutris \
(Battle.net, EA app, Ubisoft Connect) and graphics-drivers (NVIDIA cards need it) are in the catalog. Be \
honest that some online games - mainly competitive shooters and MMOs whose anti-cheat blocks Linux, such \
as Valorant, Fortnite, Destiny 2 and Rainbow Six Siege - won't run, and suggest checking protondb.com or \
areweanticheatyet.com for a specific title.
- Windows programs can be installed from a downloaded .exe/.msi with install_software too.

Style: friendly, brief and plain-spoken. British English. No markdown tables. After a tool finishes, \
say in one or two sentences what happened and what the person can do next."""

TOOLS = [
    {
        "name": "build_app",
        "description": "Create (or replace) an app for the person and open it immediately. The app is a single "
                       "self-contained HTML file with inline CSS/JS. It is added to the Stoa menu. Re-using an "
                       "existing name replaces that app.",
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Short app name shown in Start, e.g. 'Pomodoro Timer'"},
                "description": {"type": "string", "description": "One sentence describing the app"},
                "icon": {"type": "string", "enum": ICONS, "description": "Icon for the Stoa menu"},
                "html": {"type": "string", "description": "The complete HTML document"},
            },
            "required": ["name", "description", "icon", "html"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_apps",
        "description": "List the apps Stoa AI has built for this person.",
        "eager_input_streaming": True,
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "read_app",
        "description": "Return the current HTML of an app Stoa AI built, so it can be modified.",
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
        "description": "Delete an app Stoa AI built (asks the person to confirm).",
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
        "description": "Search the Stoa Store catalog (browsers, Microsoft 365, Google apps, Zoom, Spotify, "
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
        "description": "Open an installed app by name (e.g. 'Files', 'Text Editor', 'Google Chrome').",
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
        "description": "Stoa version, memory, disk space, network, battery and uptime.",
        "eager_input_streaming": True,
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]

REQUIRED = {t["name"]: t["input_schema"].get("required", []) for t in TOOLS}


def load_config():
    """{"provider", "api_key", "model", "base_url"} - or None when Stoa AI isn't set up."""
    cfg = {}
    try:
        with open(CONFIG) as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        cfg = {}
    if not cfg.get("api_key") and os.environ.get("ANTHROPIC_API_KEY"):
        cfg = {"provider": "claude", "api_key": os.environ["ANTHROPIC_API_KEY"]}
    if not cfg:
        return None
    cfg.setdefault("provider", "claude")  # configs from before providers existed
    prov = PROVIDERS.get(cfg["provider"])
    if not prov or (prov["needs_key"] and not cfg.get("api_key")):
        return None
    if prov["kind"] == "openai" and not cfg.get("model"):
        return None
    return cfg


def save_config(provider, api_key="", model="", base_url=""):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    fd = os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"provider": provider, "api_key": api_key.strip(), "model": model.strip(),
                   "base_url": base_url.strip()}, f)


def openai_client(provider, api_key, base_url=""):
    if openai is None:
        raise RuntimeError("the OpenAI SDK isn't installed")
    url = base_url or PROVIDERS[provider]["base_url"]
    return openai.OpenAI(api_key=api_key or "ollama", base_url=url or None, max_retries=3)


def list_models(provider, api_key, base_url=""):
    """Model ids the provider offers, for the setup screen (raises on auth/network errors)."""
    if PROVIDERS[provider]["kind"] == "anthropic":
        return [MODEL]
    ids = sorted({m.id for m in openai_client(provider, api_key, base_url).models.list()})
    if provider == "openai":  # hide embeddings, audio, image and moderation models
        ids = [i for i in ids if re.match(r"^(gpt|o\d|chatgpt)", i) and not re.search(
            r"(audio|realtime|transcribe|tts|image|embedding|moderation|search)", i)]
    if provider == "gemini":
        ids = [i for i in ids if "gemini" in i and "embedding" not in i]
    return ids


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
        self.provider = None
        self.model = MODEL

    # ------------------------------------------------------------------ lifecycle
    def ready(self):
        cfg = load_config()
        if not cfg:
            return False
        provider = cfg["provider"]
        if provider != self.provider:
            self.messages = []  # conversation formats differ between providers
        self.provider = provider
        if PROVIDERS[provider]["kind"] == "anthropic":
            self.client = anthropic.Anthropic(api_key=cfg["api_key"], max_retries=3)
            self.model = MODEL
        else:
            self.client = openai_client(provider, cfg.get("api_key", ""), cfg.get("base_url", ""))
            self.model = cfg["model"]
        return True

    def describe(self):
        if not self.provider:
            return ""
        label = PROVIDERS[self.provider]["label"].split(" (")[0]
        return label if self.provider == "claude" else f"{label} · {self.model}"

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
            if PROVIDERS[self.provider]["kind"] == "anthropic":
                self._loop()
            else:
                self._run_openai()
        except anthropic.AuthenticationError:
            self.ui.on_error("That API key wasn't accepted. Open the menu (⋯) and choose 'Change API key'.")
        except anthropic.PermissionDeniedError:
            self.ui.on_error("This API key doesn't have access to the model Stoa AI uses.")
        except anthropic.RateLimitError:
            self.ui.on_error("Stoa AI is busy right now (rate limited). Try again in a minute.")
        except anthropic.APIStatusError as e:
            self.ui.on_error(f"The AI service returned an error ({e.status_code}). Try again shortly.")
        except anthropic.APIConnectionError:
            self.ui.on_error("Can't reach the AI service. Check your internet connection.")
        finally:
            self.busy = False
            self.ui.on_done()

    def _run_openai(self):
        try:
            self._loop_openai()
        except openai.AuthenticationError:
            self.ui.on_error("That API key wasn't accepted. Open the menu (⋯) and choose 'Change AI provider'.")
        except openai.NotFoundError:
            self.ui.on_error(f"The model '{self.model}' wasn't found. Choose another in 'Change AI provider'.")
        except openai.RateLimitError:
            self.ui.on_error("The AI service is busy or your plan's limit was reached. Try again shortly.")
        except openai.APIStatusError as e:
            self.ui.on_error(f"The AI service returned an error ({e.status_code}). Try again shortly.")
        except openai.APIConnectionError:
            if self.provider == "ollama":
                self.ui.on_error("Can't reach Ollama on this computer. Is it installed and running?")
            else:
                self.ui.on_error("Can't reach the AI service. Check your internet connection.")

    def _loop_openai(self):
        """Tool loop for OpenAI-format chat completions (ChatGPT, Gemini, Ollama, others)."""
        tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                   "parameters": t["input_schema"]}} for t in TOOLS]
        while True:
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}] + self.messages,
                tools=tools,
                stream=True,
            )
            text, calls, finish, started = "", {}, None, False
            for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if delta and delta.content:
                    if not started:
                        self.ui.on_text_start()
                        started = True
                    text += delta.content
                    self.ui.on_text(delta.content)
                for tc in (delta.tool_calls or []) if delta else []:
                    idx = tc.index if tc.index is not None else len(calls)
                    c = calls.setdefault(idx, {"id": "", "name": "", "args": ""})
                    if tc.id:
                        c["id"] = tc.id
                    if tc.function and tc.function.name and not c["name"]:
                        c["name"] = tc.function.name
                        self.ui.on_tool_start(c["name"])
                    if tc.function and tc.function.arguments:
                        c["args"] += tc.function.arguments
                        self.ui.on_tool_progress(c["name"], len(c["args"]), tc.function.arguments)
                if choice.finish_reason:
                    finish = choice.finish_reason

            ordered = [calls[i] for i in sorted(calls)]
            for i, c in enumerate(ordered):
                c["id"] = c["id"] or f"call_{len(self.messages)}_{i}"
            assistant = {"role": "assistant", "content": text or None}
            if ordered:
                assistant["tool_calls"] = [{"id": c["id"], "type": "function",
                                            "function": {"name": c["name"], "arguments": c["args"] or "{}"}}
                                           for c in ordered]
            self.messages.append(assistant)
            if not ordered:
                return
            if finish == "length":
                self.ui.on_error("That was too big to finish in one go. Try asking for a smaller version.")
                self.messages.pop()
                return

            for c in ordered:
                try:
                    args = json.loads(c["args"] or "{}")
                except ValueError:
                    args = None
                missing = [k for k in REQUIRED.get(c["name"], []) if not isinstance((args or {}).get(k), str)]
                if not isinstance(args, dict) or missing or not hasattr(self, "t_" + c["name"]):
                    self.messages.append({"role": "tool", "tool_call_id": c["id"],
                                          "content": json.dumps({"INVALID_JSON": c["args"][:2000]})})
                    continue
                try:
                    out, is_error = self._execute(c["name"], args), False
                except Exception as e:  # noqa: BLE001 - report tool failures back to the model
                    out, is_error = f"Error: {e}", True
                self.ui.on_tool_done(c["name"], args, out, is_error)
                self.messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})

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
                    self.ui.on_error("Stoa AI produced an unreadable response. Please try again.")
                    return
                continue

            if response.stop_reason == "refusal":
                self.ui.on_error("Stoa AI can't help with that request.")
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
        with open(os.path.join(DESKTOP_DIR, f"stoa-ai-{app_id}.desktop"), "w") as f:
            f.write("[Desktop Entry]\nType=Application\n"
                    f"Name={a['name']}\nComment={a['description']}\nIcon={icon}\n"
                    f"Exec=stoa-ai-app {app_id}\nStartupWMClass=stoa-ai-{app_id}\n"
                    "Categories=Utility;\nKeywords=stoa;ai;\nX-Stoa-AI-App=true\n")
        subprocess.Popen(["stoa-ai-app", app_id], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"Built '{a['name']}' (app id {app_id}, {len(a['html']):,} characters). It is open now and in the Stoa menu."

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
        p = os.path.join(DESKTOP_DIR, f"stoa-ai-{os.path.basename(d)}.desktop")
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
