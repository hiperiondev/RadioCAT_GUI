# Proyecto CAT — Guía de Traducción

Este documento explica el sistema de traducción de dos capas que usa el
proyecto CAT, cómo interactúan ambas capas en tiempo de ejecución, y el
proceso paso a paso para añadir un nuevo idioma o extender uno existente.

---

## Tabla de contenidos

1. [Resumen — Dos capas de traducción](#1-resumen--dos-capas-de-traducción)
2. [Capa 1 — Cadenas de la GUI (gettext `.po` / `.mo`)](#2-capa-1--cadenas-de-la-gui-gettext-po--mo)
   - [Estructura de archivos](#21-estructura-de-archivos)
   - [Cómo carga la GUI las traducciones](#22-cómo-carga-la-gui-las-traducciones)
   - [Categorías de cadenas](#23-categorías-de-cadenas)
   - [Cadenas con contexto (`pgettext`)](#24-cadenas-con-contexto-pgettext)
3. [Capa 2 — Sobrescritura de etiquetas de dispositivo (TOML)](#3-capa-2--sobrescritura-de-etiquetas-de-dispositivo-toml)
   - [Estructura de archivos](#31-estructura-de-archivos)
   - [Cómo carga el servidor las sobrescrituras de etiquetas](#32-cómo-carga-el-servidor-las-sobrescrituras-de-etiquetas)
   - [Secciones y la restricción de 7 caracteres](#33-secciones-y-la-restricción-de-7-caracteres)
4. [Añadir un nuevo idioma — Guía completa](#4-añadir-un-nuevo-idioma--guía-completa)
   - [Paso 1 — Crear el archivo `.po`](#paso-1--crear-el-archivo-po)
   - [Paso 2 — Completar las traducciones](#paso-2--completar-las-traducciones)
   - [Paso 3 — Compilar a `.mo`](#paso-3--compilar-a-mo)
   - [Paso 4 — Crear el/los archivo(s) de sobrescritura de etiquetas de dispositivo](#paso-4--crear-el-los-archivo-s-de-sobrescritura-de-etiquetas-de-dispositivo)
   - [Paso 5 — Probar el nuevo idioma](#paso-5--probar-el-nuevo-idioma)
5. [Mantener las traducciones actualizadas](#5-mantener-las-traducciones-actualizadas)
   - [Cuando se añaden nuevas cadenas a la GUI](#51-cuando-se-añaden-nuevas-cadenas-a-la-gui)
   - [Cuando se añade un nuevo perfil de dispositivo](#52-cuando-se-añade-un-nuevo-perfil-de-dispositivo)
6. [Referencia — Idiomas soportados](#6-referencia--idiomas-soportados)
7. [Hoja de referencia rápida](#7-hoja-de-referencia-rápida)

---

## 1. Resumen — Dos capas de traducción

El texto de la interfaz del proyecto proviene de dos fuentes distintas que
deben gestionarse por separado.

| Fuente | Qué cubre | Mecanismo de traducción |
|---|---|---|
| `cat_gui.py` | Todo el texto estático de la GUI: etiquetas, títulos de diálogos, leyendas de botones, mensajes de error | GNU gettext (archivos `.po` / `.mo`) |
| `cat_device.toml` (y archivos por dispositivo como `device_xiegu_g90.toml`) | Etiquetas dinámicas definidas por perfil de dispositivo: botones de usuario, botones de modo, botones de RF, nombres de antena, elementos del diálogo de configuración | Archivos de sobrescritura TOML por dispositivo y por idioma (`<nombre_base_dispositivo>_labels_XX.toml`, uno por perfil de dispositivo — ver §3.1) |

Solo **`cat_server.py`** acepta un indicador `--lang`. `cat_gui.py` **no**
tiene indicador `--lang` ni clave de configuración `[display] lang =`
propia — la GUI obtiene su idioma completamente del servidor al que se
conecta. El servidor anuncia su locale (`"lang"`) en cada payload de
estado; la GUI aplica ese valor a `i18n.setup()` la primera vez que se
conecta, y no vuelve a cambiarlo durante el resto de esa sesión.

```
cat_server.py --lang es      # servidor: carga las sobrescrituras TOML de etiquetas en es
                              # GUI (al conectar): adopta "es" y carga su propio .mo en es
cat_server.py --lang de      # servidor: carga las sobrescrituras TOML de etiquetas en de
                              # GUI (al conectar): adopta "de" y carga su propio .mo en de
cat_server.py                # lang="" → el servidor usa etiquetas en inglés;
                              # la GUI recurre al locale del sistema operativo y luego a inglés
```

Implicación práctica: iniciar `cat_gui.py` por sí solo (sin servidor, o
antes de conectarse) siempre usa el locale del sistema operativo / inglés.
La interfaz traducida solo aparece después de que la GUI se conecte
exitosamente a un servidor iniciado con `--lang XX`.

---

## 2. Capa 1 — Cadenas de la GUI (gettext `.po` / `.mo`)

### 2.1 Estructura de archivos

```
locale/
├── cat_gui.pot                   ← plantilla maestra (fuente de la verdad, nunca editar directamente)
├── en/
│   └── LC_MESSAGES/
│       ├── cat_gui.po            ← traducciones al inglés (mapeos de identidad)
│       └── cat_gui.mo            ← binario compilado, cargado en tiempo de ejecución
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

**Datos clave:**
- `.pot` — la Plantilla de Objeto Portable, extraída automáticamente de
  `cat_gui.py` por `i18n/extract.py`. Contiene cada cadena traducible con
  el campo `msgstr` vacío. **Nunca traducir este archivo.** Se sobrescribe
  en cada ejecución de extracción.
- `.po` — el archivo de traducción editable por humanos para un idioma.
  Esto es lo que trabajan los traductores.
- `.mo` — la forma binaria compilada del archivo `.po`, cargada por el
  módulo `gettext` de Python en tiempo de ejecución. No es legible por
  humanos. Regenerarlo con `i18n/compile.py` después de editar el `.po`.

### 2.2 Cómo carga la GUI las traducciones

`i18n/__init__.py` es el único punto de entrada. `cat_gui.py` llama a
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
        t = gettext.NullTranslations()   # recurre silenciosamente al inglés
    t.install()
```

Después de `setup()` las tres funciones de traducción están disponibles en
todas partes:

| Función | Uso |
|---|---|
| `_("text")` | Cadenas regulares (la única usada actualmente en la práctica) |
| `ngettext("one item", "{n} items", n)` | Cadenas que cambian de forma según un conteo. **Importada pero actualmente sin uso en ningún lugar de `cat_gui.py`** — hoy no existen cadenas sensibles al plural en la GUI. Disponible para uso futuro. |
| `pgettext("context", "text")` | Cadenas ambiguas sin contexto adicional (ver §2.4) |

Orden de resolución de locale (GUI, `cat_gui.py`):
1. Al iniciar, antes de conectarse a cualquier servidor: locale del
   sistema operativo mediante las variables de entorno `LANGUAGE` /
   `LC_ALL` / `LANG` (gestionado internamente por el módulo `gettext` de
   Python, ya que `_i18n_setup(None)` se llama al arrancar).
2. Al conectarse exitosamente por primera vez a un servidor: el valor
   `"lang"` anunciado por el servidor (proveniente del `--lang` pasado a
   `cat_server.py`) reemplaza el locale del sistema operativo durante el
   resto de la sesión. Una cadena vacía del servidor significa "usar el
   locale del sistema operativo" y se trata igual que el paso 1.
3. Si no se encuentra archivo de traducción para el idioma resuelto: se
   recurre silenciosamente al inglés (sin error, sin advertencia).

**No** existe un indicador `--lang` de línea de comandos ni una clave de
configuración `[display] lang =` para `cat_gui.py` en sí — la selección de
locale ocurre una sola vez, automáticamente, y depende de a qué servidor
se conecte la GUI.

Orden de resolución de locale (servidor, `cat_server.py`):
1. Indicador de línea de comandos `--lang LOCALE` (p. ej. `es`, `de`,
   `pt_BR`). Se usa únicamente para seleccionar qué archivo(s) TOML de
   sobrescritura de etiquetas por dispositivo cargar (ver §3). No tiene
   efecto por sí solo sin una GUI conectada.
2. Sin indicador / cadena vacía → etiquetas de dispositivo en inglés (no
   se intenta buscar ningún archivo de sobrescritura).

### 2.3 Categorías de cadenas

Los archivos `.po` están organizados con comentarios que agrupan las
cadenas por área de la interfaz. Aquí hay un resumen de cada categoría que
encontrarás al traducir:

| Grupo de comentarios | Ejemplos |
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
| `#. Memory dialog instructions` | Cadena de instrucciones larga |
| `#. Messageboxes — titles` | `Device`, `Sample Rate`, `Power`, `Memory` (con `pgettext`) |
| `#. Messageboxes — bodies` | `Not connected to server.`, `Invalid port number`, … |
| `#. Connection row` | `Host:`, `Port:` |
| `#. Canvas overlays` | `● TX` |

### 2.4 Cadenas con contexto (`pgettext`)

Algunas palabras en inglés se usan en roles de interfaz completamente
distintos y se traducirían a palabras diferentes en otros idiomas. Estas
usan `msgctxt` en el archivo `.po`.

```po
msgctxt "freq_display_label"
msgid "LO A"
msgstr "LO A"

msgctxt "msgbox_title"
msgid "Power"
msgstr "Potencia"
```

El contexto (`"freq_display_label"`, `"msgbox_title"`) es invisible para
el usuario, pero le indica a `pgettext` qué traducción elegir cuando el
mismo `msgid` aparece bajo dos contextos diferentes. Siempre conserva la
línea `msgctxt` sin cambios en tu traducción.

---

## 3. Capa 2 — Sobrescritura de etiquetas de dispositivo (TOML)

### 3.1 Estructura de archivos

**Cada archivo de configuración de dispositivo tiene su propio archivo de
sobrescritura, separado** — no existe un único `cat_device_labels_XX.toml`
compartido para todo el proyecto. La ruta del archivo de sobrescritura se
deriva de la propia ruta del archivo de configuración del dispositivo:

```
cat_device.toml                       ← Inglés (no necesita sobrescritura; es la identidad)
cat_device_labels_es.toml             ← Sobrescrituras en español para cat_device.toml
cat_device_labels_de.toml             ← Sobrescrituras en alemán para cat_device.toml

device_xiegu_g90.toml                 ← Perfil del dispositivo Xiegu G90 (etiquetas en inglés)
device_xiegu_g90_labels_es.toml       ← Sobrescrituras en español para device_xiegu_g90.toml
device_xiegu_g90_labels_de.toml       ← Sobrescrituras en alemán para device_xiegu_g90.toml

device_dummy.toml                     ← Perfil de dispositivo ficticio/de prueba
device_dummy_labels_es.toml           ← Sobrescrituras en español para device_dummy.toml
```

El patrón de nombres es siempre
`<nombre_base_config_dispositivo>_labels_<idioma>.toml`, ubicado junto al
archivo de configuración del dispositivo que sobrescribe. **No** crees un
único `cat_device_labels_<idioma>.toml` esperando que se aplique a todos
los dispositivos — si la sección `[devices]` de `cat_server.toml` enumera
varios perfiles de dispositivo (p. ej. `config_1 = "device_xiegu_g90.toml"`,
`config_2 = "device_dummy.toml"`), cada uno necesita su **propio** archivo
`_labels_<idioma>.toml`. Apuntar dos dispositivos al mismo archivo de
sobrescritura, o nombrar el archivo sin el nombre base del dispositivo
correspondiente, significa que el servidor no lo encontrará y recurrirá
silenciosamente a las etiquetas en inglés para ese dispositivo.

### 3.2 Cómo carga el servidor las sobrescrituras de etiquetas

Cuando `cat_server.py` arranca con `--lang XX`, para el perfil de
dispositivo activo en ese momento (p. ej. `device_xiegu_g90.toml`):

1. Deriva la ruta del archivo de sobrescritura a partir de la propia ruta
   de la configuración del dispositivo:
   `<base_dispositivo>_labels_XX.toml` (p. ej.
   `device_xiegu_g90_labels_XX.toml`).
2. Prueba primero la etiqueta de locale exacta (p. ej. `pt_BR`), y luego
   el idioma base sin región (`pt`) si no se encuentra la coincidencia
   exacta.
3. Si lo encuentra, carga **todas las secciones de ese archivo TOML y las
   aplana en un único diccionario de búsqueda**, indexado por el texto de
   la etiqueta original en inglés (los encabezados de sección son solo
   para organización humana — no están separados por espacios de nombres
   en tiempo de ejecución; ver la nota de §3.3 más abajo).
4. Para cada etiqueta que necesita mostrar, busca la etiqueta en inglés
   como clave en ese diccionario aplanado. Si la encuentra, usa el valor
   traducido; si no, muestra sin cambios la etiqueta en inglés del perfil
   del dispositivo.

Esto significa que los archivos de sobrescritura son **puramente
aditivos**: una entrada faltante no causa ningún error, simplemente
recurre a la etiqueta en inglés. Pero como las búsquedas se aplanan entre
todas las secciones, **usar el mismo texto de etiqueta en inglés en dos
secciones distintas (p. ej. `"Mode"` tanto en `[user_mods]` como en
`[rf_btn_config]`) provocará un conflicto** — gana la que se procese al
final. Mantén el texto de las etiquetas único entre secciones dentro de un
mismo archivo de sobrescritura para evitar esto.

### 3.3 Secciones y la restricción de 7 caracteres

El archivo de sobrescritura refleja las secciones del perfil del
dispositivo, más una sección adicional para los nombres de elementos del
diálogo de configuración.

```toml
[user_buttons]
# Etiquetas mostradas en los 14 botones definidos por el usuario.
# Máximo 7 caracteres — impuesto por el ancho de la pantalla del hardware.
"UsrBtn"  = "UsrBot"

[user_mods]
# Etiquetas mostradas en la fila de modos de la GUI.
# Máximo 7 caracteres.
"FT8"   = "FT8"

[rf_usr_btns]
# Etiquetas mostradas en los botones de usuario de RF, a la izquierda de
# los botones de banda.
# Máximo 7 caracteres.
"BtnUsr1" = "BotUsr1"

[antenna]
# Etiquetas mostradas en el diálogo selector de antena.
# Máximo 7 caracteres.
"End Fed"    = "EndFed"
"Dipole 80m" = "Dip 80m"

[rf_btn_config]
# Nombres de elementos dentro del diálogo de configuración de botones
# (deslizador/lista/casilla/radio).
# Estos aparecen en pantalla en un diálogo, NO en una etiqueta de botón de hardware.
# El límite de 7 caracteres NO se aplica aquí.
"BW"      = "Ancho de banda"
"Mode"    = "Modo"
```

> **Límite de 7 caracteres:** Las secciones `[user_buttons]`,
> `[user_mods]`, `[rf_usr_btns]` y `[antenna]` están sujetas al límite de
> visualización de 7 caracteres. Excederlo no genera un error — la GUI
> trunca silenciosamente la etiqueta a 7 caracteres (`label[:7]`). Los
> elementos de `[rf_btn_config]` aparecen en un diálogo redimensionable y
> no tienen límite.
>
> **Límite separado de 10 caracteres para las etiquetas de memoria:** las
> etiquetas de las posiciones de memoria (los nombres mostrados para las
> frecuencias preestablecidas guardadas en el diálogo de Memoria) *no*
> forman parte del sistema de sobrescritura de etiquetas de dispositivo
> descrito arriba. Tienen su propio límite de longitud independiente de
> 10 caracteres (`MEMORY_LABEL_MAXLEN = 10` en `cat_server.py`), también
> impuesto mediante truncado silencioso. Tenlo en cuenta al traducir
> cadenas relacionadas con la memoria — 10 caracteres, no 7.

**Consejos para ajustar las traducciones a 7 caracteres:**

| Inglés | Estrategia | Ejemplo |
|---|---|---|
| Palabra larga | Abreviar | `"Silenciador"` → `"Silen."` |
| Etiqueta de dos palabras | Quitar el espacio o acortar ambas | `"Dip 40m"` |
| Sigla | Mantener tal cual — son universales | `"PTT"`, `"AGC"` |
| Marcador de posición (`BtnUsr1`) | Traducir solo la parte común | `"BotUsr1"` |

---

## 4. Añadir un nuevo idioma — Guía completa

Este ejemplo añade el **italiano** (`it`).

### Paso 1 — Crear el archivo `.po`

Parte de la plantilla maestra:

```bash
mkdir -p locale/it/LC_MESSAGES
cp locale/cat_gui.pot locale/it/LC_MESSAGES/cat_gui.po
```

Edita el encabezado del archivo dentro de
`locale/it/LC_MESSAGES/cat_gui.po`:

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

Establece `Language:` con tu código ISO 639-1. Actualiza `Plural-Forms`
para idiomas que tengan más de dos formas de plural (p. ej. el ruso tiene
tres). Consulta la
[referencia de formas plurales de gettext](https://www.gnu.org/software/gettext/manual/html_node/Plural-forms.html)
si lo necesitas.

### Paso 2 — Completar las traducciones

Abre `locale/it/LC_MESSAGES/cat_gui.po` y completa cada campo `msgstr`.
Deja `msgstr ""` para cualquier cadena de la que no estés seguro — la GUI
recurrirá automáticamente al `msgid` en inglés.

**Cadena regular:**
```po
msgid "Connect"
msgstr "Connetti"
```

**Cadena con un marcador de posición** — mantén los tokens `{…}`
exactamente igual:
```po
msgid "Cannot connect to {host}:{port}\n{detail}"
msgstr "Impossibile connettersi a {host}:{port}\n{detail}"
```

**Cadena con contexto** — mantén `msgctxt` sin cambios, traduce solo
`msgstr`:
```po
msgctxt "msgbox_title"
msgid "Power"
msgstr "Potenza"
```

### Paso 3 — Compilar a `.mo`

La GUI lee el binario `.mo`, no el `.po`. Compila después de cada edición:

```bash
# Compilar un solo idioma
msgfmt -o locale/it/LC_MESSAGES/cat_gui.mo locale/it/LC_MESSAGES/cat_gui.po

# O compilar todos los idiomas a la vez
python i18n/compile.py
```

`i18n/compile.py` recorre cada `locale/*/LC_MESSAGES/cat_gui.po` y lo
compila in situ. Cualquier `.po` con errores de sintaxis se informará; el
resto se compila correctamente.

### Paso 4 — Crear el/los archivo(s) de sobrescritura de etiquetas de dispositivo

Crea un archivo de sobrescritura **por cada perfil de dispositivo** que
quieras traducir, nombrado según el propio archivo de configuración de ese
dispositivo: `<nombre_base_config_dispositivo>_labels_it.toml`. No existe
un único archivo compartido — si la configuración de tu servidor enumera
más de un dispositivo, repite esto para cada uno.

```bash
# Ejemplo: sobrescrituras para device_xiegu_g90.toml
cp device_xiegu_g90.toml device_xiegu_g90_labels_it.toml
```

(En realidad no copies todo el perfil del dispositivo — se muestra así
solo para ilustrar el patrón de nombres. En la práctica, comienza con un
archivo mínimo que contenga solo las secciones/claves que quieras
traducir; las claves faltantes simplemente recurren al inglés, así que no
necesitas reflejar todo el perfil del dispositivo.)

Luego edita los valores. Recuerda el límite de 7 caracteres para todas las
secciones excepto `[rf_btn_config]`, y mantén el texto de las etiquetas
único entre secciones dentro del archivo para evitar conflictos de
búsqueda (ver §3.2).

Un ejemplo mínimo en italiano:

```toml
# Sobrescrituras de etiquetas en italiano para cat_device.toml

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

No es necesario incluir cada clave. Omite cualquier etiqueta que quieras
dejar en inglés.

### Paso 5 — Probar el nuevo idioma

```bash
python cat_server.py --lang it
```

Verifica que:
- La GUI se abre sin errores.
- Los diálogos (Set Frequency, Select Device, Memory) muestran texto
  traducido.
- Ninguna etiqueta aparece recortada en los botones de estilo hardware.
- El selector de antena muestra los nombres de antena traducidos.
- El diálogo de configuración de los botones de usuario de RF muestra los
  nombres de elementos traducidos.

---

## 5. Mantener las traducciones actualizadas

### 5.1 Cuando se añaden nuevas cadenas a la GUI

Cada vez que `cat_gui.py` incorpora nuevas cadenas traducibles, ejecuta el
ciclo completo de actualización para propagarlas a todos los archivos
`.po` existentes:

```bash
scripts/update_translations.sh
```

Este script hace tres cosas en secuencia:

1. **Extraer** — ejecuta `xgettext` a través de `i18n/extract.py` para
   regenerar `locale/cat_gui.pot` a partir del código fuente actual.
2. **Combinar** — ejecuta `msgmerge --update` para cada `.po` existente,
   añadiendo nuevas entradas `msgid` como no traducidas (`msgstr ""`) y
   preservando todas las traducciones existentes.
3. **Compilar** — ejecuta `i18n/compile.py` para recompilar cada `.po` a
   `.mo`.

Después de que el script se ejecute, abre cada archivo `.po` y busca
entradas donde `msgstr ""` esté vacío o tenga el prefijo `#, fuzzy`. Esas
son cadenas nuevas o modificadas que necesitan traducción humana.

Las **coincidencias difusas** (`#, fuzzy`) son cadenas donde `msgmerge`
adivinó una traducción a partir de una cadena anterior similar. Revísalas
con cuidado — pueden estar equivocadas. Elimina la línea de comentario
`#, fuzzy` una vez que hayas verificado o corregido la traducción, y luego
recompila.

### 5.2 Cuando se añade un nuevo perfil de dispositivo

Cuando se crea un nuevo `device_XXXX.toml` con nombres de etiquetas
nuevos:

1. Decide qué etiquetas necesitan traducción para este dispositivo. A
   diferencia de la capa gettext, no existe un archivo de sobrescritura
   "de referencia" en inglés que actualizar — el propio TOML del perfil
   del dispositivo ya contiene las etiquetas en inglés.
2. Para cada idioma que soportes, crea o actualiza
   `device_XXXX_labels_<idioma>.toml` (nombrado según el nuevo archivo de
   dispositivo, no según ningún archivo compartido) y añade las nuevas
   etiquetas con sus traducciones. Las claves faltantes se ignoran
   silenciosamente en tiempo de ejecución — se mostrarán en inglés hasta
   que se traduzcan.

No existe ninguna herramienta de extracción automática para las etiquetas
TOML. Deben mantenerse manualmente cotejándolas con los archivos de perfil
de dispositivo. Recuerda: cada dispositivo obtiene su propio archivo de
sobrescritura por idioma — nunca apuntes dos dispositivos al mismo archivo
de sobrescritura.

---

## 6. Referencia — Idiomas soportados

| Código | Idioma | Archivo `.po` | Sobrescritura de etiquetas |
|---|---|---|---|
| `en` | Inglés | `locale/en/LC_MESSAGES/cat_gui.po` | (no se necesita — los perfiles de dispositivo ya usan etiquetas en inglés) |
| `es` | Español | `locale/es/LC_MESSAGES/cat_gui.po` | `<nombre_base_dispositivo>_labels_es.toml` por dispositivo |
| `de` | Alemán | `locale/de/LC_MESSAGES/cat_gui.po` | `<nombre_base_dispositivo>_labels_de.toml` por dispositivo |
| `fr` | Francés | `locale/fr/LC_MESSAGES/cat_gui.po` | `<nombre_base_dispositivo>_labels_fr.toml` por dispositivo |
| `ja` | Japonés | `locale/ja/LC_MESSAGES/cat_gui.po` | `<nombre_base_dispositivo>_labels_ja.toml` por dispositivo |

Para añadir otro idioma, sigue el §4 y añade una fila a esta tabla. Ten en
cuenta que la capa gettext `.po`/`.mo` (un archivo por idioma, a nivel de
todo el proyecto) y la capa de etiquetas TOML (un archivo por dispositivo,
por idioma) siguen reglas de organización de archivos **diferentes** — no
asumas que las sobrescrituras TOML reflejan el patrón de un-archivo-por-
idioma de los archivos `.po`.

---

## 7. Hoja de referencia rápida

```
Añadir un nuevo idioma (p. ej. portugués = "pt")
───────────────────────────────────────────────

1. mkdir -p locale/pt/LC_MESSAGES
2. cp locale/cat_gui.pot locale/pt/LC_MESSAGES/cat_gui.po
3. Editar el encabezado en cat_gui.po  (Language: pt, Plural-Forms: ...)
4. Traducir todos los campos msgstr
5. msgfmt -o locale/pt/LC_MESSAGES/cat_gui.mo locale/pt/LC_MESSAGES/cat_gui.po
6. Para CADA perfil de dispositivo (device_xiegu_g90.toml, device_dummy.toml, ...):
     crear device_xiegu_g90_labels_pt.toml, device_dummy_labels_pt.toml, etc.
     (nombrado según el propio archivo de cada dispositivo — ¡no hay archivo único compartido!)
7. Editar cada *_labels_pt.toml  (≤7 caracteres para etiquetas de botón/modo/antena,
   ≤10 caracteres para etiquetas de memoria; sin límite en [rf_btn_config])
8. python cat_server.py --lang pt   ← probarlo (la GUI adopta "pt" al conectarse;
                                       cat_gui.py no tiene su propio indicador --lang)


Actualizar traducciones existentes tras cambios en el código fuente
────────────────────────────────────────────────────────────────────

1. scripts/update_translations.sh    (extraer + combinar + compilar)
2. Editar cada .po — completar msgstr "" y corregir entradas #, fuzzy
3. python i18n/compile.py            (recompilar a .mo)


Regla de longitud de etiquetas
───────────────────────────────

Sección               │ Límite
──────────────────────┼──────────────
[user_buttons]        │ 7 caracteres (se trunca, no se rechaza)
[user_mods]           │ 7 caracteres (se trunca, no se rechaza)
[rf_usr_btns]         │ 7 caracteres (se trunca, no se rechaza)
[antenna]             │ 7 caracteres (se trunca, no se rechaza)
[rf_btn_config]       │ sin límite (diálogo, no botón de hardware)
Etiquetas de memoria   │ 10 caracteres (sistema aparte — MEMORY_LABEL_MAXLEN,
                       │ no forma parte de los archivos TOML de sobrescritura de dispositivo)


Archivos de sobrescritura de etiquetas de dispositivo — uno por dispositivo, por idioma
──────────────────────────────────────────────────────────────────────────────────────
device_xiegu_g90.toml  +  --lang es  →  device_xiegu_g90_labels_es.toml
device_dummy.toml      +  --lang es  →  device_dummy_labels_es.toml
(NO un único cat_device_labels_es.toml compartido para todo el proyecto.)


Herramientas necesarias
────────────────────────

GNU gettext (xgettext, msgfmt, msgmerge)
  Ubuntu/Debian:  sudo apt install gettext
  macOS:          brew install gettext

Python 3.8+  (para soporte de pgettext)
```
