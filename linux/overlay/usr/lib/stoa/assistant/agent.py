"""Stoa AI: the agent loop (any supported AI provider + tools that act on Stoa).

Providers: Claude (Anthropic SDK), and ChatGPT / Gemini / Ollama / any OpenAI-compatible service
(OpenAI SDK with a base URL). The tools are the same for every provider.

The UI talks to Agent through callbacks; every callback is invoked from the worker thread,
so the UI must hop back to the GTK main loop itself.
"""
import json
import urllib.request
import time
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
    "local": {"label": "Stoa AI Local - on this PC, private", "kind": "openai",
              "base_url": "http://127.0.0.1:8089/v1", "needs_key": False, "local": True,
              "model": "stoa-local", "key_hint": "", "key_url": "",
              "privacy": "Runs entirely on this PC: nothing you type leaves it, and it works offline. Needs a "
                         "one-time download."},
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
    "openrouter": {"label": "OpenRouter - sign in, free open models", "kind": "openai",
                   "base_url": "https://openrouter.ai/api/v1", "needs_key": False, "signin": "openrouter",
                   "model": "", "key_hint": "", "key_url": "",
                   "privacy": "What you type is sent to OpenRouter and the model's provider. Sign in with "
                              "Google, GitHub or email - no API key needed."},
    "huggingface": {"label": "Hugging Face - sign in, open models", "kind": "openai",
                    "base_url": "https://router.huggingface.co/v1", "needs_key": False, "signin": "huggingface",
                    "model": "", "key_hint": "", "key_url": "",
                    "privacy": "What you type is sent to Hugging Face and the model's provider. Uses your "
                               "Hugging Face account's monthly allowance."},
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
areweanticheatyet.com for a specific title. For Jedi Academy install jedi-academy (OpenJK, mods \
supported); for a Jedi Academy mod downloaded from ModDB or elsewhere (.exe installer, .zip/.7z/.rar or .pk3, \
e.g. Movie Duels 2), install_software that file or open_app "Install a Jedi Academy mod" - it unpacks or runs the \
installer, puts the mod into the game and adds it to the Stoa menu; for modding Fallout, Skyrim, Oblivion or Starfield install mod-organizer.
- Security: open_app "stoa-protect" (Stoa Protect) for virus scans, quarantine, the firewall and \
turning on TPM unlock for an encrypted drive. Downloads and installers are scanned automatically.
- Files: find_files, read_file, write_file and open_path work on the person's own files. When they mention \
a file ("my CV", "the invoice from March"), find it first. Summaries and rewrites go in the chat unless they ask \
for a file; then write_file it next to the original or in ~/Documents and offer to open it.
- Troubleshooting: when something is slow, broken, won't connect or keeps failing, run diagnose_system first, \
explain the cause in plain words, then fix what you can with your tools (end a frozen program, install a \
missing package, change a setting) and give clear steps for the rest.
- Razer and other gaming gear: Razer Synapse only runs on Windows, so never try to install it; install \
"razer" (OpenRazer driver + Polychromatic app: lighting, per-key colours, DPI, polling rate, battery) and, for \
mixed brands, "openrgb". Synapse lighting profiles can't be imported; recreate the effect in Polychromatic. \
Razer devices are already kept out of USB power saving, which stops them freezing.
- Task Manager: open_app "Task Manager" to see what's running, end frozen apps, watch CPU, memory, disk, \
network and graphics use, choose start-up apps, or see every part inside the PC (About this PC). Ctrl+Shift+Esc \
opens it too. get_system_info includes the full hardware list (CPU, graphics card, memory sticks, drives, USB).
- Steam games already installed on another drive (for example from Windows): open_app "Find Steam games on \
other drives". It opens the drive at every start-up, lets Steam see it and adds the games so they show as \
installed - no re-download. Windows games then need "Enable Steam Play for all other titles" in Steam > \
Settings > Compatibility.
- Accounts: open_app "Accounts" to add people, change passwords or administrators; the power menu has \
"Switch user".
- Printers: most network and USB printers are found automatically. For anything else, open_app \
"system-config-printer" (Printers) or "simple-scan" (Scanner).
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
                       "'on' or 'off'; wallpaper takes a picture's path or a built-in one: stoa, aurora, sunrise, "
                       "ocean, graphite or meadow.",
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "setting": {"type": "string",
                            "enum": ["volume", "brightness", "wifi", "bluetooth", "airplane_mode", "wallpaper"]},
                "value": {"type": "string"},
            },
            "required": ["setting", "value"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_system_info",
        "description": "Stoa version, memory, disk space, network, battery, uptime and the full hardware list "
                       "(model, CPU, graphics, memory sticks, drives, USB devices, TPM, Secure Boot).",
        "eager_input_streaming": True,
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]

