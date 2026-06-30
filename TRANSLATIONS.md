# CAT Project — Translation Guide

This document explains the two-layer translation system used by the CAT project,
how both layers interact at runtime, and the step-by-step process for adding a
new language or extending an existing one.

---

## Table of Contents

1. [Overview — Two Translation Layers](#1-overview--two-translation-layers)
2. [Layer 1 — GUI Strings (gettext `.po` / `.mo`)](#2-layer-1--gui-strings-gettext-po--mo)
   - [File layout](#21-file-layout)
   - [How the GUI loads translations](#22-how-the-gui-loads-translations)
   - [String categories](#23-string-categories)
   - [Context-disambiguated strings (`pgettext`)](#24-context-disambiguated-strings-pgettext)
3. [Layer 2 — Device Label Overrides (TOML)](#3-layer-2--device-label-overrides-toml)
   - [File layout](#31-file-layout)
   - [How the server loads label overrides](#32-how-the-server-loads-label-overrides)
   - [Sections and the 7-character constraint](#33-sections-and-the-7-character-constraint)
4. [Adding a New Language — End-to-End Walkthrough](#4-adding-a-new-language--end-to-end-walkthrough)
   - [Step 1 — Create the `.po` file](#step-1--create-the-po-file)
   - [Step 2 — Fill in the translations](#step-2--fill-in-the-translations)
   - [Step 3 — Compile to `.mo`](#step-3--compile-to-mo)
   - [Step 4 — Create the device label override file](#step-4--create-the-device-label-override-file)
   - [Step 5 — Test the new language](#step-5--test-the-new-language)
5. [Keeping Translations Up to Date](#5-keeping-translations-up-to-date)
   - [When new GUI strings are added](#51-when-new-gui-strings-are-added)
   - [When a new device profile is added](#52-when-a-new-device-profile-is-added)
6. [Reference — Supported Languages](#6-reference--supported-languages)
7. [Quick Cheat Sheet](#7-quick-cheat-sheet)

---

## 1. Overview — Two Translation Layers

The project's UI text comes from two distinct sources that must be handled
separately.

| Source | What it covers | Translation mechanism |
|---|---|---|
| `cat_gui.py` | All static GUI text: labels, dialog titles, button captions, error messages | GNU gettext (`.po` / `.mo` files) |
| `cat_device.toml` (and per-device files like `device_xiegu_g90.toml`) | Dynamic labels defined per device profile: user buttons, mode buttons, RF buttons, antenna names, config dialog items | Per-device, per-language TOML override files (`<device_basename>_labels_XX.toml`, one per device profile — see §3.1) |

Only **`cat_server.py`** takes a `--lang` flag. `cat_gui.py` has **no**
`--lang` flag and no `[display] lang =` config key of its own — the GUI
gets its language entirely from the server it connects to. The server
advertises its locale (`"lang"`) in every state payload; the GUI applies
that value to `i18n.setup()` the first time it connects, and never changes
it again for the rest of that session.

```
cat_server.py --lang es      # server: loads es device-label TOML overrides
                              # GUI (once connected): adopts "es" and loads its own es .mo
cat_server.py --lang de      # server: loads de device-label TOML overrides
                              # GUI (once connected): adopts "de" and loads its own de .mo
cat_server.py                # lang="" → server uses English labels;
                              # GUI falls back to OS locale, then English
```

Practical implication: starting `cat_gui.py` on its own (without a server,
or before connecting) always uses the OS locale / English. The translated
UI only appears after the GUI successfully connects to a server started
with `--lang XX`.

---

## 2. Layer 1 — GUI Strings (gettext `.po` / `.mo`)

### 2.1 File layout

```
locale/
├── cat_gui.pot                   ← master template (source of truth, never edit directly)
├── en/
│   └── LC_MESSAGES/
│       ├── cat_gui.po            ← English translations (identity mappings)
│       └── cat_gui.mo            ← compiled binary loaded at runtime
├── es/
│   └── LC_MESSAGES/
│       ├── cat_gui.po            ← Spanish translations
│       └── cat_gui.mo
├── de/
│   └── LC_MESSAGES/
│       ├── cat_gui.po
│       └── cat_gui.mo
├── fr/
│   └── LC_MESSAGES/
│       ├── cat_gui.po
│       └── cat_gui.mo
└── ja/
    └── LC_MESSAGES/
        ├── cat_gui.po
        └── cat_gui.mo
```

**Key facts:**
- `.pot` — the Portable Object Template, extracted automatically from `cat_gui.py`
  by `i18n/extract.py`. It contains every translatable string with empty
  `msgstr` fields. **Never translate this file.** It is overwritten on every
  extraction run.
- `.po` — the human-editable translation file for one language. This is what
  translators work on.
- `.mo` — the binary compiled form of the `.po` file, loaded by Python's
  `gettext` module at runtime. Not human-readable. Regenerate it with
  `i18n/compile.py` after editing the `.po`.

### 2.2 How the GUI loads translations

`i18n/__init__.py` is the single entry point. `cat_gui.py` calls
`i18n.setup(lang)` once before building any Tk widget.

```python
# i18n/__init__.py — simplified
import gettext, os

_DOMAIN    = "cat_gui"
_LOCALEDIR = os.path.join(os.path.dirname(__file__), "..", "locale")

def setup(lang: str | None = None) -> None:
    languages = [lang, lang.split("_")[0]] if lang else None
    try:
        t = gettext.translation(_DOMAIN, localedir=_LOCALEDIR, languages=languages)
    except FileNotFoundError:
        t = gettext.NullTranslations()   # silent fallback to English
    t.install()
```

After `setup()` the three translation functions are available everywhere:

| Function | Use for |
|---|---|
| `_("text")` | Regular strings (the only one currently used in practice) |
| `ngettext("one item", "{n} items", n)` | Strings that change form based on a count. **Imported but not currently used anywhere in `cat_gui.py`** — there are no plural-sensitive strings in the GUI today. Available for future use. |
| `pgettext("context", "text")` | Strings that are ambiguous without extra context (see §2.4) |

Locale resolution order (GUI, `cat_gui.py`):
1. On startup, before any server connection: OS locale via the
   `LANGUAGE` / `LC_ALL` / `LANG` environment variables (handled
   internally by Python's `gettext`, since `_i18n_setup(None)` is called
   at launch).
2. On first successful connection to a server: the server's advertised
   `"lang"` value (from `--lang` passed to `cat_server.py`) overrides the
   OS locale for the rest of the session. An empty string from the server
   means "use OS locale" and is treated the same as step 1.
3. If no translation file is found for the resolved language: silent
   fallback to English (no error, no warning).

There is **no** `--lang` CLI flag and **no** `[display] lang =` config key
for `cat_gui.py` itself — locale selection happens once, automatically,
and is driven by whichever server the GUI connects to.

Locale resolution order (server, `cat_server.py`):
1. `--lang LOCALE` CLI flag (e.g. `es`, `de`, `pt_BR`). Used only to select
   which per-device label-override TOML file(s) to load (see §3). It has
   no effect on its own without a connected GUI.
2. No flag / empty string → English device labels (no override file
   lookup is attempted).

### 2.3 String categories

The `.po` files are organised with comments that group strings by UI area.
Here is a summary of every category you will encounter when translating:

| Comment group | Examples |
|---|---|
| `#. Main window` | Window title |
| `#. Toolbar view buttons` | `Waterfall`, `Spectrum`, `Zoom`, `Speed`, `SCALE`, `AVE` |
| `#. Frequency display rows` | `LO A`, `LO B`, `Tune` |
| `#. S-meter` | `Signal:`, `RST:`, `SWR:` |
| `#. Control sliders` | `Volume`, `AGC Thresh.`, `RF Gain`, `Squelch` |
| `#. Fixed hardware buttons` | `PTT`, `SPLIT`, `SWAP`, `LOCK`, `Antenna`, `Power`, `Soundcard` |
| `#. Connect / disconnect` | `Start`, `Stop`, `Connect`, `Connecting…`, `Disconnect` |
| `#. Dialog actions` | `Set`, `Apply`, `OK`, `Cancel`, `Close`, `Load`, `Rename`, `Save` |
| `#. Dialog titles` | `Set Frequency`, `Select Device`, `TX Power`, `Configure: {name}` |
| `#. Dialog body text` | `Frequency (Hz):`, `Select a device:`, `Edit label:` |
| `#. Empty-list placeholders` | `No devices configured on server.` |
| `#. Memory dialog instructions` | Long instruction string |
| `#. Messageboxes — titles` | `Device`, `Sample Rate`, `Power`, `Memory` (with `pgettext`) |
| `#. Messageboxes — bodies` | `Not connected to server.`, `Invalid port number`, … |
| `#. Connection row` | `Host:`, `Port:` |
| `#. Canvas overlays` | `● TX` |

### 2.4 Context-disambiguated strings (`pgettext`)

Some English words are used in completely different UI roles and would translate
to different words in other languages. These use `msgctxt` in the `.po` file.

```po
msgctxt "freq_display_label"
msgid "LO A"
msgstr "LO A"

msgctxt "msgbox_title"
msgid "Power"
msgstr "Potencia"
```

The context (`"freq_display_label"`, `"msgbox_title"`) is invisible to the user
but tells `pgettext` which translation to pick when the same `msgid` appears
under two different contexts. Always preserve the `msgctxt` line unchanged in
your translation.

---

## 3. Layer 2 — Device Label Overrides (TOML)

### 3.1 File layout

**Every device config file has its own, separate override file** — there is
no single shared `cat_device_labels_XX.toml` for the whole project. The
override file path is derived from the device config file's own path:

```
cat_device.toml                       ← English (no override needed; identity)
cat_device_labels_es.toml             ← Spanish overrides for cat_device.toml
cat_device_labels_de.toml             ← German overrides for cat_device.toml

device_xiegu_g90.toml                 ← Xiegu G90 device profile (English labels)
device_xiegu_g90_labels_es.toml       ← Spanish overrides for device_xiegu_g90.toml
device_xiegu_g90_labels_de.toml       ← German overrides for device_xiegu_g90.toml

device_dummy.toml                     ← Dummy/test device profile
device_dummy_labels_es.toml           ← Spanish overrides for device_dummy.toml
```

The naming pattern is always `<device_config_basename>_labels_<lang>.toml`,
placed next to the device config file it overrides. **Do not** create one
`cat_device_labels_<lang>.toml` and expect it to apply to every device — if
`cat_server.toml`'s `[devices]` section lists multiple device profiles
(e.g. `config_1 = "device_xiegu_g90.toml"`, `config_2 =
"device_dummy.toml"`), each one needs its **own** `_labels_<lang>.toml`
file. Pointing two devices at the same override file, or naming the file
without the matching device basename, means the server will silently fail
to find it and fall back to English labels for that device.

### 3.2 How the server loads label overrides

When `cat_server.py` starts with `--lang XX`, for the currently active
device profile (e.g. `device_xiegu_g90.toml`) it:

1. Derives the override file path from the device config's own path:
   `<device_base>_labels_XX.toml` (e.g. `device_xiegu_g90_labels_XX.toml`).
2. Tries the exact locale tag first (e.g. `pt_BR`), then the base language
   without region (`pt`) if the exact match isn't found.
3. If found, loads **all sections of that TOML file and flattens them into
   a single lookup dict**, keyed by the original English label text
   (section headers are for human organization only — they are not
   namespaced separately at runtime; see §3.3 note below).
4. For every label it needs to display, it looks up the English label as a
   key in that flattened dict. If found, the translated value is used; if
   not, the English label from the device profile is shown unchanged.

This means override files are **purely additive**: a missing entry causes
no error, it simply falls back to the English label. But because lookups
are flattened across all sections, **using the same English label text in
two different sections (e.g. `"Mode"` in both `[user_mods]` and
`[rf_btn_config]`) will collide** — whichever section is processed last
wins. Keep label text unique across sections within one override file to
avoid this.

### 3.3 Sections and the 7-character constraint

The override file mirrors the sections of the device profile, plus one
additional section for config-dialog item names.

```toml
[user_buttons]
# Labels shown on the 14 user-defined buttons.
# Max 7 characters — enforced by the hardware display width.
"UsrBtn"  = "UsrBot"

[user_mods]
# Labels shown in the mode row of the GUI.
# Max 7 characters.
"FT8"   = "FT8"

[rf_usr_btns]
# Labels shown on RF user buttons left of the band buttons.
# Max 7 characters.
"BtnUsr1" = "BotUsr1"

[antenna]
# Labels shown in the Antenna selector dialog.
# Max 7 characters.
"End Fed"    = "EndFed"
"Dipole 80m" = "Dip 80m"

[rf_btn_config]
# Item names inside the button-configuration dialog (slide/list/check/radio).
# These appear on screen in a dialog, NOT on a hardware button label.
# The 7-character limit does NOT apply here.
"BW"      = "Ancho de banda"
"Mode"    = "Modo"
```

> **7-character limit:** The `[user_buttons]`, `[user_mods]`, `[rf_usr_btns]`,
> and `[antenna]` sections are subject to the 7-character display limit.
> Exceeding it does not raise an error — the GUI silently truncates the
> label to 7 characters (`label[:7]`). `[rf_btn_config]` items appear in a
> resizable dialog and are not limited.
>
> **Separate 10-character limit for memory labels:** memory-slot labels
> (the names shown for stored frequency presets in the Memory dialog) are
> *not* part of the device label override system above. They have their
> own, independent length limit of 10 characters
> (`MEMORY_LABEL_MAXLEN = 10` in `cat_server.py`), also enforced by silent
> truncation. Keep this in mind when translating memory-related strings —
> 10 characters, not 7.

**Tips for fitting translations into 7 characters:**

| English | Approach | Example |
|---|---|---|
| Long word | Abbreviate | `"Silenciador"` → `"Silen."` |
| Two-word label | Remove space or shorten both | `"Dip 40m"` |
| Acronym | Keep as-is — they are universal | `"PTT"`, `"AGC"` |
| Placeholder (`BtnUsr1`) | Translate the common part only | `"BotUsr1"` |

---

## 4. Adding a New Language — End-to-End Walkthrough

This example adds **Italian** (`it`).

### Step 1 — Create the `.po` file

Start from the master template:

```bash
mkdir -p locale/it/LC_MESSAGES
cp locale/cat_gui.pot locale/it/LC_MESSAGES/cat_gui.po
```

Edit the file header inside `locale/it/LC_MESSAGES/cat_gui.po`:

```po
# Italian translation for cat_gui
# Copyright (C) 2025 cat_project contributors
#
msgid ""
msgstr ""
"Project-Id-Version: cat_gui\n"
"Language: it\n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=UTF-8\n"
"Content-Transfer-Encoding: 8bit\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\n"
```

Set `Language:` to your ISO 639-1 code. Update `Plural-Forms` for languages
that have more than two plural forms (e.g. Russian has three). Consult
[gettext plural forms reference](https://www.gnu.org/software/gettext/manual/html_node/Plural-forms.html)
if needed.

### Step 2 — Fill in the translations

Open `locale/it/LC_MESSAGES/cat_gui.po` and fill in each `msgstr` field.
Leave `msgstr ""` for any string you are unsure about — the GUI will fall
back to the English `msgid` automatically.

**Regular string:**
```po
msgid "Connect"
msgstr "Connetti"
```

**String with a placeholder** — keep `{…}` tokens exactly as-is:
```po
msgid "Cannot connect to {host}:{port}\n{detail}"
msgstr "Impossibile connettersi a {host}:{port}\n{detail}"
```

**Context-disambiguated string** — keep `msgctxt` unchanged, translate only
`msgstr`:
```po
msgctxt "msgbox_title"
msgid "Power"
msgstr "Potenza"
```

### Step 3 — Compile to `.mo`

The GUI reads the binary `.mo`, not the `.po`. Compile after every edit:

```bash
# Compile a single language
msgfmt -o locale/it/LC_MESSAGES/cat_gui.mo locale/it/LC_MESSAGES/cat_gui.po

# Or compile all languages at once
python i18n/compile.py
```

`i18n/compile.py` walks every `locale/*/LC_MESSAGES/cat_gui.po` and compiles
it in place. Any `.po` with syntax errors will be reported; the others are
compiled successfully.

### Step 4 — Create the device label override file(s)

Create one override file **per device profile** you want translated, named
after that device's own config file:
`<device_config_basename>_labels_it.toml`. There is no single shared file —
if your server config lists more than one device, repeat this for each one.

```bash
# Example: overrides for device_xiegu_g90.toml
cp device_xiegu_g90.toml device_xiegu_g90_labels_it.toml
```

(Don't actually copy the whole device profile — it's shown here only to
illustrate the naming pattern. In practice, start from a minimal file
containing only the sections/keys you want to translate; missing keys
simply fall back to English, so you don't need to mirror the entire device
profile.)

Then edit the values. Remember the 7-character limit for all sections except
`[rf_btn_config]`, and keep label text unique across sections within the
file to avoid lookup collisions (see §3.2).

A minimal Italian example:

```toml
# Italian label overrides for cat_device.toml

[user_buttons]
"UsrBtn"  = "UsrBot"    # "Btn" → "Bot" (Bottone)
"UsrLst1" = "UsrLst1"   # list-type button — unchanged

[user_mods]
"AM"   = "AM"
"FM"   = "FM"
"LSB"  = "LSB"
"USB"  = "USB"
"CW"   = "CW"
"APRS" = "APRS"
"RTTY" = "RTTY"
"FT8"  = "FT8"

[rf_usr_btns]
"BtnUsr1" = "BotUsr1"

[antenna]
"End Fed"    = "EndFed"
"Dipole 80m" = "Dip 80m"
"Dipole 40m" = "Dip 40m"
"Yagi 10m"   = "Yg 10m"

[rf_btn_config]
"BW"      = "Largh. di banda"
"Noise"   = "Rumore"
"Mode"    = "Modo"
"Profile" = "Profilo"
"Wide"    = "Largo"
"Narrow"  = "Stretto"
```

You do not need to include every key. Omit any label you want to leave in
English.

### Step 5 — Test the new language

```bash
python cat_server.py --lang it
```

Check that:
- The GUI opens without errors.
- Dialogs (Set Frequency, Select Device, Memory) show translated text.
- No label appears clipped on hardware-style buttons.
- The Antenna selector shows translated antenna names.
- The config dialog for RF user buttons shows translated item names.

---

## 5. Keeping Translations Up to Date

### 5.1 When new GUI strings are added

Whenever `cat_gui.py` gains new translatable strings, run the full update
cycle to propagate them to all existing `.po` files:

```bash
scripts/update_translations.sh
```

This script does three things in sequence:

1. **Extract** — runs `xgettext` via `i18n/extract.py` to regenerate
   `locale/cat_gui.pot` from the current source.
2. **Merge** — runs `msgmerge --update` for each existing `.po`, adding new
   `msgid` entries as untranslated (`msgstr ""`) while preserving all
   existing translations.
3. **Compile** — runs `i18n/compile.py` to recompile every `.po` to `.mo`.

After the script runs, open each `.po` file and search for entries where
`msgstr ""` (empty) or prefixed with `#, fuzzy`. Those are new or changed
strings that need human translation.

**Fuzzy matches** (`#, fuzzy`) are strings where `msgmerge` guessed a
translation from a similar old string. Review them carefully — they may be
wrong. Remove the `#, fuzzy` comment line once you have verified or corrected
the translation, then recompile.

### 5.2 When a new device profile is added

When a new `device_XXXX.toml` is created with new label names:

1. Decide which labels need translation for this device. Unlike the
   gettext layer, there is no English "reference" override file to update —
   the device profile TOML itself already contains the English labels.
2. For every language you support, create or update
   `device_XXXX_labels_<lang>.toml` (named after the new device file, not
   any shared file) and add the new labels with their translations.
   Missing keys are silently ignored at runtime — they will show in
   English until translated.

There is no automated extraction tool for TOML labels. They must be maintained
manually by cross-referencing the device profile files. Remember: each
device gets its own override file per language — never point two devices
at the same override file.

---

## 6. Reference — Supported Languages

| Code | Language | `.po` file | Label override |
|---|---|---|---|
| `en` | English | `locale/en/LC_MESSAGES/cat_gui.po` | (none needed — device profiles already use English labels) |
| `es` | Spanish | `locale/es/LC_MESSAGES/cat_gui.po` | `<device_basename>_labels_es.toml` per device |

To add another language, follow §4 and add a row to this table. Note that
the gettext `.po`/`.mo` layer (one file per language, project-wide) and the
TOML label layer (one file per device, per language) follow **different**
file-organization rules — don't assume the TOML overrides mirror the
single-file-per-language pattern of the `.po` files.

---

## 7. Quick Cheat Sheet

```
Adding a new language (e.g. Portuguese = "pt")
───────────────────────────────────────────────

1. mkdir -p locale/pt/LC_MESSAGES
2. cp locale/cat_gui.pot locale/pt/LC_MESSAGES/cat_gui.po
3. Edit the header in cat_gui.po  (Language: pt, Plural-Forms: ...)
4. Translate all msgstr fields
5. msgfmt -o locale/pt/LC_MESSAGES/cat_gui.mo locale/pt/LC_MESSAGES/cat_gui.po
6. For EACH device profile (device_xiegu_g90.toml, device_dummy.toml, ...):
     create device_xiegu_g90_labels_pt.toml, device_dummy_labels_pt.toml, etc.
     (named after that device's own file — no single shared file!)
7. Edit each *_labels_pt.toml  (≤7 chars for button/mode/antenna labels,
   ≤10 chars for memory labels; no limit in [rf_btn_config])
8. python cat_server.py --lang pt   ← test it (GUI adopts "pt" on connect;
                                       cat_gui.py has no --lang flag of its own)


Updating existing translations after source changes
────────────────────────────────────────────────────

1. scripts/update_translations.sh    (extract + merge + compile)
2. Edit each .po — fill in msgstr "" and fix #, fuzzy entries
3. python i18n/compile.py            (recompile to .mo)


Label length rule
─────────────────

Section              │ Limit
─────────────────────┼──────────────
[user_buttons]       │ 7 chars (truncated, not rejected)
[user_mods]          │ 7 chars (truncated, not rejected)
[rf_usr_btns]        │ 7 chars (truncated, not rejected)
[antenna]            │ 7 chars (truncated, not rejected)
[rf_btn_config]      │ none (dialog, not hardware button)
Memory slot labels   │ 10 chars (separate system — MEMORY_LABEL_MAXLEN,
                      │ not part of the device label override TOML files)


Device label override files — one per device, per language
─────────────────────────────────────────────────────────────
device_xiegu_g90.toml  +  --lang es  →  device_xiegu_g90_labels_es.toml
device_dummy.toml      +  --lang es  →  device_dummy_labels_es.toml
(NOT a single shared cat_device_labels_es.toml for the whole project.)


Required tools
──────────────

GNU gettext (xgettext, msgfmt, msgmerge)
  Ubuntu/Debian:  sudo apt install gettext
  macOS:          brew install gettext

Python 3.8+  (for pgettext support)
```
