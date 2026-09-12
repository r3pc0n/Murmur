# Murmur

**Free, local voice dictation for Windows and Linux.**

Hold a key, speak, release. Murmur transcribes your voice using [faster-whisper](https://github.com/SYSTRAN/faster-whisper) and pastes the result into whatever app you have focused. Optionally, an AI cleanup pass removes filler words and fixes punctuation before pasting.

No subscription. No cloud. Your audio never leaves your machine - unless you choose to use a remote server you control yourself.

---

## Features

- **Push-to-talk** - hold any configurable key to record, release to transcribe and paste
- **Local transcription** - runs Whisper entirely on your own GPU or CPU, no internet required
- **Remote transcription** - offload transcription to another machine over your local network, a VPN, or a reverse proxy
- **Cloud transcription** - send audio to a third-party API (Mistral Voxtral, Groq, Deepgram, or Cartesia) for fast transcription on lower-end or older machines, no server of your own required
- **AI cleanup** - an OpenRouter model (Claude, GPT, Gemini, Llama, DeepSeek, Qwen, Mistral, or Amazon Nova) or your own local model (e.g. via Ollama) removes filler words, fixes punctuation and capitalization, and preserves your language (Dutch, English, or mixed)
- **Style profiles** - choose Formal, Informal, Technical, or write your own style instruction
- **User profile** - tell the cleanup model who you are so it can apply context to every transcription
- **Word corrections** - force correct spelling for names, terms or brand names Whisper gets wrong; applied even without AI cleanup
- **Saved servers** - store multiple remote server configurations and switch between them instantly
- **Audio device selection** - choose any input device from settings
- **Activity log** - compact or debug view of every transcription session; full history saved to disk
- **Whisper Server manager** - install, start, stop and configure a local Whisper server directly from the tray icon (Windows); status and connection info on Linux
- **System tray** - runs silently in the background, waveform icon changes colour for idle / recording / processing, and matches the active theme when idle
- **Theming** - follow the active Omarchy theme live, follow the system's light/dark preference, or pick any of Omarchy's 22 bundled themes manually - works on any Linux desktop or Windows, not just Omarchy
- **Recording overlay** - a small animated indicator while recording, theme-colored, positioned anywhere on screen via a 3x3 grid in Settings
- **Single installer** - one `.exe` sets up a Python virtual environment and all dependencies automatically (Windows); `setup_linux.sh` (git clone) or the portable `murmur-install.sh` script for Linux

---

## Requirements

### Linux support matrix

| Session | Text insertion | Global push-to-talk | Status |
|---|---|---|---|
| Arch/Omarchy, Hyprland/native Wayland | `wtype` | Temporary `hyprctl` press/release bindings | Live-tested with Python 3.14.6 |
| Linux/X11 | `xdotool` | `pynput` | Supported compatibility path |
| Other native-Wayland compositors | `wtype` | No supported backend yet | Text insertion is available, but the normal push-to-talk workflow is not fully supported |

Debian and Ubuntu prerequisites are documented below. Native-Wayland global hotkeys should only be considered fully supported on Hyprland today. XWayland's `DISPLAY` may coexist with a native Wayland session; Murmur correctly prefers its Wayland backends in that case.

### Windows

| Dependency | Version | Download |
|---|---|---|
| **Python** | 3.10–3.13 for the current installer | [python.org/downloads](https://www.python.org/downloads/) |

> ⚠ During Python installation, tick **"Add Python to PATH"**.

### Linux system prerequisites

System package names are distribution-specific. Install the appropriate set before running the portable bootstrap.

#### Arch Linux / Omarchy

```bash
sudo pacman -S --needed \
  python tk portaudio pipewire pipewire-pulse wireplumber \
  gtk3 webkit2gtk-4.1 python-gobject python-cairo \
  libayatana-appindicator wtype xdg-utils
```

Hyprland users also need `hyprland`, which provides `hyprctl`. For an actual X11 session, install `xdotool`; it is not required for a native Wayland-only installation.

#### Debian / Ubuntu

Package availability varies by release. On current Debian/Ubuntu releases using WebKitGTK 4.1 and Ayatana AppIndicator:

```bash
sudo apt install \
  python3 python3-venv python3-tk python3-gi python3-gi-cairo \
  gir1.2-gtk-3.0 gir1.2-webkit2-4.1 \
  libayatana-appindicator3-1 gir1.2-ayatanaappindicator3-0.1 \
  libportaudio2 pipewire pipewire-pulse wireplumber wtype xdg-utils
```

Older releases may use WebKitGTK 4.0 or `libappindicator3` package names instead. For an actual X11 session, install `xdotool`. Development headers such as `python3-dev`, `libcairo2-dev`, `libgirepository-2.0-dev`, and `build-essential` are only needed when a Python dependency must be compiled locally.

A StatusNotifier/AppIndicator tray host is required for tray visibility. Waybar with its tray module is one validated implementation; GNOME users commonly need an AppIndicator extension. Murmur does not install or configure the tray host.

### For GPU transcription (recommended)

| Dependency | Version | Download |
|---|---|---|
| **NVIDIA GPU Driver** | Latest | [nvidia.com/drivers](https://www.nvidia.com/Download/index.aspx) |
| **NVIDIA CUDA Toolkit** | 12.x | [developer.nvidia.com/cuda-toolkit-archive](https://developer.nvidia.com/cuda-toolkit-archive) |

Without usable CUDA, Murmur's built-in default runtime falls back to CPU transcription automatically. You can select a lighter model such as `medium` and CPU/int8 explicitly in Settings.

### For AI cleanup (optional)

| Dependency | Notes | Link |
|---|---|---|
| **OpenRouter API key** | One key, many models (Claude, GPT, Gemini, Llama, and more) | [openrouter.ai/keys](https://openrouter.ai/keys) |
| **Or a local model server** | e.g. Ollama - no API key, no third party, runs entirely on your machine | [ollama.com](https://ollama.com) |

---

## Installation

### Windows

1. Download the latest installer from [Releases](https://github.com/R3PC0N/murmur/releases)
2. Run `Murmur-Setup-vX.X.exe`
3. The installer will:
   - Create a Python virtual environment
   - Install all Python dependencies
   - Create a Start Menu shortcut (and optionally a desktop shortcut)
4. On first launch, Murmur downloads the Whisper speech model (~300 MB for `medium`, ~1.5 GB for `large-v3`). A loading screen will appear - just wait until it disappears.

### Linux setup

```bash
git clone https://github.com/R3PC0N/murmur.git
cd murmur
bash setup_linux.sh
```

The script runs as your normal user. It creates `.venv` with
`--system-site-packages` so the distro-managed PyGObject and Cairo bindings are
available, installs the exact Linux dependency set pinned in
`requirements-linux.lock`, validates the current desktop session's capabilities,
and installs a visible XDG application entry and icon. It does not invoke a
package manager or change device permissions. The lock is validated on Arch with
CPython 3.14.6; recreate the venv after a Python minor-version upgrade.

GTK, WebKitGTK, AppIndicator, PyGObject, and Cairo are intentionally not installed
with pip. They must come from the system packages listed above. The dependency
lock covers application Python packages only; faster-whisper downloads the chosen
speech model into the normal Hugging Face cache on first use, and model weights
are not stored or pinned in this repository.

Native Wayland text insertion requires `wtype`. Hyprland push-to-talk uses temporary `hyprctl` runtime bindings and does not require membership in the `input` group. X11 sessions use `xdotool` instead.

After setup, Murmur appears in normal XDG application launchers such as Walker. Optional **Start with System** behavior uses a separate XDG autostart entry. A StatusNotifier/AppIndicator host must be running for the tray icon to be visible.

Start Murmur:

```bash
./murmur.sh
```

---

## Updating

Murmur doesn't check for updates on its own - each platform's install method is re-run manually. Settings, history, and your `.env` are all preserved across an update; nothing here touches them.

**Windows:** download the latest installer from [Releases](https://github.com/R3PC0N/murmur/releases) and run it over your existing install. Inno Setup recognizes it as an upgrade of the same app rather than a separate install.

**Linux, git clone:**
```bash
cd murmur
git pull
bash setup_linux.sh
```
`setup_linux.sh` always reinstalls dependencies against the current `requirements-linux.lock`, even if `.venv` already exists, so this picks up anything new - not just what a fresh install would need.

**Linux, portable install script:**
```bash
curl -sSL https://murmurlabs.dev/downloads/murmur-install.sh | bash
```
Re-running it detects your existing `~/murmur` install, updates the files in place, and reruns setup the same way as above.

---

## First-run setup

### 1. AI cleanup (optional but recommended)

Open **Settings → AI Cleanup**, enable it, and pick a provider:

- **OpenRouter** - paste an API key from [openrouter.ai/keys](https://openrouter.ai/keys) and choose a model (Claude Haiku, GPT-4o mini, Gemini Flash Lite, Llama, DeepSeek, Qwen, Mistral, and Amazon Nova are pre-listed)
- **Local** - point it at any OpenAI-compatible server, such as [Ollama](https://ollama.com) running on `http://localhost:11434/v1` - no API key needed, nothing leaves your machine

To set an OpenRouter key via environment variable instead of Settings:

**Windows:** open `%LOCALAPPDATA%\Murmur\.env` in a text editor and add your key:

```
OPENROUTER_API_KEY=sk-or-your-key-here
```

**Linux:** open `$XDG_CONFIG_HOME/murmur/.env` (normally
`~/.config/murmur/.env`) and add the same line. The Linux bootstrap creates this
file; existing source-tree `.env` values are imported on first startup and the
legacy file is retained as a backup.

### 2. Start dictating

Murmur starts in the system tray. Hold **F9** anywhere, speak, release. The transcribed text is pasted into your active window.

The hotkey can be changed in **Settings → General**.

### Push-to-talk backends

- **Windows:** the existing `keyboard`-based Windows backend.
- **Linux/X11:** `pynput` listens for the configured key.
- **Hyprland/Wayland:** Murmur registers temporary press and release bindings through `hyprctl` and relays those events to the running process. It does not permanently edit Hyprland configuration.
- **Other native-Wayland compositors:** Murmur reports that no supported global-hotkey backend is available instead of attempting an unreliable X11 fallback.

On Hyprland, Settings offers F1–F12, letters, digits, Space, Page Up, and Page Down, with optional Ctrl, Alt, Shift, and Super modifiers. Murmur compares the complete combination and will not replace an identical compositor binding. A desktop or distribution may already use F9, so choose an available combination — a single dedicated key like Page Down avoids the (rare but real) chance of a modifier combo like Ctrl+Z colliding with your terminal's own SIGTSTP suspend binding.

### Text insertion backends

- **Windows:** Murmur temporarily writes the transcription to the clipboard and simulates paste, then restores the previous clipboard content.
- **Linux/X11:** `xdotool` types directly into the focused application.
- **Linux/Wayland:** `wtype` receives literal Unicode text through standard input. Murmur uses a small typing delay for reliability and normalizes tabs to four spaces because a real Tab key often changes focus.

Wayland is selected when `WAYLAND_DISPLAY` is present even if XWayland also provides `DISPLAY`.

---

## Settings overview

Open Settings from the tray icon (right-click → Settings).

| Section | What you can configure |
|---|---|
| **General** | Push-to-talk key, start with system |
| **Audio** | Input device |
| **Transcription** | Local, remote, or cloud mode, Whisper model, device and language, saved remote servers, cloud provider/model and API key (Voxtral, Groq, Deepgram, or Cartesia) |
| **AI Cleanup** | Enable/disable, provider (OpenRouter or Local), model, API key or local server URL |
| **Display** | Appearance (theme), recording overlay, overlay screen position, sound feedback |
| **Profile** | Transcription style, user context, word corrections |

### Transcription language

The language selector applies to local faster-whisper transcription and updated bundled Murmur servers:

- **Automatic** passes no fixed language and uses Whisper's language detection.
- **Dutch** explicitly selects Whisper language code `nl`.
- **English** explicitly selects Whisper language code `en`.

Older remote servers that predate the optional language field continue to use automatic detection.

### Word corrections

In **Profile → Word corrections**, add one correction per line:

```
murmur=Murmur
cuda=CUDA
```

Corrections are applied after transcription using whole-word matching. They work even when AI cleanup is disabled.

### Style profiles

Choose a style in **Profile → Transcription style**:

| Style | Effect |
|---|---|
| `none` | No style instruction - only filler removal and punctuation fixes |
| `formal` | Complete sentences, professional tone |
| `informal` | Casual tone, contractions allowed |
| `technical` | Technical terms and acronyms preserved exactly |
| `custom` | Write your own instruction |

### Appearance & themes

Open **Settings → Display → Appearance** to choose how Murmur is colored. One picker, three kinds of entries:

- **Follow Omarchy theme** - only shown on Omarchy. Live: switching your Omarchy theme system-wide (`omarchy-theme-set` or the usual theme switcher) recolors every open Murmur window within a couple of seconds, no restart needed. Murmur only reads Omarchy's current theme state to do this - it never writes to your Omarchy configuration.
- **Follow system light/dark** - works everywhere, including plain Ubuntu/GNOME/KDE and Windows. Uses Murmur's own neutral light and dark palette, following the desktop's light/dark preference (the same standard mechanism - the XDG Desktop Portal on Linux - that Omarchy itself uses under the hood).
- **A specific theme by name** - all 22 of Omarchy's built-in themes (gruvbox, tokyo-night, nord, catppuccin, and so on) are bundled directly into Murmur, so they're available as a fixed pick even without Omarchy installed. Doesn't change until you change it.

The tray icon's idle color and the recording overlay (see below) both follow whichever of these is active. The one thing that doesn't is the native window title-bar chrome on Windows - it stays driven by the Windows light/dark setting itself, regardless of a manually-picked theme.

### Recording overlay

A small always-on-top indicator appears while recording: an animated waveform in the current theme's accent color and a timer, no other chrome. Toggle it and set where it sits on screen from **Settings → Display**:

- **Show recording overlay** - on or off
- **Overlay position** - a 3x3 grid (top/middle/bottom × left/center/right); defaults to bottom-right

---

## Remote transcription

Murmur can send audio to a Whisper server running on another machine - useful if your laptop is slow but you have a powerful desktop or home server.

### How it works

1. The server runs a FastAPI service that accepts audio and returns transcribed text
2. Requests can be authenticated with an API key; use HTTPS or a trusted VPN when audio crosses an untrusted network
3. The client sends a small WAV file over HTTP and receives the transcribed text back

All you need is for the client to be able to reach the server's URL. How you arrange that is up to you.

### Connecting client to server

There are several ways to make the server reachable from another device:

**Local network** — if both devices are on the same Wi-Fi or LAN, use the server's local IP directly:
```
http://192.168.1.x:8765
```

**Tailscale** — a free zero-config VPN. Install it on both devices, sign in with the same account, and use the server's `100.x.x.x` Tailscale IP:
```
http://100.x.x.x:8765
```
> If you use a VPN (e.g. Mullvad), add Tailscale to its split-tunnel exclusions so both can run simultaneously.

**Reverse proxy** — if you run Caddy, Nginx, or a similar proxy, add a virtual host that forwards to port 8765. This lets you use a domain name with HTTPS and works from any network without installing extra software:
```
https://whisper.yourdomain.com
```

**Direct port forwarding** — open port 8765 (or 443 via a reverse proxy) on your router and point it at the server machine. Combine with a dynamic DNS service if your home IP changes.

### Windows server (via Murmur UI)

If your server is a Windows PC with Murmur installed:

1. On the server PC: right-click the Murmur tray icon → **Whisper Server...**
2. Click **Install Server** (one-time setup, downloads ~500 MB)
3. Click **Generate** to create an API key
4. Note the **Remote URL** and **API key** shown in the window
5. On the client: open **Settings → Transcription**, switch to **Remote**, paste the URL and key
6. Click **Save current as...** to save this server for quick access later

The server can be started and stopped from the tray icon at any time. Enable **"Start server when Murmur launches"** to have it start automatically.

### Linux server

Requirements: Python 3.10+, CUDA 12.x (for GPU), or CPU-only.

The server does not implement the desktop client's automatic CUDA-to-CPU fallback. Set `WHISPER_DEVICE` and `WHISPER_COMPUTE_TYPE` explicitly for the server host.

```bash
cd murmur/server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env  # set MURMUR_API_KEY and optionally WHISPER_MODEL, WHISPER_DEVICE
```

**.env example:**
```
MURMUR_API_KEY=your-strong-random-key
WHISPER_MODEL=medium
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=float16
```

**Run manually:**
```bash
python faster_whisper_server.py
```

**Run as a systemd service:**
```bash
sudo cp murmur-whisper.service /etc/systemd/system/
# Edit the service file to match your paths and username
sudo systemctl enable --now murmur-whisper
```

> If your CUDA libraries are in a non-standard location (e.g. installed via Ollama), add the path to `LD_LIBRARY_PATH` in the service file:
> ```
> Environment="LD_LIBRARY_PATH=/usr/local/lib/ollama/cuda_v12"
> ```

**Verify the server is running:**
```bash
curl http://localhost:8765/health
# {"status":"ok","model":"medium","device":"cuda"}
```

---

## Cloud transcription

Murmur can send audio to a third-party transcription API instead of running Whisper anywhere yourself - useful on a machine too slow or battery-limited for local transcription, with no server of your own to set up or maintain.

**This is a different trust boundary than remote mode above.** Remote mode sends audio to a server *you* control; cloud mode sends it to a third party's API over the internet.

### Providers

| Provider | Console | Notes |
|---|---|---|
| Mistral Voxtral | [console.mistral.ai](https://console.mistral.ai) | Fast, low cost - the original default. Auto-detects language. |
| Groq | [console.groq.com](https://console.groq.com) | Hosted Whisper large-v3/turbo; typically the fastest and cheapest option, generous free tier. Auto-detects language. |
| Deepgram | [console.deepgram.com](https://console.deepgram.com) | Nova-3; strong accuracy. Defaults to English - Murmur doesn't currently pass a language parameter, so non-English speech isn't picked up. |
| Cartesia | [play.cartesia.ai](https://play.cartesia.ai) | Ink-Whisper. Also defaults to English for the same reason. |

Each provider needs its own API key from its own console - keys are not shared between providers, so switching providers in Settings doesn't reuse whatever key was entered for a different one. Check each provider's own pricing page before relying on it for heavy use.

If your speech isn't English, Voxtral or Groq are the ones that will actually pick that up today.

### Setup

1. Get an API key from whichever provider's console you want to use (table above)
2. Open **Settings → Transcription**, switch to **Cloud**, pick the provider and model, and paste that provider's key - or set the `MURMUR_CLOUD_API_KEY` environment variable (in `.env`, same idea as `OPENROUTER_API_KEY` for AI cleanup) if you'd rather not store it in Settings; it applies to whichever provider is currently selected
3. That's it - no model download, no server to run

A missing or invalid key fails the recording clearly rather than silently falling back to local transcription, so a billing or network problem is never mistaken for silence.

---

## Activity log

Right-click the tray icon → **Activity log** to see recent transcriptions.

- **Compact** - shows transcription results and errors only
- **Debug** - shows every step including raw Whisper output before cleanup

Full history is saved to disk. Open it via tray → **Open history**.

---

## Building from source

**Windows:**
```bat
git clone https://github.com/R3PC0N/murmur.git
cd murmur
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

**Linux:**
```bash
git clone https://github.com/R3PC0N/murmur.git
cd murmur
bash setup_linux.sh
./murmur.sh
```

**Building the Windows installer** (requires [Inno Setup 6](https://jrsoftware.org/isdl.php)):

```
Open murmur.iss in Inno Setup → press F9
Output: dist\Murmur-Setup-vX.X.exe
```

---

## Privacy

- Audio is processed locally by default and never sent anywhere
- When using remote mode, audio is sent over HTTP to a server you control — secure it with HTTPS (via a reverse proxy) or a VPN if used over the internet
- When using cloud mode, audio is sent to a third-party API (Mistral, Groq, Deepgram, or Cartesia, whichever you've picked) that you do not control — a different trust boundary than remote mode, not just a faster version of it
- AI cleanup sends transcribed text (not audio) to a third-party API if enabled and set to OpenRouter, or to a server you control (and nowhere else) if set to Local

---

## License

MIT - see [LICENSE](LICENSE)