def _tool(name, description, props, required):
    return {"name": name, "description": description, "eager_input_streaming": True,
            "input_schema": {"type": "object", "properties": props, "required": required,
                             "additionalProperties": False}}


TOOLS += [
    _tool("find_files", "Find the person's files by name (and optionally by words inside text files). Searches "
          "their home folder; returns paths, sizes and dates, newest first.",
          {"query": {"type": "string", "description": "words from the file name, e.g. 'invoice march'"},
           "contents": {"type": "string", "description": "optional: text that must appear inside the file"},
           "kind": {"type": "string", "enum": ["any", "document", "image", "audio", "video", "folder"]}},
          ["query"]),
    _tool("read_file", "Read a file's text so you can summarise, explain, check or rewrite it. Handles text and "
          "code, PDF, Word (.docx), OpenDocument (.odt), Excel (.xlsx) and PowerPoint (.pptx).",
          {"path": {"type": "string"}}, ["path"]),
    _tool("write_file", "Create or replace a text file in the person's home folder (notes, letters, CSV, code...). "
          "Replacing an existing file asks them first. Use a sensible folder like ~/Documents.",
          {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
    _tool("open_path", "Open a file, folder or web address with the right app (e.g. a PDF in the PDF viewer, a "
          "folder in Files, https://... in the browser).", {"target": {"type": "string"}}, ["target"]),
    _tool("diagnose_system", "Check the computer for problems: recent errors, failed services, disk space, memory, "
          "the busiest programs, network and internet status. Use when something is slow, broken or failing.",
          {}, []),
    _tool("list_processes", "List running programs with their CPU and memory use.",
          {"sort": {"type": "string", "enum": ["cpu", "memory"]}}, []),
    _tool("end_process", "Close a frozen or runaway program (asks the person first). Give its process id from "
          "list_processes, or its name.", {"target": {"type": "string"}}, ["target"]),
]

REQUIRED = {t["name"]: t["input_schema"].get("required", []) for t in TOOLS}

# Never read or overwrite these (keys, passwords, browser profiles, Stoa AI's own settings).
PRIVATE = (".ssh", ".gnupg", ".config/stoa/assistant.json", ".local/share/keyrings", ".mozilla", ".pki",
           ".config/google-chrome", ".config/chromium", ".config/microsoft-edge", ".var/app")


def _user_path(p, must_exist=True):
    p = os.path.realpath(os.path.expanduser(p.strip().strip('"')))
    rel = os.path.relpath(p, HOME)
    if any(rel == x or rel.startswith(x + "/") for x in PRIVATE):
        raise PermissionError("that location holds private keys or passwords, so Stoa AI doesn't touch it")
    if must_exist and not os.path.exists(p):
        raise FileNotFoundError(f"{p} doesn't exist")
    return p


def _office_text(path, ext):
    """Text from Office Open XML / OpenDocument files (they're zip archives of XML)."""
    import zipfile
    from xml.etree import ElementTree as ET
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if ext == ".docx":
            parts = ["word/document.xml"]
        elif ext == ".pptx":
            parts = sorted((n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                           key=lambda n: int(re.findall(r"\d+", n)[-1]))
        elif ext == ".odt":
            parts = ["content.xml"]
        else:  # .xlsx: cells of each sheet, with the shared-string table resolved
            shared = []
            if "xl/sharedStrings.xml" in names:
                root = ET.fromstring(z.read("xl/sharedStrings.xml"))
                shared = ["".join(t.text or "" for t in si.iter() if t.tag.endswith("}t")) for si in root]
            out = []
            for n in sorted(n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n)):
                out.append(f"--- {n.split('/')[-1][:-4]} ---")
                for row in ET.fromstring(z.read(n)).iter():
                    if not row.tag.endswith("}row"):
                        continue
                    cells = []
                    for c in row:
                        v = next((x.text for x in c if x.tag.endswith("}v")), None)
                        if v is not None and c.get("t") == "s":
                            v = shared[int(v)] if v.isdigit() and int(v) < len(shared) else v
                        if v is None:
                            v = "".join(x.text or "" for x in c.iter() if x.tag.endswith("}t"))
                        cells.append(v or "")
                    out.append("\t".join(cells))
            return "\n".join(out)
        text = []
        for part in parts:
            if part not in names:
                continue
            root = ET.fromstring(z.read(part))
            for el in root.iter():
                tag = el.tag.split("}")[-1]
                if tag in ("p", "h") and text and text[-1] != "\n":
                    text.append("\n")
                if tag in ("t", "span") and el.text:
                    text.append(el.text)
                if tag == "tab":
                    text.append("\t")
            text.append("\n")
        return re.sub(r"\n{3,}", "\n\n", "".join(text))


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
    if not prov or ((prov["needs_key"] or prov.get("signin")) and not cfg.get("api_key")):
        return None
    if prov["kind"] == "openai" and not cfg.get("model"):
        return None
    if prov.get("local") and not local_status().get("installed"):
        return None
    return cfg


def local_status():
    """Stoa AI Local's state (models installed, running, recommendation) - {} if it isn't available."""
    try:
        r = subprocess.run(["stoa-ai-local", "status"], capture_output=True, text=True, timeout=20)
        return json.loads(r.stdout) if r.returncode == 0 else {}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}


def local_ensure():
    """Start the on-device engine if needed; returns an error message or None."""
    try:
        r = subprocess.run(["stoa-ai-local", "ensure"], capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"The local AI engine didn't start ({e})."
    return None if r.returncode == 0 else (r.stderr.strip() or "The local AI engine didn't start.")


def save_config(provider, api_key="", model="", base_url="", refresh_token="", expires_at=0):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    fd = os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"provider": provider, "api_key": api_key.strip(), "model": model.strip(),
                   "base_url": base_url.strip(), "refresh_token": refresh_token, "expires_at": expires_at}, f)


