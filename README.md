<div align="center">
  <a href="https://github.com/hiperiondev/RadioCAT_GUI">
    <img src="images/full_gui.png" alt="screenshot">
  </a>
</div>

# CAT GUI — Amateur Radio SDR Control Interface

A Python client-server system for controlling a Software Defined Radio (SDR) transceiver. `cat_gui.py` is a full-featured Tkinter desktop front-end; `cat_server.py` is a protocol-compliant back-end that ships with a built-in signal simulator so the GUI works immediately out of the box — and can be replaced (or extended) with a real SDR hardware driver.

---

## Table of Contents

- [Overview](#overview)
- [System Architecture](#system-architecture)
- [Feature Highlights](#feature-highlights)
- [Requirements & Installation](#requirements--installation)
- [Windows Installation & Usage](#windows-installation--usage)
- [Quick Start](#quick-start)
- [Configuration Files](#configuration-files)
  - [cat\_gui.toml — GUI Settings](#cat_guitoml--gui-settings)
  - [cat\_server.toml — Transport & Device List](#cat_servertoml--transport--device-list)
  - [cat\_device.toml — Device Profile](#cat_devicetoml--device-profile)
  - [Per-Device State & Memory Files](#per-device-state--memory-files)
- [Command-Line Reference](#command-line-reference)
  - [cat\_gui.py](#cat_guipy-cli-flags)
  - [cat\_server.py](#cat_serverpy-cli-flags)
- [TCP Protocol Specification](#tcp-protocol-specification)
  - [GUI → Server Commands](#gui--server-commands)
  - [Server → GUI Messages](#server--gui-messages)
- [GUI Layout & Controls](#gui-layout--controls)
  - [RF Waterfall & Spectrum](#rf-waterfall--spectrum)
  - [Toolbar Strip](#toolbar-strip)
  - [Left Control Panel](#left-control-panel)
  - [AF Waterfall, Spectrum & Text Pane](#af-waterfall-spectrum--text-pane)
- [Audio System](#audio-system)
- [IQ & Audio WAV Playback (Server)](#iq--audio-wav-playback-server)
- [Frequency Memories](#frequency-memories)
- [Device Profiles & Switching](#device-profiles--switching)
- [HiDPI / Scaling](#hidpi--scaling)
- [Theming & Fonts](#theming--fonts)
- [Generated Files Reference](#generated-files-reference)
- [Extending the Server](#extending-the-server)

---

## Overview

CAT GUI implements a complete radio-control interface modeled on the look and feel of high-end SDR transceivers. The GUI connects to the server over a local (or remote) TCP socket and communicates via a simple newline-delimited JSON protocol. A separate UDP channel carries real-time bidirectional audio (receive audio from the server to the GUI speaker; microphone audio from the GUI to the server when PTT is active).

The reference server included here is a **simulator**: it generates synthetic RF carrier signals on a 192 kHz-wide spectrum, produces a 440 Hz receive audio tone, accepts every GUI command, and echoes all state changes back. You can play real IQ recordings and real receive audio through it with two flags (`--iq_wav` and `--audio_wav`). The server architecture is intentionally minimal so that it is straightforward to replace the signal-generation stub with a real SDR hardware driver (SoapySDR, RTL-SDR, SDRplay, etc.).

---

## System Architecture

```
┌────────────────────────────────────────────────────┐
│                  cat_gui.py (client)               │
│                                                    │
│  ┌───────────┐  ┌──────────┐  ┌─────────────────┐  │
│  │  WFCanvas │  │SpecCanvas│  │  FreqDisp (×3)  │  │
│  │(waterfall)│  │(spectrum)│  │  LO A / LO B /  │  │
│  └───────────┘  └──────────┘  │  Tune           │  │
│                               └─────────────────┘  │
│  ┌──────────────┐  ┌────────────────────────────┐  │
│  │RTPAudioClient│  │     NetClient (TCP)        │  │
│  │  UDP/G.711μ  │  │  JSON newline-delimited    │  │
│  └──────────────┘  └────────────────────────────┘  │
└──────────────┬──────────────────────┬──────────────┘
               │  TCP (control)       │  UDP (audio)
               ▼                      ▼
┌────────────────────────────────────────────────────┐
│                cat_server.py (server)              │
│                                                    │
│  ┌────────────┐  ┌───────────────┐  ┌───────────┐  │
│  │RadioState  │  │ClientHandler  │  │UDPAudio   │  │
│  │  (all SDR  │  │  (per-client  │  │Channel    │  │
│  │   state)   │  │  TCP thread)  │  │(TX+RX RTP)│  │
│  └────────────┘  └───────────────┘  └───────────┘  │
│  ┌────────────┐  ┌───────────────┐                 │
│  │IQWavSource │  │AudioWavSource │                 │
│  │(--iq_wav)  │  │(--audio_wav)  │                 │
│  └────────────┘  └───────────────┘                 │
└────────────────────────────────────────────────────┘
```

**TCP control channel** — newline-delimited UTF-8 JSON objects. The GUI sends one command object per line; the server replies with `{"resp": "ok"}` for every command. For `hello` and `select_device` only, the reply also includes a full state dict: `{"resp": "ok", "state": {...}}`. While running, the server additionally pushes `{"type": "data", ...}` frames at ~10 Hz with fresh spectrum, S-meter, and squelch data.

**UDP audio channel** — RTP datagrams with a 12-byte header and a G.711 μ-law (PCMU) payload at 8 kHz / 8-bit / mono / 20 ms frames (160 bytes of μ-law per packet). Bidirectional: server → GUI when PTT is off (receive audio); GUI → server when PTT is on (microphone audio for TX).

---

## Feature Highlights

### Display
- **RF waterfall** — O(width) per-frame incremental `PhotoImage.put()` scroll, adjustable speed (1–10), freezes with "● TX" badge during transmit
- **RF spectrum** — retained-item canvas (no `delete("all")` per frame), draggable IF passband overlay, peak-hold display with configurable decay, VFO cursor line
- **AF waterfall** — same engine as RF waterfall; driven from locally-decoded RTP audio (not a server-computed value), so what is drawn always matches what you hear
- **AF spectrum** — local FFT of received PCM; a Hamming window is applied in all cases; uses `numpy.fft.rfft` when available, falls back to a pure-Python Cooley-Tukey radix-2 FFT otherwise
- Reference level (SCALE) adjustable ±5 dB steps; FFT averaging (AVE) 1–10; per-box Waterfall / Spectrum toggle
- Frequency-axis grid lines and labels auto-scaled to a "nice" step size for any span or zoom level

### Frequency Control
- **Dual LO (VFO A / B)** plus a **Tune** display — three independent 9-digit amber frequency readouts with comma separators
- Per-digit mouse-wheel (or left/right-click) increment/decrement; double-click opens a direct Hz entry dialog
- **SPLIT mode** — LO A as RX, LO B as TX; TX/RX labels shown beside each LO display when active
- **Band buttons** — 160 m through 6 m (ITU Region 2 ranges); pressing one QSYs directly to the band's center frequency
- Per-device and per-antenna **band restrictions** — disabled band buttons are visually grayed out
- **M (Memory) buttons** — beside each frequency row; opens a 20-slot memory dialog per device

### Signal Processing Controls
- Volume, AGC Threshold, RF Gain, Squelch — horizontal sliders, instantly reflected to server
- **Mode buttons** — LSB, USB, AM, FM, CW, and up to 10 user-defined modulation modes
- **AGC** — off / slow / medium / fast, plus a configurable AGC threshold slider
- **Filter** — passband dragged directly on the IF spectrum canvas; low and high edge independently adjustable
- **Zoom** — in/out buttons or mouse-wheel on the IF spectrum; zoom narrows the RF span displayed
- Toggle buttons: NB (noise blanker), NR (noise reduction), NB RF, NB IF, AFC, ANF, Notch, Mute
- **S-meter** — arc-style analog meter with peak-hold bar; numeric dBm and S-unit text readout; squelch open/closed LED. During transmit the arc automatically switches to an **SWR gauge** (scale 1.0–5.0) with colour-coded zones (green → red)

### Radio Management
- **Start / Stop** — arms or disarms the SDR (server begins or stops streaming data)
- **PTT** — circular button, instantaneous TX/RX switching; waterfall/spectrum frozen with badge during TX
- **SWAP** — swaps the LO A and LO B frequencies in one click
- **LOCK** — locks the active LO (or both LOs when SPLIT is on) to prevent accidental frequency changes; the frequency displays and **M** buttons for locked LOs are disabled
- **Transport bar** — Record ●, Play ▶, Pause ⏸, Stop ■, Rewind ◀◀, Fast-forward ▶▶, Loop ∞
- **Device selector** — up to 20 named device profiles; switching saves current state and restores the target device's persisted state and memories
- **Bandwidth selector** — combobox populated from the server's `bandwidth_map` for the current mode; `◄` / `►` step buttons shift the active LO by the selected bandwidth
- **TX Power selector** — shown when the device profile defines `power_levels`; opens a modal dialog that sends `set_power` to the server
- **Antenna selector** — up to 10 labeled ports per device, each with its own optional band restriction
- **Sample Rate selector** — per-device list of selectable SDR sample rates
- **Soundcard selector** — PyAudio device enumeration; independently pick mic and speaker device
- **User-defined buttons** — 14 programmable buttons (7 + 7 rows), each independently `normal` (momentary) or `push` (toggle/latch)
- **RF user buttons** — 11 programmable buttons left of the band array, same normal/push types; a **long-press (≥ 3 s)** opens an in-app config dialog whose widgets are defined per-button in the device profile's `config_N` key
- **Text/RTTY pane** — user-defined modulation modes can split the AF box to reveal a read-only text panel or a live RTTY-style bidirectional chat panel

### Window & Scaling
- Auto-detects screen DPI and picks the best scale level; manual `+` / `−` scale buttons always available
- Scale factor is 1.25ˢᶜᵃˡᵉ (e.g., level 2 = 1.5625×); range −5 to +5
- Bottom control panel **always stays fully visible** at any window size — RF waterfall/spectrum shrink first
- Debounced `<Configure>` resize handler prevents layout thrashing during live window drag
- `--full-screen` flag; triple-Esc toggle while running
- `--resolution WxH` and `--aspect-ratio W:H` flags; aspect ratio is enforced after layout settles

---

## Requirements & Installation

### Python Version
Python **3.9** or later. Python 3.11+ includes `tomllib` in the standard library; older versions need `tomli`.

### Core Dependency
`tkinter` is included in the standard library but may require a separate OS package on some Linux distributions:

```bash
# Debian / Ubuntu
sudo apt install python3-tk

# Fedora / RHEL
sudo dnf install python3-tkinter
```

### Optional Dependencies

| Package | Purpose | Install |
|---------|---------|---------|
| `numpy` | Accelerated FFT for spectrum (both sides); required for `--iq_wav` on the server | `pip install numpy` |
| `tomli` | TOML config support on Python < 3.11 | `pip install tomli` |
| `pyaudio` | Microphone and speaker audio (GUI only) | `pip install pyaudio` |
| `fonttools` | Authoritative PostScript family name lookup for custom fonts | `pip install fonttools` |

Without `pyaudio` the GUI runs normally but audio input/output is silently disabled. Without `numpy` spectrum rendering falls back to a pure-Python FFT (correct but slower). Without `tomli`/`tomllib` a built-in minimal TOML parser is used (covers all keys the bundled config templates produce).

### Installation

```bash
# Clone or download the repository, then:
pip install numpy tomli pyaudio fonttools   # all optional, install as needed
```

No `setup.py` or `pyproject.toml` is required — both scripts run directly.

---

## Windows Installation & Usage

Everything in this project runs on Windows without any UNIX-specific dependencies. The steps below cover a clean machine from scratch.

### 1. Install Python

Download the **Python 3.11** (or later) installer from [python.org/downloads](https://www.python.org/downloads/windows/).

During installation:

- Check **"Add python.exe to PATH"** on the first screen — this is unchecked by default.
- Click **"Customize installation"** and confirm that **"tcl/tk and IDLE"** is checked. This installs `tkinter`, which is the GUI toolkit used by `cat_gui.py`. If you skip this, the GUI will fail to import `tkinter` and will not start.

Verify after installation by opening **Command Prompt** (`Win + R` → `cmd`) and running:

```cmd
python --version
python -c "import tkinter; print('tkinter OK')"
```

Both commands should complete without error.

### 2. Install Optional Dependencies

Open **Command Prompt** or **PowerShell** and run:

```cmd
pip install numpy tomli pyaudio fonttools
```

#### PyAudio on Windows

`pip install pyaudio` frequently fails on Windows because it tries to compile a C extension without a compiler present. The cleanest solution is to install a pre-built wheel instead:

```cmd
pip install pipwin
pipwin install pyaudio
```

Alternatively, download the matching `.whl` file for your Python version from the [Unofficial Windows Binaries for Python Extension Packages](https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio) page (look for `PyAudio‑0.2.x‑cpXXX‑cpXXX‑win_amd64.whl` where `XXX` matches your Python version), then install it directly:

```cmd
pip install PyAudio-0.2.14-cp311-cp311-win_amd64.whl
```

If PyAudio cannot be installed, the GUI still runs fully — audio input/output is silently disabled and a notice is printed to the console.

### 3. Get the Scripts

Download `cat_gui.py` and `cat_server.py` (and `morgenta_regular.ttf` if you want the bundled frequency font) into the same folder, for example `C:\CAT`.

### 4. Open a Working Directory

All config files, state files, and memory files are created in the **current working directory** when the scripts are first run. It is best to `cd` into your project folder before launching anything:

```cmd
cd C:\CAT
```

### 5. Run the Server

```cmd
python cat_server.py
```

On first run (when no `cat_server.toml` or `cat_device.toml` exist), the server creates annotated `.example` template files next to where the real configs would live, then runs on built-in defaults. The console will show:

```
[config] cat_server.toml not found — using built-in defaults (copy cat_server.toml.example to cat_server.toml to customise)
[config] cat_device.toml not found — using built-in defaults (copy cat_device.toml.example to cat_device.toml to customise)
[cat_server] listening on 0.0.0.0:50101
```

To persist your settings, copy (or rename) the `.example` files:

```cmd
copy cat_server.toml.example cat_server.toml
copy cat_device.toml.example cat_device.toml
```

**Windows Firewall prompt** — Windows may show a security alert the first time the server opens a socket. Click **"Allow access"** (at minimum for Private networks) so the GUI can reach it, even when both processes are on the same machine.

### 6. Run the GUI

Open a **second** Command Prompt window, `cd` to the same folder, and run:

```cmd
python cat_gui.py
```

On first run this creates `cat_gui.toml`. The GUI window opens. Type `127.0.0.1` in the **Host** field and `50101` in the **Port** field (these are the defaults already shown), then click **Connect** followed by **Start**.

> **Tip — autoconnect:** To skip the Host/Port/Connect row entirely on subsequent launches, edit `cat_gui.toml` and set:
> ```toml
> [connection]
> host = "127.0.0.1"
> port = 50101
> autoconnect = true
> ```
> The GUI will connect automatically on startup and the connection row will be hidden.

### 7. Running as Separate Windows (Recommended)

Because the server and GUI are separate processes, it is convenient to run each in its own window. A simple batch file for this:

**`start_all.bat`** (save in `C:\CAT`):

```bat
@echo off
cd /d %~dp0
start "CAT Server" cmd /k python cat_server.py
timeout /t 1 >nul
start "CAT GUI"    cmd /k python cat_gui.py
```

Double-click `start_all.bat` to launch both in separate titled windows. Closing either window shuts down that process cleanly.

### 8. Windows-Specific Notes

#### Audio Device Selection

Windows often has multiple audio endpoints (e.g., speakers, headphones, virtual cable). To list all devices and their indices:

```cmd
python cat_gui.py --audio-list
```

Then launch the GUI targeting specific devices:

```cmd
python cat_gui.py --audio-mic 1 --audio-speaker 2
```

Or set them persistently in `cat_gui.toml`:

```toml
[audio]
mic = 1
speaker = 2
```

#### Custom Fonts

Custom TTF/OTF fonts work on Windows without administrator rights. The GUI calls `AddFontResourceExW` with `FR_PRIVATE | FR_NOT_ENUM` flags, which registers the font in-process only — no system-wide installation and no UAC prompt. Simply point `--freq-font` at any `.ttf` or `.otf` file:

```cmd
python cat_gui.py --freq-font "C:\Fonts\MyFont.ttf"
```

Or in `cat_gui.toml`:

```toml
[display]
freq_font = "C:\\Fonts\\MyFont.ttf"
```

Note the **double backslashes** in TOML strings, or use forward slashes (both work on Windows):

```toml
freq_font = "C:/Fonts/MyFont.ttf"
```

#### HiDPI / 4K Displays

On high-DPI monitors Windows applies display scaling. If the GUI appears blurry or oversized, Python may be receiving pre-scaled coordinates from Windows. The auto-scale logic already compensates by reading the real screen resolution and selecting the best scale level, but you can override it:

```cmd
python cat_gui.py --scale 2
```

Or set it in `cat_gui.toml`:

```toml
[display]
scale = 2
disable_scale = false
```

You can also right-click `python.exe` → Properties → Compatibility → Change high DPI settings → **"Override high DPI scaling behavior: Application"** to let Python handle DPI itself rather than Windows.

#### Full-Screen Mode

```cmd
python cat_gui.py --full-screen
```

Once running, press **Esc three times within one second** to toggle full-screen on or off.

#### Firewall & Remote Connections

If the server and GUI run on **different machines** (e.g., server on a shack PC, GUI on a laptop over LAN), you must allow inbound connections on both the TCP control port and the UDP audio port through Windows Defender Firewall:

1. Open **Windows Defender Firewall with Advanced Security** (`wf.msc`).
2. Add an **Inbound Rule** → Rule Type: Port → TCP → port `50101` → Allow.
3. Add a second **Inbound Rule** → Rule Type: Port → UDP → port `5004` → Allow.

Then launch the server normally and point the GUI at the server's LAN IP:

```cmd
python cat_gui.py --host 192.168.1.10 --port 50101
```

#### PATH Issues

If `python` is not found after installation, use the full path (`C:\Users\YourName\AppData\Local\Programs\Python\Python311\python.exe`) or re-run the Python installer and check **"Add Python to environment variables"** in the Customize step.

If `pip` is not found, run:

```cmd
python -m pip install numpy tomli pyaudio fonttools
```

#### Console Encoding

If the console prints garbled characters (rare on modern Windows 10/11), set the code page to UTF-8 before running:

```cmd
chcp 65001
python cat_server.py
```

---

## Quick Start

**1. Start the server** (default port 50101, simulated RF signals):

```bash
python cat_server.py
```

On first run, if `cat_server.toml` or `cat_device.toml` are absent, the server creates `.example` template files and runs on built-in defaults. Copy the examples to activate custom configuration:

```bash
cp cat_server.toml.example cat_server.toml
cp cat_device.toml.example cat_device.toml
```

**2. Start the GUI** (connects to 127.0.0.1:50101 by default):

```bash
python cat_gui.py
```

**3.** In the GUI, click **Connect**, then click **Start**.

The RF waterfall and spectrum will begin scrolling, the S-meter will animate, and a 440 Hz receive tone will play through the system speaker (if PyAudio is installed).

---

## Configuration Files

Both sides **self-correct** their TOML configuration files on every run: if a key is missing (e.g. after an upgrade adds a new option), it is added at its default value and the file is rewritten in place.

### cat\_gui.toml — GUI Settings

Created in the working directory as `cat_gui.toml` (override with `--config PATH`).

```toml
# CAT GUI configuration
# CLI flags override these values at runtime without modifying this file.

[display]
bg = "dark"           # "light" or "dark"
full_screen = false   # start in full-screen mode
scale = 0             # HiDPI scale level, -5 to 5
disable_scale = false # hide the +/- scale controls
freq_font = ""        # path to TTF/OTF font for frequency digit displays
gui_font = ""         # path to TTF/OTF font for all other GUI text

[connection]
# Both host and port must be set, and autoconnect = true, to connect on startup.
# With autoconnect = true the host/port/connect row is hidden from the GUI entirely.
host = ""
port = 0
autoconnect = false

[audio]
# Device indices from --audio-list; -1 = system default.
# Both mic and speaker must be set together (or both left at -1).
mic = -1
speaker = -1
disable_soundcard_select = false
```

### cat\_server.toml — Transport & Device List

Created as `cat_server.toml` (override with `--config PATH`). Contains server transport settings and the list of up to 20 named device profiles.

```toml
[server]
host = "0.0.0.0"
port = 50101

[audio]
audio_port = 5004
no_audio = false

[devices]
# Up to 20 device profiles. Empty label = slot unused.
label_1 = "Main SDR"
config_1 = "devcfg_main.toml"
label_2 = ""
config_2 = ""
# ... label_3 / config_3 ... label_20 / config_20
```

### cat\_device.toml — Device Profile

Created as `cat_device.toml` (override with `--device-config PATH`). Defines the GUI layout for one device: its programmable buttons, modulation modes, SDR sample rates, and antenna ports.

```toml
[user_buttons]
# Up to 14 user-defined buttons. Slots must be filled in order (no gaps).
label_1 = "CW Spot"
type_1 = "push"     # "normal" (momentary), "push" (toggle/latch), or "list" (selection dropdown)
list_1 = ""         # comma-separated dropdown items when type is "list" (max 20 chars each)
label_2 = ""
# ... label_3 / type_3 / list_3 ... label_14 / type_14 / list_14

[user_mods]
# Up to 10 user-defined modulation buttons. Slots must be filled in order.
label_1 = "RTTY"
type_1 = "text_input"  # "normal", "text", or "text_input"
# ... label_2 / type_2 ... label_10 / type_10

[rf_usr_btns]
# Up to 11 buttons shown left of the band array in the RF panel.
# Buttons with empty labels are hidden in the GUI.
label_1 = "ATU"
mode_1 = "push"     # "normal" (momentary) or "push" (push-push toggle)
# config_1: JSON-encoded dict defining the long-press (≥ 3 s) configure dialog.
# Empty string or "{}" = no dialog for this button.
# Each key is the widget label; the value is a widget spec object.
# Four widget types are supported:
#   slide  → {"type": "slide", "range": [min, max]}
#   list   → {"type": "list", "values": [{"key": "Label", "val": "value"}, …]}
#   check  → {"type": "check"}
#   radio  → {"type": "radio", "options": ["val1", "val2", …]}
# Example (slider 0–100, a two-option radio group, and a checkbox):
config_1 = '{"Power": {"type":"slide","range":[0,100]}, "Band": {"type":"radio","options":["HF","VHF"]}, "Bypass": {"type":"check"}}'
# ... label_2 / mode_2 / config_2 ... label_11 / mode_11 / config_11

[bandwidth]
# Available filter bandwidths (Hz) for each modulation mode.
# A matching entry is required for every label defined in [user_mods];
# the server will refuse to start (sys.exit) if any label is missing here.
AM  = "3000,6000,9000,10000"
FM  = "12500,25000"
LSB = "2700,3600"
USB = "2700,3600"
CW  = "250,500,1000,2000"
# RTTY = "250,500"   ← add one line per [user_mods] label you define

[sdr]
sample_rate = 192000
# Comma-separated list of selectable rates for this device.
sample_rates = "192000,250000,500000,1000000,2000000"
# Comma-separated list of bands this device may tune to (empty = all).
allowed_bands = "160m,80m,60m,40m,30m,20m,17m,15m,12m,10m,6m"
# Comma-separated TX power levels in watts; empty = power selector hidden.
power_levels = "5.0,10.0,25.0,50.0,100.0"

[antenna]
# Up to 10 antenna ports. Empty label = slot unused/hidden.
label_1 = "Dipole"
allowed_bands_1 = ""          # empty = inherit device-level allowed_bands
label_2 = "HF Vertical"
allowed_bands_2 = "40m,20m,15m,10m"
# ... label_3 / allowed_bands_3 ... label_10 / allowed_bands_10
```

Each entry in `cat_server.toml`'s `[devices]` section points to a **separate** `cat_device.toml`-compatible file for that profile. Switching devices in the GUI loads that profile's buttons, sample rates, memories, and last-saved GUI state.

### Per-Device State & Memory Files

These are generated automatically next to each device's config file:

| File | Content |
|------|---------|
| `<device>.gui_state.json` | Persisted operator settings: frequencies (LO A/B/Tune), mode, filter, AGC, gains, squelch, toggles, zoom, sample rate, button states, antenna selection, spectrum display settings, selected bandwidth (`selected_bw`), RF user button configure-dialog values (`rf_usr_btn_config_vals`) |
| `<device>.memories.json` | 3 × 20 frequency memories (LO A, LO B, Tune) with labels and frequencies |

State is saved when the operator switches away from a device and restored when they switch back. Memory slots are written immediately whenever a slot is saved from the GUI.

---

## Command-Line Reference

### cat\_gui.py CLI Flags

```
python cat_gui.py [OPTIONS]

Connection:
  --host HOST            Server hostname or IP (must pair with --port)
  --port PORT            Server TCP port (must pair with --host)
  --autoconnect          Connect automatically on startup; hides the
                         host/port/connect row in the GUI

Display:
  --bg {light,dark}      Background theme ("dark" is the default)
  --full-screen          Start in full-screen mode (triple-Esc to toggle)
  --resolution WxH       Initial window size in pixels, e.g. 1280x720
  --aspect-ratio W:H     Lock window to an aspect ratio, e.g. 16:9 or 4:3
                         (ignored when --full-screen is set)
  --scale INT            Initial HiDPI scale level, -5 to 5 (0 = auto-detect)
  --disable-scale        Hide the +/- scale buttons (pair with --scale)
  --freq-font PATH       TTF/OTF font file for the LO/Tune frequency displays
  --gui-font PATH        TTF/OTF font file for all other GUI text

Audio:
  --audio-list           Print all audio device indices and exit
  --audio-mic INDEX      Select microphone device by index (pair with --audio-speaker)
  --audio-speaker INDEX  Select speaker device by index (pair with --audio-mic)
  --disable-soundcard-select
                         Hide the Soundcard button in the GUI

Misc:
  --config PATH          Load GUI TOML config from PATH instead of ./cat_gui.toml
  --debug                Enable verbose debug output on the console

Band Restriction:
  --restrict-band        Hard-block any LO change that falls outside the active
                         device's allowed_bands (standard amateur bands outside
                         that list are always rejected). Without this flag,
                         allowed_bands only grays out band buttons; keyboard and
                         mouse-wheel frequency entry are unrestricted.
```

### cat\_server.py CLI Flags

```
python cat_server.py [OPTIONS]

Transport:
  --host HOST            TCP listen address (default: 0.0.0.0)
  --port PORT            TCP listen port (default: 50101)
  --audio-port PORT      UDP RTP audio port (default: 5004)
  --no-audio             Disable the UDP audio channel entirely

Config files:
  --config PATH          Load cat_server.toml from PATH instead of ./cat_server.toml
  --device-config PATH   Load cat_device.toml from PATH instead of ./cat_device.toml

IQ & Audio:
  --iq_wav PATH          WAV file of IQ samples to use for the RF spectrum/waterfall
                         (stereo PCM/float, I=left, Q=right; optional auxi chunk for
                         center frequency). Looped forever. Requires numpy.
  --audio_wav PATH       WAV file to transmit as simulated receive audio (looped).
                         Resampled to 8 kHz mono. Replaces the built-in 440 Hz tone.

User-defined buttons (also settable via cat_device.toml):
  --user-button-label-N TEXT   Label for user button N (1–14, max 7 chars)
  --user-button-type-N TYPE    "normal" or "push" for user button N

User-defined modulation modes:
  --user_mod_N LABEL     Label for user-mod button N (1–10, max 4 chars)
  --user_mod_type_N TYPE "normal", "text", or "text_input" for slot N

RF user buttons:
  --rf_usr_btn_N LABEL   Label for RF user button N (1–11, max 7 chars)
  --rf_usr_btn_mode_N M  "normal" or "push" for RF user button N
```

> **Priority:** CLI flags always beat the TOML config file, which beats built-in defaults. Button/mod slot flags must be specified sequentially (1, 2, 3 …) with no gaps; the server will error if a slot is skipped.

---

## TCP Protocol Specification

All messages are UTF-8, newline-terminated JSON objects (`\n`). One object per line in both directions. The server accepts multiple simultaneous TCP clients (each in its own thread).

### GUI → Server Commands

Every command receives an immediate `{"resp": "ok"}` reply. Commands marked ★ also return a full state dict in the same reply: `{"resp": "ok", "state": {...full radio state...}}`.

#### Startup

| Command | Fields | Notes |
|---------|--------|-------|
| `hello` ★ | — | Sent on connect; triggers a `reload_state` push and returns full state |

#### Frequency

| Command | Fields | Notes |
|---------|--------|-------|
| `set_freq` | `hz: int` | Set LO A (main receive) frequency |
| `set_lo_a_freq` | `hz: int` | Alias for `set_freq` |
| `set_lo_b_freq` | `hz: int` | Set LO B (split TX) frequency |
| `set_tune_freq` | `hz: int` | Set Tune (BFO/IF offset) frequency |
| `set_lo` | `lo: "A"\|"B"` | Select active LO |

#### Mode & DSP

| Command | Fields | Notes |
|---------|--------|-------|
| `set_mode` | `mode: str` | e.g. `"USB"`, `"LSB"`, `"AM"`, `"FM"`, `"CW"` |
| `set_agc` | `mode: str` | `"off"`, `"slow"`, `"medium"`, `"fast"` |
| `set_agc_thresh` | `value: float` | AGC threshold in dBm (−140 to −20) |
| `set_filter` | `lo: int, hi: int` | IF passband edges in Hz (e.g. `lo=100, hi=2800`) |
| `set_zoom` | `value: int` | Zoom factor (≥ 1) |
| `set_rf_gain` | `value: float` | RF gain in dB (0–60) |
| `set_volume` | `value: float` | Audio volume (0–100) |
| `set_squelch` | `value: float` | Squelch level in dBm (−140 to 0) |
| `set_nb` | `enabled: bool` | Noise blanker (audio/IF) |
| `set_nbrf` | `enabled: bool` | Noise blanker (RF) |
| `set_nbif` | `enabled: bool` | Noise blanker (IF) |
| `set_nr` | `enabled: bool` | Noise reduction |
| `set_afc` | `enabled: bool` | Automatic frequency control |
| `set_anf` | `enabled: bool` | Automatic notch filter |
| `set_notch` | `enabled: bool` | Manual notch filter |
| `set_mute` | `enabled: bool` | Audio mute |
| `set_selected_bw` | `value: int` | Set the active bandwidth from the current mode's `bandwidth_map` list (Hz) |

#### Spectrum Display

| Command | Fields | Notes |
|---------|--------|-------|
| `set_spec_ref` | `box: "rf"\|"af", value: float` | Reference level (top of display), snapped to nearest 5 dB, range −50 to +10 |
| `set_spec_ave` | `box: "rf"\|"af", value: int` | FFT averaging count, 1–10 |

#### PTT, SPLIT, Transport

| Command | Fields | Notes |
|---------|--------|-------|
| `set_ptt` | `enabled: bool, udp_port: int` | Activate/deactivate PTT; `udp_port` tells the server where to send TX audio |
| `set_split` | `enabled: bool` | Enable/disable SPLIT (LO A RX, LO B TX) |
| `start` | — | Begin SDR streaming |
| `stop` | — | Stop SDR streaming |
| `transport` | `action: str` | `"rec"`, `"play"`, `"pause"`, `"stop"`, `"rw"`, `"ff"`, `"infinite"` |

#### Device & Hardware

| Command | Fields | Notes |
|---------|--------|-------|
| `get_devices` | — | Returns `{"type": "device_list", "devices": [...]}` |
| `select_device` ★ | `index: int` | 1-based device index; saves current state, loads new device |
| `get_sample_rates` | — | Returns `{"type": "sample_rate_list", "rates": [...], "current": N}` |
| `set_sample_rate` | `value: int` | Set sample rate (must be in this device's configured list) |
| `get_antennas` | — | Returns `{"type": "antenna_list", "antennas": [...], "current": N, "device_allowed_bands": [...]}` |
| `select_antenna` | `index: int` | 1-based antenna port index (0 = deselect) |
| `get_power_levels` | — | Returns the list of TX power levels for the current device |
| `set_power` | `index: int` | Select TX power level by 0-based index from the device's `power_levels` list; silently ignored (with a console warning) if index is out of range |

#### User Buttons & Text

| Command | Fields | Notes |
|---------|--------|-------|
| `user_button` | `index: int` | Momentary press of user button N (1-based) |
| `user_button` | `index: int, enabled: bool` | Push-push (toggle) state of user button N |
| `user_button` | `index: int, choice: int` | Selection index for a `"list"`-type user button |
| `rf_usr_button` | `index: int` | Momentary press or push-push toggle of RF user button N (1–11, left of band buttons) |
| `rf_usr_button` | `index: int, enabled: bool` | Explicit push state for a `"push"`-type RF user button |
| `rf_usr_btn_config_set` | `index: int, values: {name: value, …}` | Store configure-dialog values for RF user button N; persisted to `.gui_state.json` |
| `user_text` | `index: int, text: str` | Text submitted by the operator in a `text_input` mode panel |
| `ui_display` | `box: str, view: str` | Waterfall / Spectrum view toggle |
| `ui_toolbar` | `box: str, action: str` | Toolbar button click (Waterfall / Spectrum toolbar) |
| `ui_smeter_btn` | `action: str` | S-meter button click (Peak / S-units / Squelch) |
| `ui_button` | `action: str` | GUI control button (Full Screen, SDR-Device, FreqMgr, Minimize, Exit) |
| `memory` | — | Legacy momentary "M" button press (no-op; kept for backward compatibility with older GUI builds) |

#### Frequency Memories

| Command | Fields | Notes |
|---------|--------|-------|
| `get_memories` | `position: "LO A"\|"LO B"\|"Tune"` | Returns the 20-slot list for that row |
| `save_memory` | `position: str, index: int, label: str, freq: float` | Saves a slot and persists immediately to disk |

#### Audio Registration

| Command | Fields | Notes |
|---------|--------|-------|
| `audio_hello` | `udp_port: int` | Registers the GUI's UDP endpoint with the server's audio channel |

---

### Server → GUI Messages

#### Streamed Data Frame (~10 Hz while running)

```json
{
  "type": "data",
  "f_start": 28390000,
  "f_stop": 28590000,
  "spectrum": [-120.5, -118.3, ...],       // NUM_BINS dBm values
  "af_range": 3000,
  "af_spectrum": [-95.1, -93.0, ...],      // AF_BINS dBm values (0..3000 Hz)
  "smeter_dbm": -73.0,
  "smeter_text": "S9",
  "squelch_open": true,
  "swr": null,                             // float (e.g. 1.35) while PTT on; null otherwise
  "state": { ... }                         // incremental state fields
}
```

The GUI uses `f_start`/`f_stop` to position the RF spectrum/waterfall frequency axis; `af_range` (always 3000 Hz) for the AF display axis.

#### Unsolicited Pushes

| Type | Fields | Meaning |
|------|--------|---------|
| `audio_port` | `port, sample_rate, frame_ms, codec` | Emitted on client connect; tells the GUI which UDP port to open for audio |
| `reload_state` | — | GUI should resync all widgets from the preceding `resp:ok` state |
| `device_list` | `devices: [{index, label}]` | Response to `get_devices` |
| `sample_rate_list` | `rates: [int], current: int` | Response to `get_sample_rates` |
| `antenna_list` | `antennas: [...], current: int, device_allowed_bands: [...]` | Response to `get_antennas` |
| `memory_list` | `position: str, memories: [{label, freq}×20]` | Response to `get_memories` or `save_memory` |
| `power_level_list` | `levels: [str], current: int` | Response to `get_power_levels`; drives the TX Power selector dialog |
| `bandwidth_map` | `map: {mode: [int, ...]}` | Sent on connect and on device switch; populates the Bandwidth selector combobox per mode |
| `user_text` | `index: int, text: str` | Server-pushed text to a `text`/`text_input` panel slot |
| `disconnected` | (optional `reason`) | Emitted by GUI internally when the TCP connection drops |

#### State Dictionary

The full state dict (sent in `resp:ok` for `hello` / `select_device`, and incrementally in `data` frames) contains:

```
center_freq, tune_freq, lo_b_freq, lo_active
mode, agc, agc_thresh
filter_lo, filter_hi
rf_gain, volume, squelch
nb, nr, nbrf, nbif, afc, anf, notch, mute
ptt, split, running
zoom, sample_rate
user_buttons, user_btn_state, user_btn_list_sel
rf_usr_btns, rf_usr_btn_state, rf_usr_btn_config_vals
user_mod_labels, user_mod_types
spec_ref_rf, spec_ave_rf, spec_ref_af, spec_ave_af
allowed_bands, antenna_labels, antenna_index, antenna_allowed_bands
bandwidth_map, selected_bw
power_levels, power_index
active_device_index
```

Key notes:
- `rf_usr_btn_config_vals` — dict keyed by 1-based button index (as string); value is a `{name: value}` dict of the last values submitted via `rf_usr_btn_config_set`. Persisted to `.gui_state.json`.
- `selected_bw` — currently selected bandwidth as an Hz string (e.g. `"2700"`). Persisted per-device.
- `active_device_index` — 1-based index of the active device profile (0 = none). Used by the GUI to restore the device label on startup and mark the active device in the Device dialog.
- `antenna_allowed_bands` — list of 10 sorted-band-name lists (one per antenna slot). Empty inner list = inherit device-level `allowed_bands`.
- `swr` in **data frames only** — float SWR reading (e.g. `1.35`) while PTT is on; `null` when PTT is off. Drives the SWR gauge on the S-meter. (Not in the state dict; only in `type: "data"` frames.)

---

## GUI Layout & Controls

### RF Waterfall & Spectrum

The RF panel fills the top portion of the window and is divided into two vertically stacked subpanels:

**RF Waterfall** (`WFCanvas`) — the larger, expanding panel at the top. New spectrum rows are prepended at the top so the newest data is always at the top and history scrolls down. The scroll rate is controlled by the Speed knob in the toolbar. During PTT the waterfall is frozen and a "● TX" badge is shown.

**RF Spectrum** (`SpecCanvas`) — fixed-height strip below the waterfall. Drawn with a retained-object technique (all canvas items created once at startup; each frame only updates coordinates). Shows: spectrum trace with green fill, a semi-transparent IF passband overlay (blue rectangle with draggable edges), a VFO cursor line (red), and a peak-hold line (white-blue). The IF filter edges can be dragged directly with the mouse. Mouse-wheel on the spectrum zooms in/out.

### Toolbar Strip

A narrow strip between the RF panel and the bottom row contains per-box controls for both the RF panel (above) and the AF panel (below):

- **Waterfall / Spectrum** — mutually exclusive toggle buttons to switch the display mode for this box
- **SCALE** — reference level (top of display) in dB; +/− buttons step by 5 dB (range −50 to +10)
- **AVE** — FFT averaging count; +/− buttons step by 1 (range 1–10)
- **Speed** — waterfall scroll speed; +/− buttons step by 1 (range 1–10)
- **RBW** / **Span** labels (informational)

### Left Control Panel

The left-hand panel is fixed-width and hosts all transceiver controls, top to bottom:

**S-meter row** — arc-style analog S-meter canvas with animated needle, peak-hold indicator, squelch open/closed LED, and a PTT circular button pinned to the right. When PTT is active the arc gauge automatically switches to an **SWR meter** (scale 1.0–5.0) with colour-coded zones (green for low SWR, stepping through amber to red at high SWR); the dBm / S-unit text area is replaced with a numeric SWR readout. The S-meter resumes when PTT is released.

**Frequency displays** — three `FreqDisp` widgets (LO A, LO B, Tune). Each shows 9 amber digits with thousands separators. A row of LO A/B selector buttons sits between the displays; SPLIT state shows TX/RX labels beside the active LOs. An **M** button beside each row opens the frequency memory dialog for that row.

**SWAP / LOCK / BW row** — immediately below the LO selector buttons:
- **SWAP** — exchanges the LO A and LO B frequencies in one click.
- **LOCK** — toggles a frequency lock on the active LO. When locked the frequency display and **M** button for that LO are disabled to prevent accidental QSY. With SPLIT active, LOCK applies to both LO A and LO B simultaneously.
- **◄ / ►** — shift the active LO down or up by the currently selected bandwidth.
- **Bandwidth combobox** — dropdown populated from `bandwidth_map[current_mode]`; selecting a value sends `set_selected_bw` to the server.

**Band buttons** — 11 ITU Region 2 bands (160 m – 6 m). Clicking QSYs LO to the band center. Buttons outside the device's `allowed_bands` (or the selected antenna's restriction) are grayed out automatically.

**Volume / AGC Threshold / RF Gain / Squelch** — four horizontal sliders with labels.

**Device / Sample Rate / Soundcard** — buttons that open modal selection dialogs.

**Power** — TX power level button; shown only when the server reports `power_levels` for the current device. Opens a level-selection dialog; the chosen level is sent as `set_power`.

**Mode buttons** — standard modulation modes (LSB, USB, AM, FM, CW, …) plus up to 10 server-defined user modulation modes.

**DSP toggles** — NB, NR, AGC, Filter, AFC, ANF, Notch, Mute — each a two-state push button with green highlight when active.

**Transport bar** — Record ●, Play ▶, Pause ⏸, Stop ■, Rewind ◀◀, Fast-forward ▶▶, Loop ∞.

**Start button** — arms/disarms the SDR. Text changes to "Stop" while running.

**User-defined button rows** — 14 buttons in two rows of 7. Labels and types come from the server; unlabeled buttons are hidden.

**RF user buttons** — 11 buttons shown above the band buttons in the RF panel, to the left of the band array. A **long-press (≥ 3 seconds)** on any button opens a runtime configure dialog. The dialog's widgets are defined in the device profile's `config_N` key for that button (see `cat_device.toml` above); values submitted in the dialog are sent as `rf_usr_btn_config_set` and persisted to `.gui_state.json`.

**Date/time + connection controls** — UTC clock (green); host/port fields and a Connect button with a status LED. In autoconnect mode the entire row is hidden.

### AF Waterfall, Spectrum & Text Pane

The right half of the bottom row is the Audio Frequency panel, driven entirely from locally-decoded RTP audio (not server-computed):

- **AF Waterfall** — same `WFCanvas` engine; shows 0–3000 Hz audio frequency content scrolling in real time
- **AF Spectrum** — same `SpecCanvas` engine; 0–3000 Hz range, no filter overlay (AF has no draggable passband)
- **AF Toolbar** — same controls as RF toolbar (Scale, Ave, Speed, Waterfall/Spectrum toggle)
- **Text/RTTY Pane** — when a `text` or `text_input` user-mod mode is selected, the AF box splits horizontally. The right side shows a read-only text display (server-pushed messages) and, for `text_input` modes, an editable 3-line input box that sends its contents as `user_text` when the operator presses Enter. Each user-mod slot has its own independent text history.

---

## Audio System

The GUI's `RTPAudioClient` manages the UDP audio channel:

- **Receive (PTT OFF):** The server sends one RTP/PCMU packet every 20 ms. The GUI decodes μ-law to 16-bit PCM and writes to a PyAudio output (speaker) stream via a deque ring buffer and a PyAudio callback.
- **Transmit (PTT ON):** The GUI opens a PyAudio input (mic) stream, reads 160-sample PCM frames, encodes to μ-law, packs into RTP, and sends UDP datagrams to the server.
- **AF spectrum feed:** Decoded PCM samples are accumulated in a rolling ring buffer; a background worker thread fires an FFT every ~50 ms and posts the result to the GUI's Tk event queue for display in the AF waterfall/spectrum.
- The μ-law codec uses precomputed 256-entry decode and 65536-entry encode lookup tables (built once at import time) for a zero-branch, zero-struct hot path on every audio frame.
- Soundcard selection (microphone and speaker independently) via the Soundcard dialog or `--audio-mic` / `--audio-speaker` flags; `--audio-list` prints all available device indices.

---

## IQ & Audio WAV Playback (Server)

### `--iq_wav PATH`

Drives the RF spectrum and waterfall from a real IQ recording instead of the synthetic signal generator. Accepts SDRplay-style stereo WAV files where the left channel is I and the right channel is Q, at any integer or float PCM depth (8/16/32-bit). If the file contains an `auxi` chunk the recorded centre frequency is extracted and used to seed the initial tuned frequency.

The file is looped forever (tape-loop playback). An IQ FFT (`IQ_FFT_SIZE = 4096` bins, Hanning window, fftshift) converts each block to a dBm-approximate power spectrum; the zoom level then crops and resamples the full-bandwidth result to the GUI's display width.

Requires `numpy`.

### `--audio_wav PATH`

Replaces the built-in 440 Hz demo tone with a real WAV file (mono or stereo PCM/float at any sample rate). Stereo is downmixed to mono; the audio is resampled to 8 kHz if its native rate differs. The file loops forever as the simulated receive audio stream delivered to the GUI.

---

## Frequency Memories

Each device profile has its own independent set of memories: 20 slots for each of three frequency positions (LO A, LO B, Tune) = 60 slots per device.

Opening the memory dialog (clicking an **M** button beside a frequency display) sends `get_memories` to the server. The server returns all 20 slots for that position from the active device's memory file. The operator can:

- **Recall** a memory slot — sends `set_freq` (or equivalent) and closes the dialog
- **Save** the current frequency into a slot — opens a label-entry dialog, then sends `save_memory`
- **Edit** a slot's label in-place

Memories are written to disk immediately every time a slot is saved; they survive server restarts and device switches.

---

## Device Profiles & Switching

Up to 20 device profiles can be defined in `cat_server.toml`'s `[devices]` section. Each entry pairs a display label with a path to a `cat_device.toml`-compatible config file.

When the operator clicks the **Device** button, the GUI sends `get_devices`; the server replies with a list dialog. Selecting a device sends `select_device`:

1. The server saves the current device's GUI state (frequencies, mode, filter, gains, toggles, etc.) to its `.gui_state.json` file.
2. The new device's `cat_device.toml`-like file is loaded; user buttons, modulation buttons, RF buttons, sample rates, band restrictions, and antenna ports are replaced.
3. The new device's `.gui_state.json` is restored (frequencies, mode, toggles, etc.).
4. The new device's `.memories.json` is loaded.
5. A `reload_state` message is sent; the GUI resyncs all widgets.

On startup, if a `[devices]` list is configured and `--device-config` was not explicitly passed, the server auto-selects device 1 so that its persisted state file is used from the very first connection (avoiding a "phantom" identity mismatch on first connect).

---

## HiDPI / Scaling

All geometry constants are defined in a `BASE` dictionary at scale 1.0. The effective scale factor is `1.25 ^ scale_level`. Level 0 targets a 1280×720 display; the auto-detection logic picks the largest level whose default window size (1520×870 at level 0) fits in 90% of the screen:

| Scale Level | Factor | Target Resolution |
|:-----------:|:------:|:----------------:|
| −5 | 0.33× | very small displays |
| −4 | 0.41× | — |
| −3 | 0.51× | — |
| −2 | 0.64× | — |
| −1 | 0.80× | < 1280×720 |
| 0 | 1.00× | 1280×720 |
| 1 | 1.25× | 1920×1080 |
| 2 | 1.56× | 2560×1440 |
| 3 | 1.95× | — |
| 4 | 2.44× | 3840×2160 |
| 5 | 3.05× | — |

The `+` / `−` scale buttons in the top-right corner of the window increment/decrement the level at runtime; all fonts, widget sizes, padding, and canvas geometry recalculate immediately. The scale overlay shows the current level and fades after a few seconds.

The layout engine ensures the bottom control panel (S-meter row through the date/time row) is **always fully visible** at any window height: only the RF waterfall/spectrum above shrinks to accommodate the bottom panel.

---

## Theming & Fonts

### Colour Palette

The default dark theme uses a deep navy/teal colour scheme:

| Role | Hex | Description |
|------|-----|-------------|
| Window / waterfall background | `#020814` | Deep dark blue |
| Control panel | `#0c1525` | Dark navy |
| Spectrum background | `#010610` | Near-black navy |
| Spectrum trace | `#22cc44` | Green |
| VFO cursor | `#ff2828` | Red |
| Frequency digits | `#ffb800` | Amber |
| Active button | `#1a3c6a` / `#50c0ff` | Blue |
| S-meter bar | `#28ee50` → `#ff3830` | Green → red |
| Peak hold | `#e0e8ff` | White-blue |

The `--bg light` flag or `bg = "light"` in `cat_gui.toml` replaces all background surfaces with `#FFECD6` (warm cream), converting the frequency digit amber to dark orange for readability.

### Custom Fonts

Two independent font paths can be set:

- `--freq-font PATH` — used exclusively for the LO A, LO B, and Tune frequency digit displays
- `--gui-font PATH` — propagated to all of Tk's named system fonts (`TkDefaultFont`, `TkTextFont`, etc.) so every widget picks it up automatically

Font loading (TTF/OTF) works without admin rights on Linux, macOS, and Windows:

- **Linux:** copies the font to `~/.local/share/fonts/`, runs `fc-cache`, then calls `FcConfigAppFontAddFile()` on the live in-process fontconfig handle so Tk sees the family immediately
- **macOS:** copies to `~/Library/Fonts/`, then calls `CTFontManagerRegisterFontsForURL` scoped to the current process
- **Windows:** calls `AddFontResourceExW` with `FR_PRIVATE | FR_NOT_ENUM` (no admin rights required)

The PostScript family name is resolved by fonttools (preferred), then `fc-query`, then a filename-stem heuristic.

---

## Generated Files Reference

| File | Created By | Content |
|------|-----------|---------|
| `cat_gui.toml` | GUI on first run | GUI display, connection, audio settings |
| `cat_server.toml.example` | Server on first run (if `cat_server.toml` is absent) | Annotated template — copy to `cat_server.toml` to customise |
| `cat_device.toml.example` | Server on first run (if `cat_device.toml` is absent) | Annotated template — copy to `cat_device.toml` to customise |
| `<device>.gui_state.json` | Operator (must create manually) | Persisted per-device operator settings; server saves into it but never creates it |
| `<device>.memories.json` | Server on first memory save | Per-device 3×20 frequency memories |
| `<device>.gui_state.json.example` | Server on first run | Example gui_state file for reference / starting point |
| `<device>.memories.json.example` | Server on first run | Example memories file for reference / starting point |

> **Config file creation:** When `cat_server.toml` or `cat_device.toml` is absent the server writes a `<name>.toml.example` companion file and runs on built-in defaults for that session. The actual `.toml` file is **never** auto-created; the operator must copy or rename the `.example` file to activate custom configuration.

> **gui_state files:** The server saves into `<device>.gui_state.json` but will never create it if it does not exist. An `.example` version is written on first run for reference. The operator must create the real file (e.g. by copying the example) before per-device state will be persisted across restarts.

All `.toml` files are self-healing: missing keys are added at their default value and the file is rewritten in place.

---

## Extending the Server

The reference server is structured so that the signal-generation layer is easy to replace:

- **`RadioState.apply(cmd)`** — processes every GUI command. Add new commands here.
- **`ClientHandler._stream_loop()`** — calls `RadioState.as_dict()` and builds the outgoing `data` frame at 10 Hz. Replace the synthetic `Signal` list with real SDR samples to get a live spectrum.
- **`UDPAudioChannel._tx_loop()`** — sends μ-law RTP frames from either `AudioWavSource.read_frame()` or `_gen_sine_frame()`. Connect a real SDR demodulator here to deliver actual receive audio.
- **`UDPAudioChannel._rx_loop()`** — receives μ-law RTP from the GUI during PTT. The decoded PCM is currently discarded; route it to your SDR transmit path here.
- **`IQWavSource`** — a complete, standalone IQ WAV reader with looping and FFT output. Wrap a real SDR API (SoapySDR, RTL-SDR Python bindings, etc.) in the same interface (`read_block(n)` → complex numpy array) to feed live IQ samples into `_iq_fft_spectrum_db()`.

The JSON protocol is intentionally simple: any language or framework that can open a TCP socket and write newline-terminated JSON can drive the GUI.

## Hamlib map

`cat_gui.py` uses a **custom JSON-over-TCP protocol** (newline-delimited JSON objects) that communicates with a proprietary Python backend (`cat_server.py`). Hamlib's `rigctld` uses a **text command protocol** (single-char or `\long_name value\n` over TCP port 4532). The two protocols are architecturally different in several key ways:

### 1. Summary

| Dimension | cat_gui.py Custom Protocol | Hamlib rigctld |
|---|---|---|
| **Wire format** | JSON objects, newline-delimited | Plain-text tokens, space-separated, `\n`-terminated |
| **Transport** | TCP (configurable port) + UDP RTP audio | TCP (default 4532) only |
| **Push model** | Server **pushes** spectrum/state continuously | Client **polls** for each `get_*` |
| **Audio** | Integrated RTP/G.711 µ-law audio stream | No audio — radio-only |
| **State sync** | `resp:ok` + `reload_state` push full state | Client reads each parameter individually |
| **Mode tokens** | Server-defined arbitrary labels (up to 10 slots) | Fixed set: USB, LSB, CW, FM, AM, RTTY… |
| **Memory** | JSON object with freq/mode/label | `rigmem` utility; CAT-command channel |

### 2. Outbound Commands (`net.send`) → Hamlib Equivalents

Commands sent **from the GUI to the server**.

| # | cat_gui.py `cmd` | Parameters | Hamlib Equivalent | Hamlib Short/Long | Status |
|---|---|---|---|---|---|
| 1 | `hello` | — | *(handshake — no direct equivalent)* | `\dump_caps` (nearest: capability query) | ⚠️ **Different** — Hamlib has no session hello; `dump_caps` is closest |
| 2 | `start` | — | *(no equivalent — SDR-specific start/stop streaming)* | — | ❌ **Missing in Hamlib** |
| 3 | `stop` | — | *(no equivalent)* | — | ❌ **Missing in Hamlib** |
| 4 | `set_lo_a_freq` | `hz` (int) | `set_freq` on VFOA | `F` / `\set_freq` | ⚠️ **Different** — Hamlib sets VFO freq; cat_gui uses "LO A" (SDR local oscillator concept) |
| 5 | `set_lo_b_freq` | `hz` (int) | `set_freq` on VFOB | `F` / `\set_freq` (with VFO=VFOB) | ⚠️ **Different** — requires explicit VFO selection in Hamlib |
| 6 | `set_lo` | `lo` ("A"\|"B") | `set_vfo` | `V` / `\set_vfo` | ✅ **Maps** — VFO A/B selection |
| 7 | `set_tune_freq` | `hz` (int) | *(no direct equivalent — IF/tune offset concept)* | RIT/XIT `J`/`Z` (partial) | ⚠️ **Different** — Hamlib RIT/XIT is relative offset; tune_freq is absolute |
| 8 | `set_mode` | `mode` (string) | `set_mode` | `M` / `\set_mode` | ⚠️ **Different** — Hamlib uses fixed token set; cat_gui uses server-defined arbitrary labels |
| 9 | `set_filter` | `lo`, `hi` (Hz) | `set_mode` passband | `M` / `\set_mode` (2nd arg) | ⚠️ **Different** — Hamlib sets passband as single width integer; cat_gui uses lo/hi pair |
| 10 | `set_ptt` | `enabled` (bool), `udp_port` (int) | `set_ptt` | `T` / `\set_ptt` | ⚠️ **Different** — Hamlib PTT values: 0=RX,1=TX,2=TX-mic,3=TX-data; cat_gui uses bool + RTP UDP port |
| 11 | `set_split` | `enabled` (bool) | `set_split_vfo` | `S` / `\set_split_vfo` | ⚠️ **Different** — Hamlib also requires TX VFO token; cat_gui uses simple bool |
| 12 | `set_volume` | `value` (float 0–100) | `set_level AF` | `L AF` / `\set_level AF` | ✅ **Maps** — AF level |
| 13 | `set_rf_gain` | `value` (float dB) | `set_level RF` | `L RF` / `\set_level RF` | ✅ **Maps** — RF gain level |
| 14 | `set_squelch` | `value` (float dBm) | `set_level SQL` | `L SQL` / `\set_level SQL` | ✅ **Maps** — Squelch level |
| 15 | `set_agc_thresh` | `value` (float dB) | `set_level AGC` | `L AGC` / `\set_level AGC` | ⚠️ **Different** — Hamlib AGC is enum (OFF/SLOW/MEDIUM/FAST/AUTO); cat_gui uses dB threshold float |
| 16 | `set_zoom` | `value` (int) | *(no equivalent — SDR spectrum zoom)* | — | ❌ **Missing in Hamlib** |
| 17 | `set_selected_bw` | `value` (int Hz) | `set_mode` passband | `M` / `\set_mode` | ⚠️ **Different** — Hamlib merges mode+BW in one command |
| 18 | `set_spec_ref` | `box`, `value` (dB) | *(no equivalent — display parameter)* | — | ❌ **Missing in Hamlib** |
| 19 | `set_spec_ave` | `box`, `value` (int) | *(no equivalent — display parameter)* | — | ❌ **Missing in Hamlib** |
| 20 | `ui_display` | `box`, `view` | *(no equivalent — GUI-layer command)* | — | ❌ **Missing in Hamlib** |
| 21 | `transport` | `action` (rec/play/pause/stop/rw/ff/infinite) | *(no equivalent — media transport)* | — | ❌ **Missing in Hamlib** |
| 22 | `get_devices` | — | *(no equivalent — device enumeration)* | `\dump_caps` (partial) | ❌ **Missing in Hamlib** |
| 23 | `select_device` | `index` (int) | *(no equivalent — device switching)* | `-m model` CLI only | ❌ **Missing in Hamlib** (CLI flag, not runtime command) |
| 24 | `get_sample_rates` | — | *(no equivalent — SDR-specific)* | — | ❌ **Missing in Hamlib** |
| 25 | `set_sample_rate` | `value` (int Hz) | *(no equivalent — SDR-specific)* | — | ❌ **Missing in Hamlib** |
| 26 | `get_antennas` | — | `get_ant` | `y` / `\get_ant` | ⚠️ **Different** — Hamlib returns antenna number; cat_gui requests a list of labeled antenna ports |
| 27 | `select_antenna` | `index` (int, 1-based) | `set_ant` | `Y` / `\set_ant` | ✅ **Maps** — antenna selection by index |
| 28 | `get_power_levels` | — | `get_level RFPOWER` | `l RFPOWER` / `\get_level RFPOWER` | ⚠️ **Different** — Hamlib returns a scalar; cat_gui requests a list of named power presets |
| 29 | `set_power` | `index` (int) | `set_level RFPOWER` | `L RFPOWER` / `\set_level RFPOWER` | ⚠️ **Different** — Hamlib uses 0.0–1.0 float; cat_gui uses preset index |
| 30 | `user_button` | `index`, optional `enabled` / `choice` | `set_func` | `U` / `\set_func` | ⚠️ **Different** — Hamlib has fixed function tokens; cat_gui supports arbitrary server-defined buttons |
| 31 | `user_text` | `index`, `text` (string) | `send_morse` (b) — closest analog | `b` / `\send_morse` | ⚠️ **Different** — Hamlib sends Morse; cat_gui sends free-form text for digital mode text input |
| 32 | `rf_usr_button` | `index`, optional `enabled` | `set_func` | `U` / `\set_func` | ⚠️ **Different** — same as `user_button` — Hamlib has no RF-domain custom button concept |
| 33 | `rf_usr_btn_config_set` | `index`, `values` (dict) | *(no equivalent)* | — | ❌ **Missing in Hamlib** |
| 34 | `get_memories` | `position` (int) | `get_mem` (channel memory read) | `\get_mem` | ⚠️ **Different** — Hamlib reads one channel at a time; cat_gui returns a list from a position |
| 35 | `save_memory` | `position`, `freq`, `mode`, `label` | `set_mem` / `set_channel` | `\set_mem` / `\set_channel` | ⚠️ **Different** — Hamlib memory has no user label field in protocol |
| 36 | `audio_hello` | `udp_port` (int) | *(no equivalent — RTP audio channel setup)* | — | ❌ **Missing in Hamlib** |

### 3. Inbound Messages (Server → GUI) → Hamlib Equivalents

Messages **received by the GUI** from the server and processed in `_handle()`.

| # | cat_gui.py `type` | Key Payload Fields | Hamlib Equivalent | Status |
|---|---|---|---|---|
| 1 | `data` | `f_start`, `f_stop`, `spectrum[]`, `smeter_dbm`, `smeter_text`, `swr` | *(no equivalent — continuous SDR push)* | ❌ **No Hamlib analog** — Hamlib uses `get_level STRENGTH` polling; no spectrum push |
| 2 | `af_local` | `af_spectrum[]`, `af_range` | *(no equivalent — locally computed AF FFT)* | ❌ **No Hamlib analog** |
| 3 | `reload_state` | Full state dict (all parameters) | *(no equivalent — full state push)* | ❌ **No Hamlib analog** — Hamlib requires individual `get_*` polls |
| 4 | `resp:ok` (via `"state"` key) | Merged state dict | `RPRT 0` (success acknowledgment only) | ⚠️ **Different** — Hamlib returns `RPRT 0`; cat_gui piggybacks full state on acknowledgment |
| 5 | `audio_port` | `port` (UDP int), `sample_rate`, `frame_ms` | *(no equivalent)* | ❌ **Missing in Hamlib** |
| 6 | `disconnected` | optional `reason` | `RPRT -1` (error response) | ⚠️ **Different** — Hamlib error is per-command; cat_gui disconnected is an async event |
| 7 | `device_list` | `devices[]` | *(no equivalent)* | ❌ **Missing in Hamlib** |
| 8 | `sample_rate_list` | `rates[]`, `current` | *(no equivalent)* | ❌ **Missing in Hamlib** |
| 9 | `antenna_list` | `antennas[]`, `current`, `device_allowed_bands` | `get_ant` response (scalar only) | ⚠️ **Different** — Hamlib returns a single antenna number; cat_gui returns full labeled list with band restrictions |
| 10 | `power_level_list` | `levels[]`, `current` | `get_level RFPOWER` (scalar) | ⚠️ **Different** — cat_gui delivers named presets list |
| 11 | `memory_list` | `memories[]` | `get_mem` (one channel) | ⚠️ **Different** — Hamlib reads one channel; cat_gui sends a page of labeled entries |
| 12 | `user_text` | `index`, `text` | *(no equivalent)* | ❌ **Missing in Hamlib** |

### 4. State Variables → Hamlib Level/Func/Parameter Mapping

Key-value pairs stored in `self.state` (populated from server-pushed JSON).

| # | cat_gui.py State Key | Type | Description | Hamlib Equivalent | Hamlib Command | Status |
|---|---|---|---|---|---|---|
| 1 | `lo_freq` | int Hz | LO A (main VFO) frequency | Frequency VFOA | `f` / `\get_freq` | ✅ **Maps** |
| 2 | `lo_b_freq` | int Hz | LO B (second VFO) frequency | Frequency VFOB | `f` (with VFO=VFOB) | ✅ **Maps** |
| 3 | `tune_freq` | int Hz | IF/tune frequency (absolute) | RIT (`j`) or XIT (`z`) — relative only | ⚠️ **Different** — Hamlib RIT/XIT is offset; this is absolute |
| 4 | `lo_active` | "A"\|"B" | Which LO/VFO is active | Current VFO | `v` / `\get_vfo` | ✅ **Maps** |
| 5 | `mode` | string | Current modulation mode label | Mode token | `m` / `\get_mode` | ⚠️ **Different** — cat_gui mode is arbitrary server string; Hamlib uses fixed enum |
| 6 | `filter_lo` / `filter_hi` | int Hz | IF passband lower/upper edges | Passband (single width int) | `m` / `\get_mode` (2nd value) | ⚠️ **Different** — Hamlib passband is a width; cat_gui uses absolute lo/hi pair |
| 7 | `ptt` | bool | Push-to-talk state | PTT state | `t` / `\get_ptt` | ✅ **Maps** |
| 8 | `split` | bool | Split TX/RX enabled | Split VFO | `s` / `\get_split_vfo` | ✅ **Maps** |
| 9 | `volume` | float 0–100 | Audio output volume | AF level | `l AF` / `\get_level AF` | ✅ **Maps** |
| 10 | `rf_gain` | float dB | RF gain | RF level | `l RF` / `\get_level RF` | ✅ **Maps** |
| 11 | `squelch` | float dBm | Squelch threshold | SQL level | `l SQL` / `\get_level SQL` | ✅ **Maps** |
| 12 | `agc_thresh` | float dB | AGC threshold | AGC level | `l AGC` / `\get_level AGC` | ⚠️ **Different** — Hamlib AGC is enum not threshold |
| 13 | `sample_rate` | int Hz | SDR sample rate | *(no equivalent)* | — | ❌ **Missing in Hamlib** |
| 14 | `zoom` | int | Spectrum zoom level | *(no equivalent)* | — | ❌ **Missing in Hamlib** |
| 15 | `running` | bool | SDR streaming active | *(no equivalent)* | — | ❌ **Missing in Hamlib** |
| 16 | `user_mod_labels` | list[str] | Server-defined mode button labels | Mode tokens | `m` / `\get_mode` | ⚠️ **Different** — fixed vs. dynamic |
| 17 | `user_mod_types` | list[str] | Mode type (normal/text/text_input) | *(no equivalent)* | — | ❌ **Missing in Hamlib** |
| 18 | `user_buttons` | list[dict] | Server-defined auxiliary buttons | `set_func` / `get_func` tokens | `U` / `u` | ⚠️ **Different** — Hamlib has fixed function set |
| 19 | `user_btn_state` | list[bool] | Toggle state per user button | `get_func` | `u` / `\get_func` | ⚠️ **Partial** |
| 20 | `user_btn_list_sel` | list[int] | List-type button selections | *(no equivalent)* | — | ❌ **Missing in Hamlib** |
| 21 | `rf_usr_btns` | list[dict] | RF domain user buttons | `set_func` / `get_func` | `U` / `u` | ⚠️ **Different** — same as user_buttons |
| 22 | `rf_usr_btn_state` | list[bool] | RF user button toggle states | `get_func` | `u` | ⚠️ **Partial** |
| 23 | `rf_usr_btn_config_vals` | dict | Per-button config parameter values | *(no equivalent)* | — | ❌ **Missing in Hamlib** |
| 24 | `antenna_index` | int (1-based) | Currently selected antenna | Antenna number | `y` / `\get_ant` | ✅ **Maps** |
| 25 | `antenna_labels` | list[str] | Named antenna port labels | *(not in Hamlib protocol)* | — | ❌ **Missing in Hamlib** |
| 26 | `antenna_allowed_bands` | list[list[str]] | Per-antenna band restrictions | *(no equivalent)* | — | ❌ **Missing in Hamlib** |
| 27 | `allowed_bands` | list[str] | Active allowed amateur bands | *(no equivalent)* | — | ❌ **Missing in Hamlib** |
| 28 | `power_index` | int | Selected TX power preset index | RFPOWER level (float 0–1) | `l RFPOWER` | ⚠️ **Different** — index vs. float |
| 29 | `power_levels` | list | Named TX power presets | *(no equivalent as list)* | — | ❌ **Missing in Hamlib** |
| 30 | `selected_bw` | int Hz | BW selector (step size) | Passband | `m` / `\get_mode` | ⚠️ **Partial** |
| 31 | `bandwidth_map` | dict | BW preset map | *(no equivalent)* | — | ❌ **Missing in Hamlib** |
| 32 | `active_device_index` | int | Currently active SDR device | *(no equivalent — SDR-specific)* | — | ❌ **Missing in Hamlib** |
| 33 | `spec_ref_rf` / `spec_ref_af` | float dB | Spectrum reference level | *(no equivalent)* | — | ❌ **Missing in Hamlib** |
| 34 | `spec_ave_rf` / `spec_ave_af` | int | Spectrum averager count | *(no equivalent)* | — | ❌ **Missing in Hamlib** |
| 35 | `toolbar_view_rf` / `toolbar_view_af` | string | Display mode (Waterfall/Spectrum) | *(no equivalent)* | — | ❌ **Missing in Hamlib** |

### 5. Hamlib Functions NOT Present in cat_gui.py

Standard Hamlib/rigctld commands that have **no counterpart** in the cat_gui.py protocol.

| # | Hamlib Command | Short | Description | Notes |
|---|---|---|---|---|
| 1 | `set_rit` / `get_rit` | `J` / `j` | Receiver Incremental Tuning (Hz offset) | cat_gui uses absolute `tune_freq`; RIT would require conversion |
| 2 | `set_xit` / `get_xit` | `Z` / `z` | Transmitter Incremental Tuning | Same as RIT note |
| 3 | `set_ts` / `get_ts` | `N` / `n` | Tuning step size in Hz | No step concept in cat_gui (uses custom BW step) |
| 4 | `set_rptr_shift` / `get_rptr_shift` | `R` / `r` | Repeater shift (FM operations) | Not relevant for SDR-focused app |
| 5 | `set_rptr_offs` / `get_rptr_offs` | `O` / `o` | Repeater offset in Hz | Same as above |
| 6 | `set_ctcss_tone` / `get_ctcss_tone` | `C` / `c` | CTCSS tone (tenths of Hz) | FM sub-tone — not supported |
| 7 | `set_dcs_code` / `get_dcs_code` | `D` / `d` | DCS code | Not supported |
| 8 | `set_ctcss_sql` / `get_ctcss_sql` | `0x90` / `0x91` | CTCSS squelch tone | Not supported |
| 9 | `set_func NB` / `get_func NB` | `U NB` / `u NB` | Noise Blanker on/off | cat_gui has no NB toggle in visible protocol (may be in user_button) |
| 10 | `set_func COMP` | `U COMP` | Speech compressor | Not supported |
| 11 | `set_func VOX` | `U VOX` | Voice-operated TX | Not supported |
| 12 | `set_func TONE` / `TSQL` | `U TONE` | CTCSS tone squelch | Not supported |
| 13 | `set_func LOCK` | `U LOCK` | VFO lock | cat_gui implements frequency lock client-side only (no server cmd) |
| 14 | `set_func AFC` | `U AFC` | Automatic Frequency Control | May be in user_button; not in explicit protocol |
| 15 | `set_func ANF` | `U ANF` | Automatic Notch Filter | May be in user_button |
| 16 | `set_func NR` | `U NR` | Noise Reduction | May be in user_button |
| 17 | `set_level PREAMP` | `L PREAMP` | Preamplifier level | Not in explicit protocol |
| 18 | `set_level ATT` | `L ATT` | Attenuator setting | Not in explicit protocol |
| 19 | `set_level MICGAIN` | `L MICGAIN` | Microphone gain | Not in explicit protocol |
| 20 | `set_level KEYSPD` | `L KEYSPD` | CW keyer speed (WPM) | Not supported |
| 21 | `set_level NOTCHF` | `L NOTCHF` | Manual notch frequency | May be in user_button/config |
| 22 | `send_morse` | `b` | Send Morse code string | Not supported |
| 23 | `get_dcd` | `0x8b` | Data Carrier Detect / squelch open | Not in explicit protocol |
| 24 | `dump_caps` | `\dump_caps` | Dump all rig capabilities | Partially covered by `get_devices` + `reload_state` |
| 25 | `set_lock_mode` | *(rigctld-only)* | Prevent mode changes from other clients | Not needed (single-client design) |

### 6. Architecture Differences Summary

```
cat_gui.py custom protocol          Hamlib rigctld
─────────────────────────────────   ──────────────────────────────────
JSON {cmd, ...} → server            \command value\n → rigctld
server pushes spectrum/state        client polls each parameter
Integrated RTP UDP audio            No audio channel
Session handshake (hello)           Stateless command/response
Dynamic mode/button labels          Fixed mode/func token set
SDR concepts (LO, zoom, sample_rate) Rig concepts (VFO, RIT, CTCSS)
Device switching at runtime         Model selected at startup (-m)
Band restriction (allowed_bands)    No band restriction in protocol
Per-device persistent config        Backend config only at start (--set-conf)
```

### 7. Mapping Coverage Summary

| Category | Total cat_gui items | ✅ Direct Map | ⚠️ Partial/Different | ❌ No Hamlib Equivalent |
|---|---|---|---|---|
| Outbound Commands | 36 | 4 (11%) | 16 (44%) | 16 (45%) |
| Inbound Messages | 12 | 0 (0%) | 5 (42%) | 7 (58%) |
| State Variables | 35 | 8 (23%) | 9 (26%) | 18 (51%) |
| **Totals** | **83** | **12 (14%)** | **30 (36%)** | **41 (49%)** |


> **`[bandwidth]` validation:** The server performs a **fatal check** (`sys.exit(1)`) at startup if any label defined in `[user_mods]` lacks a matching entry in the `[bandwidth]` section of the active device config. Always add a `[bandwidth]` entry for every custom modulation mode you define, or the server will refuse to start.
