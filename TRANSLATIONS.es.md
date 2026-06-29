# Proyecto CAT — Guía de Traducción

Este documento explica el sistema de traducción de dos capas utilizado por el
proyecto CAT, cómo interactúan ambas capas en tiempo de ejecución, y el proceso
paso a paso para agregar un nuevo idioma o extender uno existente.

---

## Tabla de Contenidos

1. [Descripción General — Dos Capas de Traducción](#1-descripción-general--dos-capas-de-traducción)
2. [Capa 1 — Cadenas de la GUI (gettext `.po` / `.mo`)](#2-capa-1--cadenas-de-la-gui-gettext-po--mo)
   - [Estructura de archivos](#21-estructura-de-archivos)
   - [Cómo carga la GUI las traducciones](#22-cómo-carga-la-gui-las-traducciones)
   - [Categorías de cadenas](#23-categorías-de-cadenas)
   - [Cadenas desambiguadas por contexto (`pgettext`)](#24-cadenas-desambiguadas-por-contexto-pgettext)
3. [Capa 2 — Sobrescritura de Etiquetas de Dispositivo (TOML)](#3-capa-2--sobrescritura-de-etiquetas-de-dispositivo-toml)
   - [Estructura de archivos](#31-estructura-de-archivos)
   - [Cómo carga el servidor las sobrescrituras de etiquetas](#32-cómo-carga-el-servidor-las-sobrescrituras-de-etiquetas)
   - [Secciones y la restricción de 7 caracteres](#33-secciones-y-la-restricción-de-7-caracteres)
4. [Agregar un Nuevo Idioma — Guía Completa](#4-agregar-un-nuevo-idioma--guía-completa)
   - [Paso 1 — Crear el archivo `.po`](#paso-1--crear-el-archivo-po)
   - [Paso 2 — Completar las traducciones](#paso-2--completar-las-traducciones)
   - [Paso 3 — Compilar a `.mo`](#paso-3--compilar-a-mo)
   - [Paso 4 — Crear el archivo de sobrescritura de etiquetas del dispositivo](#paso-4--crear-el-archivo-de-sobrescritura-de-etiquetas-del-dispositivo)
   - [Paso 5 — Probar el nuevo idioma](#paso-5--probar-el-nuevo-idioma)
5. [Mantener las Traducciones Actualizadas](#5-mantener-las-traducciones-actualizadas)
   - [Cuando se agregan nuevas cadenas a la GUI](#51-cuando-se-agregan-nuevas-cadenas-a-la-gui)
   - [Cuando se agrega un nuevo perfil de dispositivo](#52-cuando-se-agrega-un-nuevo-perfil-de-dispositivo)
6. [Referencia — Idiomas Soportados](#6-referencia--idiomas-soportados)
7. [Referencia Rápida](#7-referencia-rápida)

---

## 1. Descripción General — Dos Capas de Traducción

El texto de la interfaz del proyecto proviene de dos fuentes distintas que deben
gestionarse por separado.

| Fuente | Qué cubre | Mecanismo de traducción |
|---|---|---|
| `cat_gui.py` | Todo el texto estático de la GUI: etiquetas, títulos de diálogos, leyendas de botones, mensajes de error | GNU gettext (archivos `.po` / `.mo`) |
| `cat_device.toml` (y archivos por dispositivo como `device_xiegu_g90.toml`) | Etiquetas dinámicas definidas por perfil de dispositivo: botones de usuario, botones de modo, botones RF, nombres de antenas, elementos del diálogo de configuración | Archivos de sobrescritura TOML por idioma (`cat_device_labels_XX.toml`) |

Ambas capas se seleccionan simultáneamente mediante el flag `--lang` (o la
clave `[display] lang =` en `cat_gui.toml`). No se configuran de forma
independiente.

```
cat_server.py --lang es      # carga es .mo  +  cat_device_labels_es.toml
cat_server.py --lang de      # carga de .mo  +  cat_device_labels_de.toml
cat_server.py                # usa el locale del sistema operativo, luego inglés
```

---

## 2. Capa 1 — Cadenas de la GUI (gettext `.po` / `.mo`)

### 2.1 Estructura de archivos

```
locale/
├── cat_gui.pot                   ← plantilla maestra (fuente de verdad, nunca editar directamente)
├── en/
│   └── LC_MESSAGES/
│       ├── cat_gui.po            ← traducciones al inglés (asignaciones de identidad)
│       └── cat_gui.mo            ← binario compilado cargado en tiempo de ejecución
├── es/
│   └── LC_MESSAGES/
│       ├── cat_gui.po            ← traducciones al español
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

**Puntos clave:**
- `.pot` — la Plantilla de Objeto Portable, extraída automáticamente de `cat_gui.py`
  por `i18n/extract.py`. Contiene todas las cadenas traducibles con campos
  `msgstr` vacíos. **Nunca traduzca este archivo.** Se sobreescribe en cada
  ejecución de extracción.
- `.po` — el archivo de traducción editable por humanos para un idioma. Aquí
  trabajan los traductores.
- `.mo` — la forma binaria compilada del archivo `.po`, cargada por el módulo
  `gettext` de Python en tiempo de ejecución. No es legible por humanos.
  Regenerarlo con `i18n/compile.py` después de editar el `.po`.

### 2.2 Cómo carga la GUI las traducciones

`i18n/__init__.py` es el punto de entrada único. `cat_gui.py` llama a
`i18n.setup(lang)` una vez antes de construir cualquier widget de Tk.

```python
# i18n/__init__.py — simplificado
import gettext, os

_DOMAIN    = "cat_gui"
_LOCALEDIR = os.path.join(os.path.dirname(__file__), "..", "locale")

def setup(lang: str | None = None) -> None:
    languages = [lang, lang.split("_")[0]] if lang else None
    try:
        t = gettext.translation(_DOMAIN, localedir=_LOCALEDIR, languages=languages)
    except FileNotFoundError:
        t = gettext.NullTranslations()   # retroceso silencioso al inglés
    t.install()
```

Después de `setup()` las tres funciones de traducción están disponibles en
todas partes:

| Función | Se usa para |
|---|---|
| `_("texto")` | Cadenas normales |
| `ngettext("un elemento", "{n} elementos", n)` | Cadenas que cambian de forma según una cantidad |
| `pgettext("contexto", "texto")` | Cadenas ambiguas sin contexto adicional (ver §2.4) |

Orden de resolución del locale:
1. Flag CLI `--lang` (p. ej. `es`, `es_AR`)
2. `[display] lang =` en `cat_gui.toml`
3. Variables de entorno `LANGUAGE` / `LC_ALL` / `LANG`
4. Retroceso silencioso al inglés (sin error, sin advertencia)

### 2.3 Categorías de cadenas

Los archivos `.po` están organizados con comentarios que agrupan las cadenas
por área de la interfaz. A continuación se resume cada categoría que encontrará
al traducir:

| Grupo de comentario | Ejemplos |
|---|---|
| `#. Main window` | Título de la ventana |
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
| `#. Memory dialog instructions` | Cadena larga de instrucciones |
| `#. Messageboxes — titles` | `Device`, `Sample Rate`, `Power`, `Memory` (con `pgettext`) |
| `#. Messageboxes — bodies` | `Not connected to server.`, `Invalid port number`, … |
| `#. Connection row` | `Host:`, `Port:` |
| `#. Canvas overlays` | `● TX` |

### 2.4 Cadenas desambiguadas por contexto (`pgettext`)

Algunas palabras en inglés se utilizan en roles de interfaz completamente
distintos y se traducirían de forma diferente en otros idiomas. Estas usan
`msgctxt` en el archivo `.po`.

```po
msgctxt "freq_display_label"
msgid "LO A"
msgstr "LO A"

msgctxt "msgbox_title"
msgid "Power"
msgstr "Potencia"
```

El contexto (`"freq_display_label"`, `"msgbox_title"`) es invisible para el
usuario, pero indica a `pgettext` qué traducción elegir cuando el mismo `msgid`
aparece bajo dos contextos diferentes. Conserve siempre la línea `msgctxt` sin
cambios en su traducción.

---

## 3. Capa 2 — Sobrescritura de Etiquetas de Dispositivo (TOML)

### 3.1 Estructura de archivos

Los archivos de sobrescritura residen en la raíz del proyecto junto a los TOML
de perfil de dispositivo:

```
cat_device_labels_en.toml    ← Inglés (asignaciones de identidad, plantilla de referencia)
cat_device_labels_es.toml    ← Español
cat_device_labels_de.toml    ← Alemán (crear al agregar etiquetas de dispositivo en alemán)
...
device_xiegu_g90.toml        ← Perfil de dispositivo Xiegu G90 (define etiquetas en inglés)
device_dummy.toml            ← Perfil de dispositivo de prueba
```

### 3.2 Cómo carga el servidor las sobrescrituras de etiquetas

Cuando `cat_server.py` arranca con `--lang XX`:

1. Carga el perfil de dispositivo activo (p. ej. `device_xiegu_g90.toml`).
2. Busca `cat_device_labels_XX.toml` en el mismo directorio.
3. Para cada etiqueta que necesita mostrar, realiza una búsqueda en el archivo
   de sobrescritura. Si la etiqueta en inglés se encuentra como clave, se usa
   el valor traducido. Si no existe sobrescritura, se muestra la etiqueta en
   inglés del perfil de dispositivo sin cambios.

Esto significa que los archivos de sobrescritura son **puramente aditivos**: una
entrada faltante no causa ningún error, simplemente retrocede a la etiqueta en
inglés.

### 3.3 Secciones y la restricción de 7 caracteres

El archivo de sobrescritura refleja las secciones del perfil de dispositivo,
más una sección adicional para los nombres de elementos del diálogo de
configuración.

```toml
[user_buttons]
# Etiquetas mostradas en los 14 botones definidos por el usuario.
# Máx. 7 caracteres — impuesto por el ancho de la pantalla del hardware.
"UsrBtn"  = "UsrBot"

[user_mods]
# Etiquetas mostradas en la fila de modos de la GUI.
# Máx. 7 caracteres.
"FT8"   = "FT8"

[rf_usr_btns]
# Etiquetas mostradas en los botones RF de usuario a la izquierda de los botones de banda.
# Máx. 7 caracteres.
"BtnUsr1" = "BotUsr1"

[antenna]
# Etiquetas mostradas en el diálogo selector de antena.
# Máx. 7 caracteres.
"End Fed"    = "EndFed"
"Dipole 80m" = "Dip 80m"

[rf_btn_config]
# Nombres de elementos dentro del diálogo de configuración de botones (slide/list/check/radio).
# Aparecen en pantalla en un diálogo, NO en una etiqueta de botón de hardware.
# La restricción de 7 caracteres NO aplica aquí.
"BW"      = "Ancho de banda"
"Mode"    = "Modo"
```

> **Límite de 7 caracteres:** Las secciones `[user_buttons]`, `[user_mods]`,
> `[rf_usr_btns]` y `[antenna]` están sujetas al límite de 7 caracteres para
> pantallas de hardware. Superarlo hará que la etiqueta sea recortada o
> rechazada por la GUI. Los elementos de `[rf_btn_config]` aparecen en un
> diálogo redimensionable y no tienen este límite.

**Consejos para ajustar traducciones a 7 caracteres:**

| Inglés | Estrategia | Ejemplo |
|---|---|---|
| Palabra larga | Abreviar | `"Silenciador"` → `"Silen."` |
| Etiqueta de dos palabras | Eliminar espacio o acortar ambas | `"Dip 40m"` |
| Sigla | Dejar igual — son universales | `"PTT"`, `"AGC"` |
| Marcador de posición (`BtnUsr1`) | Traducir solo la parte común | `"BotUsr1"` |

---

## 4. Agregar un Nuevo Idioma — Guía Completa

Este ejemplo agrega **italiano** (`it`).

### Paso 1 — Crear el archivo `.po`

Comience desde la plantilla maestra:

```bash
mkdir -p locale/it/LC_MESSAGES
cp locale/cat_gui.pot locale/it/LC_MESSAGES/cat_gui.po
```

Edite el encabezado del archivo `locale/it/LC_MESSAGES/cat_gui.po`:

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

Establezca `Language:` con su código ISO 639-1. Actualice `Plural-Forms` para
idiomas que tengan más de dos formas plurales (p. ej. el ruso tiene tres).
Consulte la
[referencia de formas plurales de gettext](https://www.gnu.org/software/gettext/manual/html_node/Plural-forms.html)
si es necesario.

### Paso 2 — Completar las traducciones

Abra `locale/it/LC_MESSAGES/cat_gui.po` y complete cada campo `msgstr`.
Deje `msgstr ""` para cualquier cadena de la que no esté seguro — la GUI
retrocederá automáticamente al `msgid` en inglés.

**Cadena normal:**
```po
msgid "Connect"
msgstr "Connetti"
```

**Cadena con marcadores de posición** — conserve los tokens `{…}` exactamente
como están:
```po
msgid "Cannot connect to {host}:{port}\n{detail}"
msgstr "Impossibile connettersi a {host}:{port}\n{detail}"
```

**Cadena desambiguada por contexto** — conserve `msgctxt` sin cambios, traduzca
solo `msgstr`:
```po
msgctxt "msgbox_title"
msgid "Power"
msgstr "Potenza"
```

### Paso 3 — Compilar a `.mo`

La GUI lee el binario `.mo`, no el `.po`. Compile después de cada edición:

```bash
# Compilar un solo idioma
msgfmt -o locale/it/LC_MESSAGES/cat_gui.mo locale/it/LC_MESSAGES/cat_gui.po

# O compilar todos los idiomas a la vez
python i18n/compile.py
```

`i18n/compile.py` recorre todos los `locale/*/LC_MESSAGES/cat_gui.po` y los
compila en su lugar. Se reportará cualquier `.po` con errores de sintaxis; los
demás se compilarán correctamente.

### Paso 4 — Crear el archivo de sobrescritura de etiquetas del dispositivo

Cree `cat_device_labels_it.toml` en la raíz del proyecto. Use el archivo de
referencia en inglés como punto de partida:

```bash
cp cat_device_labels_en.toml cat_device_labels_it.toml
```

Luego edite los valores. Recuerde el límite de 7 caracteres para todas las
secciones excepto `[rf_btn_config]`.

Ejemplo mínimo en italiano:

```toml
# Italian label overrides for cat_device.toml

[user_buttons]
"UsrBtn"  = "UsrBot"    # "Btn" → "Bot" (Bottone)
"UsrLst1" = "UsrLst1"   # botón de tipo lista — sin cambios

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

No es necesario incluir todas las claves. Omita cualquier etiqueta que desee
dejar en inglés.

### Paso 5 — Probar el nuevo idioma

```bash
python cat_server.py --lang it
```

Verifique que:
- La GUI se abra sin errores.
- Los diálogos (Set Frequency, Select Device, Memory) muestren el texto traducido.
- Ninguna etiqueta aparezca recortada en los botones de estilo hardware.
- El selector de antena muestre los nombres de antena traducidos.
- El diálogo de configuración de los botones RF muestre los nombres de elementos traducidos.

---

## 5. Mantener las Traducciones Actualizadas

### 5.1 Cuando se agregan nuevas cadenas a la GUI

Cada vez que `cat_gui.py` incorpore nuevas cadenas traducibles, ejecute el
ciclo de actualización completo para propagarlas a todos los archivos `.po`
existentes:

```bash
scripts/update_translations.sh
```

Este script realiza tres acciones en secuencia:

1. **Extraer** — ejecuta `xgettext` a través de `i18n/extract.py` para
   regenerar `locale/cat_gui.pot` desde el código fuente actual.
2. **Fusionar** — ejecuta `msgmerge --update` para cada `.po` existente,
   añadiendo nuevas entradas `msgid` sin traducir (`msgstr ""`) y preservando
   todas las traducciones existentes.
3. **Compilar** — ejecuta `i18n/compile.py` para recompilar todos los `.po`
   a `.mo`.

Tras ejecutar el script, abra cada archivo `.po` y busque entradas donde
`msgstr ""` (vacío) o con el prefijo `#, fuzzy`. Esas son cadenas nuevas o
modificadas que necesitan traducción humana.

**Coincidencias difusas** (`#, fuzzy`) son cadenas donde `msgmerge` adivinó
una traducción a partir de una cadena antigua similar. Revíselas con cuidado —
pueden ser incorrectas. Elimine la línea de comentario `#, fuzzy` una vez que
haya verificado o corregido la traducción, luego recompile.

### 5.2 Cuando se agrega un nuevo perfil de dispositivo

Cuando se crea un nuevo `device_XXXX.toml` con nuevos nombres de etiquetas:

1. Añada las nuevas etiquetas a `cat_device_labels_en.toml` (asignaciones de
   identidad en inglés) para que siga siendo la plantilla de referencia.
2. Para cada idioma soportado, abra `cat_device_labels_XX.toml` y agregue las
   nuevas etiquetas con sus traducciones. Las claves faltantes se ignoran
   silenciosamente en tiempo de ejecución — aparecerán en inglés hasta que sean
   traducidas.

No existe una herramienta de extracción automatizada para etiquetas TOML. Deben
mantenerse manualmente consultando los archivos de perfil de dispositivo.

---

## 6. Referencia — Idiomas Soportados

| Código | Idioma | Archivo `.po` | Sobrescritura de etiquetas |
|---|---|---|---|
| `en` | Inglés | `locale/en/LC_MESSAGES/cat_gui.po` | `cat_device_labels_en.toml` |
| `es` | Español | `locale/es/LC_MESSAGES/cat_gui.po` | `cat_device_labels_es.toml` |
| `de` | Alemán | `locale/de/LC_MESSAGES/cat_gui.po` | `cat_device_labels_de.toml` |
| `fr` | Francés | `locale/fr/LC_MESSAGES/cat_gui.po` | `cat_device_labels_fr.toml` |
| `ja` | Japonés | `locale/ja/LC_MESSAGES/cat_gui.po` | `cat_device_labels_ja.toml` |

Para agregar otro idioma, siga el §4 y añada una fila a esta tabla.

---

## 7. Referencia Rápida

```
Agregar un nuevo idioma (p. ej. portugués = "pt")
──────────────────────────────────────────────────

1. mkdir -p locale/pt/LC_MESSAGES
2. cp locale/cat_gui.pot locale/pt/LC_MESSAGES/cat_gui.po
3. Editar el encabezado en cat_gui.po  (Language: pt, Plural-Forms: ...)
4. Traducir todos los campos msgstr
5. msgfmt -o locale/pt/LC_MESSAGES/cat_gui.mo locale/pt/LC_MESSAGES/cat_gui.po
6. cp cat_device_labels_en.toml cat_device_labels_pt.toml
7. Editar cat_device_labels_pt.toml  (≤7 caracteres para etiquetas de botones!)
8. python cat_server.py --lang pt   ← probar


Actualizar traducciones existentes tras cambios en el código fuente
────────────────────────────────────────────────────────────────────

1. scripts/update_translations.sh    (extraer + fusionar + compilar)
2. Editar cada .po — completar msgstr "" y corregir entradas #, fuzzy
3. python i18n/compile.py            (recompilar a .mo)


Regla de longitud de etiquetas
───────────────────────────────

Sección              │ ¿Límite de 7 caracteres?
─────────────────────┼──────────────────────────
[user_buttons]       │ SÍ
[user_mods]          │ SÍ
[rf_usr_btns]        │ SÍ
[antenna]            │ SÍ
[rf_btn_config]      │ NO  (diálogo, no botón de hardware)


Herramientas requeridas
────────────────────────

GNU gettext (xgettext, msgfmt, msgmerge)
  Ubuntu/Debian:  sudo apt install gettext
  macOS:          brew install gettext

Python 3.8+  (para soporte de pgettext)
```