def fresh_credentials(cfg):
    """For signed-in providers whose access tokens expire: refresh shortly before expiry and save."""
    if not PROVIDERS[cfg["provider"]].get("signin") or not cfg.get("expires_at"):
        return cfg
    if cfg["expires_at"] - time.time() > 120:
        return cfg
    import signin
    new = signin.refresh(PROVIDERS[cfg["provider"]]["signin"], cfg.get("refresh_token", ""))
    save_config(cfg["provider"], new["api_key"], cfg.get("model", ""), cfg.get("base_url", ""),
                new["refresh_token"], new["expires_at"])
    return dict(cfg, **new)


def _models_json(provider, api_key, base_url=""):
    """The provider's raw /models list (keeps pricing and capability fields the SDK may drop)."""
    url = (base_url or PROVIDERS[provider]["base_url"]).rstrip("/") + "/models"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}", "User-Agent": "Stoa-AI"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read()).get("data", [])


def pick_model(provider, models):
    """A sensible default: a free model that can use tools (OpenRouter), else a large instruct model."""
    def can_use_tools(m):
        sp = m.get("supported_parameters")
        return sp is None or "tools" in sp
    ids = [m["id"] for m in models if can_use_tools(m)] or [m["id"] for m in models]
    if provider == "openrouter":
        free = [i for i in ids if i.endswith(":free")]
        ids = free or ids
    prefer = ("gpt-oss-120b", "llama-3.3-70b", "qwen3", "deepseek", "llama-4", "mistral", "gemma")
    for p in prefer:
        for i in ids:
            if p in i.lower():
                return i
    return ids[0] if ids else ""


def openai_client(provider, api_key, base_url=""):
    if openai is None:
        raise RuntimeError("the OpenAI SDK isn't installed")
    url = base_url or PROVIDERS[provider]["base_url"]
    return openai.OpenAI(api_key=api_key or "ollama", base_url=url or None, max_retries=3)


def list_models(provider, api_key, base_url=""):
    """Model ids the provider offers, for the setup screen (raises on auth/network errors)."""
    if PROVIDERS[provider]["kind"] == "anthropic":
        return [MODEL]
    if PROVIDERS[provider].get("signin"):
        models = _models_json(provider, api_key, base_url)
        ids = [m["id"] for m in models if (m.get("supported_parameters") is None
                                          or "tools" in m.get("supported_parameters", []))]
        if provider == "openrouter":  # free ones first
            ids.sort(key=lambda i: (not i.endswith(":free"), i))
        return ids
    ids = sorted({m.id for m in openai_client(provider, api_key, base_url).models.list()})
    if provider == "openai":  # hide embeddings, audio, image and moderation models
        ids = [i for i in ids if re.match(r"^(gpt|o\d|chatgpt)", i) and not re.search(
            r"(audio|realtime|transcribe|tts|image|embedding|moderation|search)", i)]
    if provider == "gemini":
        ids = [i for i in ids if "gemini" in i and "embedding" not in i]
    return ids


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


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
            try:
                cfg = fresh_credentials(cfg)
            except Exception:  # noqa: BLE001 - shown as a sign-in prompt when the request fails
                pass
            self.client = openai_client(provider, cfg.get("api_key", ""), cfg.get("base_url", ""))
            self.model = cfg["model"]
        return True

    def describe(self):
        if not self.provider:
            return ""
        label = PROVIDERS[self.provider]["label"].split(" (")[0].split(" - ")[0]
        if PROVIDERS[self.provider].get("local"):
            return f"{label} · {local_status().get('model') or 'on this PC'}"
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
        if PROVIDERS[self.provider].get("local"):
            err = local_ensure()
            if err:
                self.ui.on_error(err)  # _run's finally block reports completion
                return
        try:
            self._loop_openai()
        except openai.AuthenticationError:
            self.ui.on_error("Your sign-in has expired. Open the menu (⋯), choose 'Change AI provider' and "
                             "press 'Sign in again'." if PROVIDERS[self.provider].get("signin") else
                             "That API key wasn't accepted. Open the menu (⋯) and choose 'Change AI provider'.")
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

    # ------------------------------------------------------------- files
    def t_find_files(self, a):
        words = [w.lower() for w in a["query"].split() if w.strip()]
        needle = (a.get("contents") or "").lower()
        kinds = {"document": (".pdf", ".doc", ".docx", ".odt", ".txt", ".md", ".rtf", ".xls", ".xlsx", ".ods", ".csv",
                              ".ppt", ".pptx", ".odp"),
                 "image": (".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp", ".svg"),
                 "audio": (".mp3", ".m4a", ".flac", ".wav", ".ogg", ".opus"),
                 "video": (".mp4", ".mkv", ".mov", ".avi", ".webm")}
        kind = a.get("kind") or "any"
        found, deadline = [], time.time() + 8
        for root, dirs, files in os.walk(HOME):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("snap", "node_modules", "__pycache__")]
            names = dirs if kind == "folder" else files
            for n in names:
                low = n.lower()
                if not all(w in low for w in words):
                    continue
                if kind in kinds and not low.endswith(kinds[kind]):
                    continue
                p = os.path.join(root, n)
                if needle and kind != "folder":
                    try:
                        if os.path.getsize(p) > 5_000_000:
                            continue
                        with open(p, errors="ignore") as f:
                            if needle not in f.read().lower():
                                continue
                    except OSError:
                        continue
                found.append(p)
            if len(found) >= 200 or time.time() > deadline:
                break
        if not found:
            return "No matching files found in the home folder."
        found.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0, reverse=True)
        lines = []
        for p in found[:30]:
            st = os.stat(p)
            lines.append(f"{p}  ({'folder' if os.path.isdir(p) else human_size(st.st_size)}, "
                         f"{time.strftime('%d %b %Y', time.localtime(st.st_mtime))})")
        more = f"\n...and {len(found) - 30} more" if len(found) > 30 else ""
        return "\n".join(lines) + more

    def t_read_file(self, a):
        p = _user_path(a["path"])
        if os.path.isdir(p):
            items = sorted(os.listdir(p))[:200]
            return f"{p} is a folder containing:\n" + "\n".join(items)
        ext = os.path.splitext(p)[1].lower()
        if ext == ".pdf":
            r = subprocess.run(["pdftotext", "-layout", "-l", "40", p, "-"], capture_output=True, text=True, timeout=60)
            text = r.stdout
            if not text.strip():
                return "This PDF has no text layer (it's probably a scan or images)."
        elif ext in (".docx", ".xlsx", ".pptx", ".odt"):
            text = _office_text(p, ext)
        else:
            with open(p, "rb") as f:
                raw = f.read(400_000)
            if b"\0" in raw[:4096]:
                return f"{os.path.basename(p)} is a binary file ({human_size(os.path.getsize(p))}); it can't be read as text."
            text = raw.decode("utf-8", errors="replace")
        limit = 60_000
        if len(text) > limit:
            text = text[:limit] + f"\n\n[...cut: the file has {len(text):,} characters; this is the first {limit:,}]"
        return text

    def t_write_file(self, a):
        p = _user_path(a["path"], must_exist=False)
        if not (p + "/").startswith(HOME + "/"):
            raise PermissionError("Stoa AI only writes inside your home folder")
        if os.path.relpath(p, HOME).startswith("."):
            raise PermissionError("Stoa AI doesn't change hidden settings files")
        if os.path.exists(p) and not self.ui.ask_approval(f"Replace {p}?", "Replace"):
            return "The person chose not to replace the file."
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(a["content"])
        return f"Saved {p} ({human_size(len(a['content'].encode()))})."

    def t_open_path(self, a):
        t = a["target"].strip()
        if not re.match(r"^(https?|mailto):", t):
            t = _user_path(t)
        subprocess.Popen(["xdg-open", t], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return f"Opened {t}."

    # ------------------------------------------------------------- troubleshooting
    def t_diagnose_system(self, a):
        def sh(cmd, timeout=15):
            try:
                r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
                return (r.stdout or r.stderr).strip()
            except (OSError, subprocess.TimeoutExpired):
                return "(not available)"
        import system
        kind, net, _ = system.network()
        online = sh("curl -s -o /dev/null -w '%{http_code}' --max-time 6 https://connectivitycheck.gstatic.com/generate_204")
        sections = [
            ("System", sh(". /etc/os-release; echo \"$PRETTY_NAME, Linux $(uname -r), up $(uptime -p | cut -c4-)\"")),
            ("Errors since start-up (newest last)", sh("journalctl -b -p 3 --no-pager -o short-monotonic -n 25 "
                                                       "| cut -c1-220") or "none"),
            ("Failed services", sh("systemctl --failed --no-legend --plain | head -20") or "none"),
            ("Your failed services", sh("systemctl --user --failed --no-legend --plain | head -20") or "none"),
            ("USB and input problems (disconnects, resets)", sh("journalctl -k -b --no-pager -o short-monotonic "
                "| grep -iE 'usb .*(disconnect|reset|error)|hid.*(error|fail)|input.*(lost|error)' | tail -12 "
                "| cut -c1-200") or "none"),
            ("Disk space", sh("df -h -x tmpfs -x devtmpfs -x squashfs -x overlay --output=target,size,used,avail,pcent")),
            ("Memory", sh("free -h")),
            ("Busiest programs", sh("ps -eo pid,comm,%cpu,%mem --sort=-%cpu | head -8")),
            ("Network", f"{kind} {net}".strip() + f"; internet: {'working' if online == '204' else 'NOT reachable'}"),
            ("Temperatures", sh("cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | head -4 "
                                "| awk '{printf \"%.0f°C \", $1/1000}'") or "not reported"),
        ]
        return "\n\n".join(f"## {t}\n{v}" for t, v in sections)

    def t_list_processes(self, a):
        key = "-%mem" if a.get("sort") == "memory" else "-%cpu"
        r = subprocess.run(["ps", "-u", str(os.getuid()), "-o", "pid,comm,%cpu,%mem,etime", f"--sort={key}"],
                           capture_output=True, text=True, timeout=10)
        return "\n".join(r.stdout.splitlines()[:25])

    def t_end_process(self, a):
        t = a["target"].strip()
        if t.isdigit():
            pids = [int(t)]
        else:
            r = subprocess.run(["pgrep", "-u", str(os.getuid()), "-i", "-f", t], capture_output=True, text=True)
            pids = [int(x) for x in r.stdout.split() if int(x) != os.getpid()]
        if not pids:
            return f"No program matching '{t}' is running."
        names = []
        for pid in pids:
            try:
                with open(f"/proc/{pid}/comm") as f:
                    names.append(f.read().strip())
            except OSError:
                pass
        if any(n in ("stoa-shell", "labwc", "Xorg", "systemd") for n in names):
            return "That's part of the desktop itself; ending it would close your session."
        if not self.ui.ask_approval(f"Close {', '.join(sorted(set(names))) or t}? Unsaved work in it will be lost.",
                                    "Close it"):
            return "The person chose not to close it."
        import signal
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        time.sleep(2)
        for pid in pids:
            if os.path.exists(f"/proc/{pid}"):
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
        return f"Closed {len(pids)} process(es)."

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
        if a["setting"] == "wallpaper":
            v = a["value"].strip()
            builtin = {"stoa": "/usr/share/stoa/wallpaper.jpg"}
            path = builtin.get(v.lower()) or (f"/usr/share/stoa/wallpapers/{v.lower()}.jpg"
                                              if re.fullmatch(r"[a-z]+", v.lower()) else _user_path(v))
            r = subprocess.run(["stoa-settings", "set-wallpaper", path], capture_output=True, text=True, timeout=60)
            if r.returncode:
                raise ValueError(r.stderr.strip() or "couldn't set that wallpaper")
            return "Wallpaper changed."
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
            sh("stoa-taskmgr", "--report"),
        ])
