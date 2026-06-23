# CAT GUI — Interfaz de Control SDR para Radioaficionados

Sistema cliente-servidor en Python para controlar un transceptor de Radio Definida por Software (SDR). `cat_gui.py` es una interfaz de escritorio Tkinter completa; `cat_server.py` es un backend compatible con el protocolo que incluye un simulador de señales integrado, lo que permite que la GUI funcione de inmediato sin configuración adicional — y puede ser reemplazado (o extendido) con un driver real de hardware SDR.

---

## Tabla de Contenidos

- [Descripción General](#descripción-general)
- [Arquitectura del Sistema](#arquitectura-del-sistema)
- [Características Principales](#características-principales)
- [Requisitos e Instalación](#requisitos-e-instalación)
- [Instalación y Uso en Windows](#instalación-y-uso-en-windows)
- [Inicio Rápido](#inicio-rápido)
- [Archivos de Configuración](#archivos-de-configuración)
  - [cat\_gui.toml — Configuración de la GUI](#cat_guitoml--configuración-de-la-gui)
  - [cat\_server.toml — Transporte y Lista de Dispositivos](#cat_servertoml--transporte-y-lista-de-dispositivos)
  - [cat\_device.toml — Perfil de Dispositivo](#cat_devicetoml--perfil-de-dispositivo)
  - [Estado y Memorias por Dispositivo](#estado-y-memorias-por-dispositivo)
- [Referencia de Línea de Comandos](#referencia-de-línea-de-comandos)
  - [cat\_gui.py](#parámetros-cli-de-cat_guipy)
  - [cat\_server.py](#parámetros-cli-de-cat_serverpy)
- [Especificación del Protocolo TCP](#especificación-del-protocolo-tcp)
  - [Comandos GUI → Servidor](#comandos-gui--servidor)
  - [Mensajes Servidor → GUI](#mensajes-servidor--gui)
- [Diseño de la GUI y Controles](#diseño-de-la-gui-y-controles)
  - [Cascada RF y Espectro](#cascada-rf-y-espectro)
  - [Barra de Herramientas](#barra-de-herramientas)
  - [Panel de Control Izquierdo](#panel-de-control-izquierdo)
  - [Cascada AF, Espectro y Panel de Texto](#cascada-af-espectro-y-panel-de-texto)
- [Sistema de Audio](#sistema-de-audio)
- [Reproducción de WAV IQ y Audio (Servidor)](#reproducción-de-wav-iq-y-audio-servidor)
- [Memorias de Frecuencia](#memorias-de-frecuencia)
- [Perfiles de Dispositivo y Cambio de Dispositivo](#perfiles-de-dispositivo-y-cambio-de-dispositivo)
- [HiDPI / Escala](#hidpi--escala)
- [Temas y Fuentes](#temas-y-fuentes)
- [Referencia de Archivos Generados](#referencia-de-archivos-generados)
- [Extender el Servidor](#extender-el-servidor)

---

## Descripción General

CAT GUI implementa una interfaz completa de control de radio basada en el aspecto visual de los transceptores SDR de gama alta. La GUI se conecta al servidor mediante un socket TCP local (o remoto) y se comunica con un protocolo JSON simple delimitado por saltos de línea. Un canal UDP separado transporta el audio bidireccional en tiempo real (audio de recepción del servidor al altavoz de la GUI; audio del micrófono de la GUI al servidor cuando PTT está activo).

El servidor de referencia incluido es un **simulador**: genera señales portadoras RF sintéticas en un espectro de 192 kHz de ancho, produce un tono de recepción de 440 Hz, acepta todos los comandos de la GUI y reenvía todos los cambios de estado. Se pueden reproducir grabaciones IQ reales y audio de recepción real a través de él con dos parámetros (`--iq_wav` y `--audio_wav`). La arquitectura del servidor es intencionalmente mínima para que sea sencillo reemplazar el stub de generación de señales con un driver real de hardware SDR (SoapySDR, RTL-SDR, SDRplay, etc.).

---

## Arquitectura del Sistema

```
┌────────────────────────────────────────────────────┐
│                  cat_gui.py (cliente)               │
│                                                    │
│  ┌──────────┐  ┌──────────┐  ┌─────────────────┐  │
│  │ WFCanvas │  │SpecCanvas│  │   FreqDisp (×3)  │  │
│  │(cascada) │  │(espectro) │  │ LO A / LO B /   │  │
│  └──────────┘  └──────────┘  │ Sintonizador     │  │
│                               └─────────────────┘  │
│  ┌──────────────┐  ┌────────────────────────────┐  │
│  │ RTPAudioClient│  │     NetClient (TCP)        │  │
│  │  UDP/G.711μ  │  │  JSON delimitado por línea  │  │
│  └──────────────┘  └────────────────────────────┘  │
└──────────────┬──────────────────────┬──────────────┘
               │  TCP (control)       │  UDP (audio)
               ▼                      ▼
┌────────────────────────────────────────────────────┐
│                 cat_server.py (servidor)            │
│                                                    │
│  ┌────────────┐  ┌───────────────┐  ┌───────────┐  │
│  │RadioState  │  │ClientHandler  │  │UDPAudio   │  │
│  │  (estado   │  │  (hilo TCP    │  │Channel    │  │
│  │  SDR)      │  │  por cliente) │  │(TX+RX RTP)│  │
│  └────────────┘  └───────────────┘  └───────────┘  │
│  ┌────────────┐  ┌───────────────┐                  │
│  │IQWavSource │  │AudioWavSource │                  │
│  │(--iq_wav)  │  │(--audio_wav)  │                  │
│  └────────────┘  └───────────────┘                  │
└────────────────────────────────────────────────────┘
```

**Canal de control TCP** — objetos JSON UTF-8 delimitados por salto de línea. La GUI envía un objeto de comando por línea; el servidor siempre responde con `{"resp": "ok"}` (más un diccionario de estado completo en `hello` y `select_device`). Durante la ejecución, el servidor también envía tramas `{"type": "data", ...}` a ~10 Hz con datos actualizados de espectro, S-meter y silenciador.

**Canal de audio UDP** — datagramas RTP con una cabecera de 12 bytes y carga útil G.711 μ-law (PCMU) a 8 kHz / 8 bits / mono / tramas de 20 ms (160 bytes de μ-law por paquete). Bidireccional: servidor → GUI cuando PTT está desactivado (audio de recepción); GUI → servidor cuando PTT está activo (audio del micrófono para TX).

---

## Características Principales

### Pantalla
- **Cascada RF** — desplazamiento incremental O(ancho) por trama con `PhotoImage.put()`, velocidad ajustable (1–10), se congela con el indicador "● TX" durante la transmisión
- **Espectro RF** — lienzo con elementos retenidos (sin `delete("all")` por trama), superposición de pasabanda IF arrastrable, visualización de pico con decaimiento configurable, línea de cursor VFO
- **Cascada AF** — mismo motor que la cascada RF; impulsada desde el audio RTP decodificado localmente (no un valor calculado por el servidor), de modo que lo dibujado siempre coincide con lo que se escucha
- **Espectro AF** — FFT local del PCM recibido; usa `numpy.fft.rfft` cuando está disponible, con respaldo a una FFT Cooley-Tukey radix-2 puro Python con ventana Hamming
- Nivel de referencia (SCALE) ajustable en pasos de ±5 dB; promediado FFT (AVE) 1–10; selector Cascada / Espectro por recuadro
- Líneas de cuadrícula del eje de frecuencia y etiquetas con escala automática para cualquier span o nivel de zoom

### Control de Frecuencia
- **LO dual (VFO A / B)** más una pantalla **Sintonizador** — tres visualizaciones de frecuencia ámbar de 9 dígitos independientes con separadores de miles
- Incremento/decremento por dígito con rueda del ratón (o clic izquierdo/derecho); doble clic abre un diálogo de entrada directa en Hz
- **Modo SPLIT** — LO A como RX, LO B como TX; etiquetas TX/RX mostradas junto a cada pantalla LO cuando está activo
- **Botones de banda** — 160 m hasta 6 m (rangos Región 2 UIT); al presionar uno se sintoniza directamente a la frecuencia central de la banda
- **Restricciones de banda** por dispositivo y por antena — los botones de banda deshabilitados aparecen visualmente atenuados
- **Botones M (Memoria)** — junto a cada fila de frecuencia; abre un diálogo de 20 ranuras de memoria por dispositivo

### Controles de Procesamiento de Señal
- Volumen, Umbral AGC, Ganancia RF, Silenciador — controles deslizantes horizontales, reflejados instantáneamente en el servidor
- **Botones de modo** — LSB, USB, AM, FM, CW, y hasta 10 modos de modulación definidos por el usuario
- **AGC** — apagado / lento / medio / rápido, más un control deslizante de umbral AGC configurable
- **Filtro** — pasabanda arrastrado directamente en el lienzo del espectro IF; bordes inferior y superior ajustables independientemente
- **Zoom** — botones de acercar/alejar o rueda del ratón en el espectro IF; el zoom estrecha el span RF mostrado
- Botones de alternancia: NB (blanqueador de ruido), NR (reducción de ruido), NB RF, NB IF, AFC, ANF, Notch, Silenciar
- **S-meter** — medidor analógico de arco con barra de pico; lectura numérica de dBm y unidades S; LED de silenciador abierto/cerrado

### Gestión de Radio
- **Iniciar / Detener** — activa o desactiva el SDR (el servidor comienza o detiene el streaming de datos)
- **PTT** — botón circular, conmutación TX/RX instantánea; cascada/espectro congelados con indicador durante TX
- **Barra de transporte** — Grabar ●, Reproducir ▶, Pausar ⏸, Detener ■, Rebobinar ◀◀, Avance rápido ▶▶, Bucle ∞
- **Selector de dispositivo** — hasta 20 perfiles de dispositivo nombrados; al cambiar se guarda el estado actual y se restaura el estado persistido del dispositivo destino y sus memorias
- **Selector de antena** — hasta 10 puertos etiquetados por dispositivo, cada uno con su propia restricción de banda opcional
- **Selector de velocidad de muestreo** — lista de velocidades de muestreo SDR seleccionables por dispositivo
- **Selector de tarjeta de sonido** — enumeración de dispositivos PyAudio; selección independiente de micrófono y altavoz
- **Botones definidos por el usuario** — 14 botones programables (7 + 7 filas), cada uno independientemente `normal` (momentáneo) o `push` (alternancia/enclavamiento)
- **Botones RF de usuario** — 11 botones programables a la izquierda del array de bandas, de los mismos tipos normal/push
- **Panel de texto/RTTY** — los modos de modulación definidos por el usuario pueden dividir el recuadro AF para mostrar un panel de texto de solo lectura o un panel de chat bidireccional estilo RTTY en vivo

### Ventana y Escala
- Detecta automáticamente el DPI de la pantalla y selecciona el mejor nivel de escala; botones manuales `+` / `−` siempre disponibles
- El factor de escala es 1.25ˢᶜᵃˡᵃ (por ejemplo, nivel 2 = 1.5625×); rango de −5 a +5
- El panel de control inferior **siempre permanece completamente visible** en cualquier tamaño de ventana — la cascada/espectro RF se reducen primero
- El manejador de redimensionamiento `<Configure>` con antirrebote evita el desorden de diseño durante el arrastre en vivo
- Parámetro `--full-screen`; triple-Esc para alternar durante la ejecución
- Parámetros `--resolution WxH` y `--aspect-ratio W:H`; la relación de aspecto se aplica después de que el diseño se estabilice

---

## Requisitos e Instalación

### Versión de Python
Python **3.9** o posterior. Python 3.11+ incluye `tomllib` en la biblioteca estándar; las versiones anteriores necesitan `tomli`.

### Dependencia Principal
`tkinter` está incluido en la biblioteca estándar pero puede requerir un paquete del sistema operativo adicional en algunas distribuciones Linux:

```bash
# Debian / Ubuntu
sudo apt install python3-tk

# Fedora / RHEL
sudo dnf install python3-tkinter
```

### Dependencias Opcionales

| Paquete | Propósito | Instalación |
|---------|-----------|-------------|
| `numpy` | FFT acelerada para el espectro (ambos lados); requerida para `--iq_wav` en el servidor | `pip install numpy` |
| `tomli` | Soporte de configuración TOML en Python < 3.11 | `pip install tomli` |
| `pyaudio` | Audio de micrófono y altavoz (solo GUI) | `pip install pyaudio` |
| `fonttools` | Búsqueda autorizada del nombre de familia PostScript para fuentes personalizadas | `pip install fonttools` |

Sin `pyaudio` la GUI funciona normalmente pero la entrada/salida de audio se desactiva silenciosamente. Sin `numpy` el renderizado del espectro recurre a una FFT en Python puro (correcta pero más lenta). Sin `tomli`/`tomllib` se usa un analizador TOML mínimo integrado (cubre todas las claves que producen las plantillas de configuración incluidas).

### Instalación

```bash
# Clonar o descargar el repositorio, luego:
pip install numpy tomli pyaudio fonttools   # todas opcionales, instalar según sea necesario
```

No se requiere `setup.py` ni `pyproject.toml` — ambos scripts se ejecutan directamente.

---

## Instalación y Uso en Windows

Todo en este proyecto funciona en Windows sin dependencias específicas de UNIX. Los pasos a continuación cubren una máquina nueva desde cero.

### 1. Instalar Python

Descargar el instalador de **Python 3.11** (o posterior) desde [python.org/downloads](https://www.python.org/downloads/windows/).

Durante la instalación:

- Marcar **"Añadir python.exe al PATH"** en la primera pantalla — esta opción está desmarcada por defecto.
- Hacer clic en **"Personalizar instalación"** y confirmar que **"tcl/tk e IDLE"** está marcado. Esto instala `tkinter`, el kit de herramientas GUI usado por `cat_gui.py`. Si se omite, la GUI no podrá importar `tkinter` y no se iniciará.

Verificar después de la instalación abriendo el **Símbolo del sistema** (`Win + R` → `cmd`) y ejecutando:

```cmd
python --version
python -c "import tkinter; print('tkinter OK')"
```

Ambos comandos deben completarse sin error.

### 2. Instalar Dependencias Opcionales

Abrir el **Símbolo del sistema** o **PowerShell** y ejecutar:

```cmd
pip install numpy tomli pyaudio fonttools
```

#### PyAudio en Windows

`pip install pyaudio` frecuentemente falla en Windows porque intenta compilar una extensión C sin compilador presente. La solución más limpia es instalar una rueda precompilada:

```cmd
pip install pipwin
pipwin install pyaudio
```

Alternativamente, descargar el archivo `.whl` correspondiente a su versión de Python desde la página [Unofficial Windows Binaries for Python Extension Packages](https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio) (buscar `PyAudio‑0.2.x‑cpXXX‑cpXXX‑win_amd64.whl` donde `XXX` coincida con su versión de Python), e instalarlo directamente:

```cmd
pip install PyAudio-0.2.14-cp311-cp311-win_amd64.whl
```

Si PyAudio no puede instalarse, la GUI sigue funcionando completamente — la entrada/salida de audio se desactiva silenciosamente y se muestra un aviso en la consola.

### 3. Obtener los Scripts

Descargar `cat_gui.py` y `cat_server.py` (y `morgenta_regular.ttf` si desea la fuente de frecuencia incluida) en la misma carpeta, por ejemplo `C:\CAT`.

### 4. Abrir un Directorio de Trabajo

Todos los archivos de configuración, estado y memoria se crean en el **directorio de trabajo actual** cuando los scripts se ejecutan por primera vez. Es mejor hacer `cd` a la carpeta del proyecto antes de iniciar cualquier cosa:

```cmd
cd C:\CAT
```

### 5. Ejecutar el Servidor

```cmd
python cat_server.py
```

En la primera ejecución se crean `cat_server.toml` y `cat_device.toml` en `C:\CAT` con valores predeterminados anotados. La consola mostrará:

```
[config] Created default config: cat_server.toml
[config] Created default config: cat_device.toml
[cat_server] listening on 0.0.0.0:50101
```

**Aviso del Firewall de Windows** — Windows puede mostrar una alerta de seguridad la primera vez que el servidor abre un socket. Hacer clic en **"Permitir acceso"** (al menos para redes privadas) para que la GUI pueda acceder a él, incluso cuando ambos procesos están en la misma máquina.

### 6. Ejecutar la GUI

Abrir una **segunda** ventana del Símbolo del sistema, hacer `cd` a la misma carpeta, y ejecutar:

```cmd
python cat_gui.py
```

En la primera ejecución se crea `cat_gui.toml`. La ventana de la GUI se abre. Escribir `127.0.0.1` en el campo **Host** y `50101` en el campo **Puerto** (estos son los valores predeterminados ya mostrados), luego hacer clic en **Conectar** y después en **Iniciar**.

> **Consejo — autoconexión:** Para omitir la fila Host/Puerto/Conectar en ejecuciones posteriores, editar `cat_gui.toml` y configurar:
> ```toml
> [connection]
> host = "127.0.0.1"
> port = 50101
> autoconnect = true
> ```
> La GUI se conectará automáticamente al iniciar y la fila de conexión quedará oculta.

### 7. Ejecutar en Ventanas Separadas (Recomendado)

Como el servidor y la GUI son procesos separados, es conveniente ejecutar cada uno en su propia ventana. Un archivo por lotes sencillo para esto:

**`start_all.bat`** (guardar en `C:\CAT`):

```bat
@echo off
cd /d %~dp0
start "CAT Server" cmd /k python cat_server.py
timeout /t 1 >nul
start "CAT GUI"    cmd /k python cat_gui.py
```

Hacer doble clic en `start_all.bat` para iniciar ambos en ventanas separadas con títulos. Cerrar cualquiera de las ventanas detiene ese proceso correctamente.

### 8. Notas Específicas de Windows

#### Selección de Dispositivo de Audio

Windows frecuentemente tiene múltiples endpoints de audio (por ejemplo, altavoces, auriculares, cable virtual). Para listar todos los dispositivos y sus índices:

```cmd
python cat_gui.py --audio-list
```

Luego iniciar la GUI apuntando a dispositivos específicos:

```cmd
python cat_gui.py --audio-mic 1 --audio-speaker 2
```

O configurarlos de forma persistente en `cat_gui.toml`:

```toml
[audio]
mic = 1
speaker = 2
```

#### Fuentes Personalizadas

Las fuentes TTF/OTF personalizadas funcionan en Windows sin derechos de administrador. La GUI llama a `AddFontResourceExW` con los parámetros `FR_PRIVATE | FR_NOT_ENUM`, que registra la fuente solo en el proceso — sin instalación en todo el sistema y sin aviso UAC. Simplemente apuntar `--freq-font` a cualquier archivo `.ttf` o `.otf`:

```cmd
python cat_gui.py --freq-font "C:\Fonts\MiFuente.ttf"
```

O en `cat_gui.toml`:

```toml
[display]
freq_font = "C:\\Fonts\\MiFuente.ttf"
```

Notar las **barras invertidas dobles** en los strings TOML, o usar barras inclinadas (ambas funcionan en Windows):

```toml
freq_font = "C:/Fonts/MiFuente.ttf"
```

#### Pantallas HiDPI / 4K

En monitores de alta resolución Windows aplica escala de pantalla. Si la GUI aparece borrosa o sobredimensionada, es posible que Python esté recibiendo coordenadas pre-escaladas de Windows. La lógica de escala automática ya lo compensa leyendo la resolución real de pantalla y seleccionando el mejor nivel, pero se puede anular:

```cmd
python cat_gui.py --scale 2
```

O configurarlo en `cat_gui.toml`:

```toml
[display]
scale = 2
disable_scale = false
```

También se puede hacer clic derecho en `python.exe` → Propiedades → Compatibilidad → Cambiar configuración de DPI alto → **"Omitir comportamiento de escala de PPP alto: Aplicación"** para que Python maneje el DPI en lugar de Windows.

#### Modo Pantalla Completa

```cmd
python cat_gui.py --full-screen
```

Una vez en ejecución, presionar **Esc tres veces en un segundo** para activar o desactivar el modo de pantalla completa.

#### Firewall y Conexiones Remotas

Si el servidor y la GUI se ejecutan en **máquinas diferentes** (por ejemplo, servidor en una PC del shack, GUI en una laptop por LAN), se deben permitir conexiones entrantes en el puerto de control TCP y en el puerto de audio UDP mediante el Firewall de Windows Defender:

1. Abrir **Firewall de Windows Defender con seguridad avanzada** (`wf.msc`).
2. Agregar una **Regla de entrada** → Tipo de regla: Puerto → TCP → puerto `50101` → Permitir.
3. Agregar una segunda **Regla de entrada** → Tipo de regla: Puerto → UDP → puerto `5004` → Permitir.

Luego iniciar el servidor normalmente y apuntar la GUI a la IP LAN del servidor:

```cmd
python cat_gui.py --host 192.168.1.10 --port 50101
```

#### Problemas con PATH

Si `python` no se encuentra después de la instalación, usar la ruta completa (`C:\Users\SuNombre\AppData\Local\Programs\Python\Python311\python.exe`) o volver a ejecutar el instalador de Python y marcar **"Agregar Python a las variables de entorno"** en el paso de personalización.

Si `pip` no se encuentra, ejecutar:

```cmd
python -m pip install numpy tomli pyaudio fonttools
```

#### Codificación de la Consola

Si la consola muestra caracteres ilegibles (poco frecuente en Windows 10/11 modernos), configurar la página de códigos a UTF-8 antes de ejecutar:

```cmd
chcp 65001
python cat_server.py
```

---

## Inicio Rápido

**1. Iniciar el servidor** (puerto 50101 por defecto, señales RF simuladas):

```bash
python cat_server.py
```

**2. Iniciar la GUI** (se conecta a 127.0.0.1:50101 por defecto):

```bash
python cat_gui.py
```

**3.** En la GUI, hacer clic en **Conectar**, luego en **Iniciar**.

La cascada RF y el espectro comenzarán a desplazarse, el S-meter se animará, y un tono de recepción de 440 Hz se reproducirá a través del altavoz del sistema (si PyAudio está instalado).

---

## Archivos de Configuración

Ambos lados generan archivos de configuración TOML en la primera ejecución con valores predeterminados anotados, y **se autocorrigen** en cada ejecución posterior: si falta una clave (por ejemplo, después de que una actualización agrega una nueva opción), se añade con su valor predeterminado y el archivo se reescribe en su lugar.

### cat\_gui.toml — Configuración de la GUI

Creado en el directorio de trabajo como `cat_gui.toml` (anular con `--config RUTA`).

```toml
# Configuración de CAT GUI
# Los parámetros CLI anulan estos valores en tiempo de ejecución sin modificar este archivo.

[display]
bg = "dark"           # "light" o "dark"
full_screen = false   # iniciar en modo pantalla completa
scale = 0             # nivel de escala HiDPI, -5 a 5
disable_scale = false # ocultar los controles de escala +/-
freq_font = ""        # ruta a la fuente TTF/OTF para las pantallas de dígitos de frecuencia
gui_font = ""         # ruta a la fuente TTF/OTF para el resto del texto de la GUI

[connection]
# Tanto host como port deben configurarse, y autoconnect = true, para conectar al inicio.
# Con autoconnect = true la fila de host/port/conectar se oculta completamente de la GUI.
host = ""
port = 0
autoconnect = false

[audio]
# Índices de dispositivo de --audio-list; -1 = predeterminado del sistema.
# Tanto mic como speaker deben configurarse juntos (o ambos dejarse en -1).
mic = -1
speaker = -1
disable_soundcard_select = false
```

### cat\_server.toml — Transporte y Lista de Dispositivos

Creado como `cat_server.toml` (anular con `--config RUTA`). Contiene la configuración de transporte del servidor y la lista de hasta 20 perfiles de dispositivo nombrados.

```toml
[server]
host = "0.0.0.0"
port = 50101

[audio]
audio_port = 5004
no_audio = false

[devices]
# Hasta 20 perfiles de dispositivo. Etiqueta vacía = ranura sin usar.
label_1 = "SDR Principal"
config_1 = "devcfg_main.toml"
label_2 = ""
config_2 = ""
# ... label_3 / config_3 ... label_20 / config_20
```

### cat\_device.toml — Perfil de Dispositivo

Creado como `cat_device.toml` (anular con `--device-config RUTA`). Define el diseño de la GUI para un dispositivo: sus botones programables, modos de modulación, velocidades de muestreo SDR y puertos de antena.

```toml
[user_buttons]
# Hasta 14 botones definidos por el usuario. Las ranuras deben llenarse en orden (sin saltos).
label_1 = "CW Spot"
type_1 = "push"     # "normal" (momentáneo) o "push" (alternancia/enclavamiento)
list_1 = ""         # elementos desplegables separados por coma (opcional)
label_2 = ""
# ... label_3 / type_3 / list_3 ... label_14 / type_14 / list_14

[user_mods]
# Hasta 10 botones de modulación definidos por el usuario. Las ranuras deben llenarse en orden.
label_1 = "RTTY"
type_1 = "text_input"  # "normal", "text", o "text_input"
# ... label_2 / type_2 ... label_10 / type_10

[rf_usr_btns]
# Hasta 11 botones mostrados a la izquierda del array de bandas en el panel RF.
label_1 = "ATU"
mode_1 = "push"     # "normal" o "push"
# ... label_2 / mode_2 ... label_11 / mode_11

[sdr]
sample_rate = 192000
# Lista separada por comas de velocidades seleccionables para este dispositivo.
sample_rates = "192000,250000,500000,1000000,2000000"
# Lista separada por comas de bandas a las que este dispositivo puede sintonizar (vacío = todas).
allowed_bands = "160m,80m,60m,40m,30m,20m,17m,15m,12m,10m,6m"

[antenna]
# Hasta 10 puertos de antena. Etiqueta vacía = ranura sin usar/oculta.
label_1 = "Dipolo"
allowed_bands_1 = ""          # vacío = heredar allowed_bands del nivel de dispositivo
label_2 = "Vertical HF"
allowed_bands_2 = "40m,20m,15m,10m"
# ... label_3 / allowed_bands_3 ... label_10 / allowed_bands_10
```

Cada entrada en la sección `[devices]` de `cat_server.toml` apunta a un archivo compatible con `cat_device.toml` **separado** para ese perfil. Cambiar de dispositivo en la GUI carga los botones, velocidades de muestreo, memorias y el último estado guardado de ese perfil.

### Estado y Memorias por Dispositivo

Se generan automáticamente junto al archivo de configuración de cada dispositivo:

| Archivo | Contenido |
|---------|-----------|
| `<dispositivo>.gui_state.json` | Configuración persistida del operador: frecuencias (LO A/B/Sintonizador), modo, filtro, AGC, ganancias, silenciador, alternadores, zoom, velocidad de muestreo, estados de botones, selección de antena, configuración de pantalla del espectro |
| `<dispositivo>.memories.json` | 3 × 20 memorias de frecuencia (LO A, LO B, Sintonizador) con etiquetas y frecuencias |

El estado se guarda cuando el operador cambia de un dispositivo y se restaura cuando regresa. Las ranuras de memoria se escriben inmediatamente cada vez que se guarda una ranura desde la GUI.

---

## Referencia de Línea de Comandos

### Parámetros CLI de cat\_gui.py

```
python cat_gui.py [OPCIONES]

Conexión:
  --host HOST            Nombre de host o IP del servidor (debe ir con --port)
  --port PORT            Puerto TCP del servidor (debe ir con --host)
  --autoconnect          Conectar automáticamente al iniciar; oculta la fila
                         host/port/conectar en la GUI

Pantalla:
  --bg {light,dark}      Tema de fondo ("dark" es el predeterminado)
  --full-screen          Iniciar en modo pantalla completa (triple-Esc para alternar)
  --resolution WxH       Tamaño inicial de ventana en píxeles, por ejemplo 1280x720
  --aspect-ratio W:H     Bloquear ventana a una relación de aspecto, por ejemplo 16:9 o 4:3
                         (ignorado cuando --full-screen está activo)
  --scale INT            Nivel de escala HiDPI inicial, -5 a 5 (0 = detección automática)
  --disable-scale        Ocultar los botones de escala +/- (usar con --scale)
  --freq-font RUTA       Archivo de fuente TTF/OTF para las pantallas de frecuencia LO/Sintonizador
  --gui-font RUTA        Archivo de fuente TTF/OTF para el resto del texto de la GUI

Audio:
  --audio-list           Imprimir todos los índices de dispositivos de audio y salir
  --audio-mic ÍNDICE     Seleccionar el dispositivo de micrófono por índice (usar con --audio-speaker)
  --audio-speaker ÍNDICE Seleccionar el dispositivo de altavoz por índice (usar con --audio-mic)
  --disable-soundcard-select
                         Ocultar el botón Tarjeta de sonido en la GUI

Misceláneos:
  --config RUTA          Cargar la configuración TOML de la GUI desde RUTA en lugar de ./cat_gui.toml
  --debug                Habilitar salida de depuración detallada en la consola
```

### Parámetros CLI de cat\_server.py

```
python cat_server.py [OPCIONES]

Transporte:
  --host HOST            Dirección de escucha TCP (predeterminado: 0.0.0.0)
  --port PORT            Puerto de escucha TCP (predeterminado: 50101)
  --audio-port PORT      Puerto RTP UDP de audio (predeterminado: 5004)
  --no-audio             Deshabilitar el canal de audio UDP por completo

Archivos de configuración:
  --config RUTA          Cargar cat_server.toml desde RUTA en lugar de ./cat_server.toml
  --device-config RUTA   Cargar cat_device.toml desde RUTA en lugar de ./cat_device.toml

IQ y Audio:
  --iq_wav RUTA          Archivo WAV de muestras IQ para usar en el espectro/cascada RF
                         (PCM/float estéreo, I=izquierda, Q=derecha; fragmento auxi opcional para
                         la frecuencia central). En bucle indefinido. Requiere numpy.
  --audio_wav RUTA       Archivo WAV para transmitir como audio de recepción simulado (en bucle).
                         Remuestreado a 8 kHz mono. Reemplaza el tono de 440 Hz incorporado.

Botones definidos por el usuario (también configurables en cat_device.toml):
  --user-button-label-N TEXTO   Etiqueta para el botón de usuario N (1–14, máx. 7 caracteres)
  --user-button-type-N TIPO     "normal" o "push" para el botón de usuario N

Modos de modulación definidos por el usuario:
  --user_mod_N ETIQUETA  Etiqueta para el botón de modo de usuario N (1–10, máx. 4 caracteres)
  --user_mod_type_N TIPO "normal", "text", o "text_input" para la ranura N

Botones RF de usuario:
  --rf_usr_btn_N ETIQUETA  Etiqueta para el botón RF de usuario N (1–11, máx. 7 caracteres)
  --rf_usr_btn_mode_N M    "normal" o "push" para el botón RF de usuario N
```

> **Prioridad:** Los parámetros CLI siempre tienen prioridad sobre el archivo de configuración TOML, que tiene prioridad sobre los valores predeterminados integrados. Los parámetros de ranuras de botones/mod deben especificarse secuencialmente (1, 2, 3 …) sin saltos; el servidor mostrará un error si se salta una ranura.

---

## Especificación del Protocolo TCP

Todos los mensajes son objetos JSON UTF-8 terminados en salto de línea (`\n`). Un objeto por línea en ambas direcciones. El servidor acepta múltiples clientes TCP simultáneos (cada uno en su propio hilo).

### Comandos GUI → Servidor

Cada comando recibe una respuesta inmediata `{"resp": "ok"}`. Los comandos marcados con ★ también reciben un diccionario de estado completo: `{"resp": "ok", "state": {...}}`.

#### Inicio

| Comando | Campos | Notas |
|---------|--------|-------|
| `hello` ★ | — | Enviado al conectar; activa un push `reload_state` y devuelve el estado completo |

#### Frecuencia

| Comando | Campos | Notas |
|---------|--------|-------|
| `set_freq` | `hz: int` | Establecer la frecuencia de LO A (recepción principal) |
| `set_lo_a_freq` | `hz: int` | Alias de `set_freq` |
| `set_lo_b_freq` | `hz: int` | Establecer la frecuencia de LO B (TX en SPLIT) |
| `set_tune_freq` | `hz: int` | Establecer la frecuencia del Sintonizador (desplazamiento BFO/IF) |
| `set_lo` | `lo: "A"\|"B"` | Seleccionar el LO activo |

#### Modo y DSP

| Comando | Campos | Notas |
|---------|--------|-------|
| `set_mode` | `mode: str` | Por ejemplo `"USB"`, `"LSB"`, `"AM"`, `"FM"`, `"CW"` |
| `set_agc` | `mode: str` | `"off"`, `"slow"`, `"medium"`, `"fast"` |
| `set_agc_thresh` | `value: float` | Umbral AGC en dBm (−140 a −20) |
| `set_filter` | `lo: int, hi: int` | Bordes del pasabanda IF en Hz (por ejemplo `lo=100, hi=2800`) |
| `set_zoom` | `value: int` | Factor de zoom (≥ 1) |
| `set_rf_gain` | `value: float` | Ganancia RF en dB (0–60) |
| `set_volume` | `value: float` | Volumen de audio (0–100) |
| `set_squelch` | `value: float` | Nivel de silenciador en dBm (−140 a 0) |
| `set_nb` | `enabled: bool` | Blanqueador de ruido (audio/IF) |
| `set_nbrf` | `enabled: bool` | Blanqueador de ruido (RF) |
| `set_nbif` | `enabled: bool` | Blanqueador de ruido (IF) |
| `set_nr` | `enabled: bool` | Reducción de ruido |
| `set_afc` | `enabled: bool` | Control automático de frecuencia |
| `set_anf` | `enabled: bool` | Filtro de muesca automático |
| `set_notch` | `enabled: bool` | Filtro de muesca manual |
| `set_mute` | `enabled: bool` | Silenciar audio |

#### Pantalla del Espectro

| Comando | Campos | Notas |
|---------|--------|-------|
| `set_spec_ref` | `box: "rf"\|"af", value: float` | Nivel de referencia (parte superior de la pantalla), ajustado al múltiplo de 5 dB más cercano, rango −50 a +10 |
| `set_spec_ave` | `box: "rf"\|"af", value: int` | Conteo de promediado FFT, 1–10 |

#### PTT, SPLIT, Transporte

| Comando | Campos | Notas |
|---------|--------|-------|
| `set_ptt` | `enabled: bool, udp_port: int` | Activar/desactivar PTT; `udp_port` indica al servidor dónde enviar el audio TX |
| `set_split` | `enabled: bool` | Habilitar/deshabilitar SPLIT (LO A RX, LO B TX) |
| `start` | — | Iniciar el streaming SDR |
| `stop` | — | Detener el streaming SDR |
| `transport` | `action: str` | `"rec"`, `"play"`, `"pause"`, `"stop"`, `"rw"`, `"ff"`, `"infinite"` |

#### Dispositivo y Hardware

| Comando | Campos | Notas |
|---------|--------|-------|
| `get_devices` | — | Devuelve `{"type": "device_list", "devices": [...]}` |
| `select_device` ★ | `index: int` | Índice de dispositivo base 1; guarda el estado actual, carga el nuevo dispositivo |
| `get_sample_rates` | — | Devuelve `{"type": "sample_rate_list", "rates": [...], "current": N}` |
| `set_sample_rate` | `value: int` | Establecer la velocidad de muestreo (debe estar en la lista configurada del dispositivo) |
| `get_antennas` | — | Devuelve `{"type": "antenna_list", "antennas": [...], "current": N, "device_allowed_bands": [...]}` |
| `select_antenna` | `index: int` | Índice de puerto de antena base 1 (0 = deseleccionar) |

#### Botones de Usuario y Texto

| Comando | Campos | Notas |
|---------|--------|-------|
| `user_button` | `index: int` | Pulsación momentánea del botón de usuario N |
| `user_button` | `index: int, enabled: bool` | Estado push-push (alternancia) del botón de usuario N |
| `user_text` | `index: int, text: str` | Texto enviado por el operador en un panel de modo `text_input` |
| `ui_button` | `name: str` | Pulsación de botón UI nombrado (por ejemplo `"Full Screen"`, `"Bandwidth"`) |
| `ui_display` | `box: str, view: str` | Alternancia de vista Cascada / Espectro |

#### Memorias de Frecuencia

| Comando | Campos | Notas |
|---------|--------|-------|
| `get_memories` | `position: "LO A"\|"LO B"\|"Tune"` | Devuelve la lista de 20 ranuras para esa fila |
| `save_memory` | `position: str, index: int, label: str, freq: float` | Guarda una ranura y la persiste inmediatamente en disco |

#### Registro de Audio

| Comando | Campos | Notas |
|---------|--------|-------|
| `audio_hello` | `udp_port: int` | Registra el endpoint UDP de la GUI con el canal de audio del servidor |

---

### Mensajes Servidor → GUI

#### Trama de Datos en Streaming (~10 Hz durante la ejecución)

```json
{
  "type": "data",
  "f_start": 28390000,
  "f_stop": 28590000,
  "spectrum": [-120.5, -118.3, ...],       // NUM_BINS valores en dBm
  "af_range": 3000,
  "af_spectrum": [-95.1, -93.0, ...],      // AF_BINS valores en dBm (0..3000 Hz)
  "smeter_dbm": -73.0,
  "smeter_text": "S9",
  "squelch_open": true,
  "state": { ... }                         // campos de estado incrementales
}
```

La GUI usa `f_start`/`f_stop` para posicionar el eje de frecuencia del espectro/cascada RF; `af_range` (siempre 3000 Hz) para el eje de la pantalla AF.

#### Pushes No Solicitados

| Tipo | Campos | Significado |
|------|--------|-------------|
| `audio_port` | `port, sample_rate, frame_ms, codec` | Emitido al conectar el cliente; indica a la GUI qué puerto UDP abrir para el audio |
| `reload_state` | — | La GUI debe resincronizar todos los widgets desde el estado `resp:ok` precedente |
| `device_list` | `devices: [{index, label}]` | Respuesta a `get_devices` |
| `sample_rate_list` | `rates: [int], current: int` | Respuesta a `get_sample_rates` |
| `antenna_list` | `antennas: [...], current: int, device_allowed_bands: [...]` | Respuesta a `get_antennas` |
| `memory_list` | `position: str, memories: [{label, freq}×20]` | Respuesta a `get_memories` o `save_memory` |
| `user_text` | `index: int, text: str` | Texto enviado por el servidor a una ranura de panel `text`/`text_input` |
| `disconnected` | (razón opcional) | Emitido internamente por la GUI cuando cae la conexión TCP |

#### Diccionario de Estado

El diccionario de estado completo (enviado en `resp:ok` para `hello` / `select_device`, e incrementalmente en las tramas `data`) contiene:

```
center_freq, tune_freq, lo_b_freq, lo_active
mode, agc, agc_thresh
filter_lo, filter_hi
rf_gain, volume, squelch
nb, nr, nbrf, nbif, afc, anf, notch, mute
ptt, split, running
zoom, sample_rate
user_buttons, user_btn_state, user_btn_list_sel
rf_usr_btns, rf_usr_btn_state
user_mod_labels, user_mod_types
spec_ref_rf, spec_ave_rf, spec_ref_af, spec_ave_af
allowed_bands, antenna_labels, antenna_index, antenna_allowed_bands
```

---

## Diseño de la GUI y Controles

### Cascada RF y Espectro

El panel RF ocupa la parte superior de la ventana y está dividido en dos subpaneles apilados verticalmente:

**Cascada RF** (`WFCanvas`) — el panel más grande y expandible en la parte superior. Las nuevas filas de espectro se insertan en la parte superior para que los datos más recientes estén siempre arriba y el historial se desplace hacia abajo. La velocidad de desplazamiento se controla con el selector de Velocidad en la barra de herramientas. Durante PTT la cascada se congela y se muestra el indicador "● TX".

**Espectro RF** (`SpecCanvas`) — franja de altura fija debajo de la cascada. Dibujado con una técnica de objetos retenidos (todos los elementos del lienzo se crean una vez al inicio; cada trama solo actualiza coordenadas). Muestra: traza del espectro con relleno verde, una superposición semitransparente del pasabanda IF (rectángulo azul con bordes arrastrables), una línea de cursor VFO (roja) y una línea de pico (blanco-azul). Los bordes del filtro IF se pueden arrastrar directamente con el ratón. La rueda del ratón sobre el espectro hace zoom de acercar/alejar.

### Barra de Herramientas

Una franja estrecha entre el panel RF y la fila inferior contiene controles por recuadro tanto para el panel RF (arriba) como para el panel AF (abajo):

- **Cascada / Espectro** — botones de alternancia mutuamente exclusivos para cambiar el modo de visualización de este recuadro
- **SCALE** — nivel de referencia (parte superior de la pantalla) en dB; los botones +/− avanzan de 5 en 5 dB (rango −50 a +10)
- **AVE** — conteo de promediado FFT; los botones +/− avanzan de 1 en 1 (rango 1–10)
- **Speed** — velocidad de desplazamiento de la cascada; los botones +/− avanzan de 1 en 1 (rango 1–10)
- Etiquetas **RBW** / **Span** (informativas)

### Panel de Control Izquierdo

El panel izquierdo tiene ancho fijo y aloja todos los controles del transceptor, de arriba a abajo:

**Fila del S-meter** — lienzo del S-meter analógico de arco con aguja animada, indicador de pico, LED de silenciador abierto/cerrado, y un botón circular PTT fijado a la derecha.

**Pantallas de frecuencia** — tres widgets `FreqDisp` (LO A, LO B, Sintonizador). Cada uno muestra 9 dígitos ámbar con separadores de miles. Una fila de botones selectores LO A/B se ubica entre las pantallas; el estado SPLIT muestra etiquetas TX/RX junto a los LOs activos. Un botón **M** junto a cada fila abre el diálogo de memoria de frecuencia para esa fila.

**Botones de banda** — 11 bandas ITU Región 2 (160 m – 6 m). Al hacer clic se sintoniza el LO al centro de la banda. Los botones fuera de las `allowed_bands` del dispositivo (o la restricción de la antena seleccionada) se atenúan automáticamente.

**Volumen / Umbral AGC / Ganancia RF / Silenciador** — cuatro controles deslizantes horizontales con etiquetas.

**Dispositivo / Ancho de banda / Velocidad de muestreo / Tarjeta de sonido** — botones que abren diálogos o envían comandos `ui_button`.

**Botones de modo** — modos de modulación estándar (LSB, USB, AM, FM, CW, …) más hasta 10 modos de modulación de usuario definidos por el servidor.

**Alternadores DSP** — NB, NR, AGC, Filtro, AFC, ANF, Notch, Silenciar — cada uno es un botón de dos estados con resaltado verde cuando está activo.

**Barra de transporte** — Grabar ●, Reproducir ▶, Pausar ⏸, Detener ■, Rebobinar ◀◀, Avance rápido ▶▶, Bucle ∞.

**Botón Iniciar** — activa/desactiva el SDR. El texto cambia a "Detener" mientras está en ejecución.

**Filas de botones definidos por el usuario** — 14 botones en dos filas de 7. Las etiquetas y tipos provienen del servidor; los botones sin etiqueta están ocultos.

**Botones RF de usuario** — 11 botones mostrados encima de los botones de banda en el panel RF, a la izquierda del array de bandas.

**Fecha/hora + controles de conexión** — reloj UTC (verde); campos de host/puerto y un botón Conectar con LED de estado. En modo de autoconexión toda la fila está oculta.

### Cascada AF, Espectro y Panel de Texto

La mitad derecha de la fila inferior es el panel de Frecuencia de Audio, impulsado enteramente desde el audio RTP decodificado localmente (no calculado por el servidor):

- **Cascada AF** — mismo motor `WFCanvas`; muestra el contenido de frecuencia de audio de 0–3000 Hz desplazándose en tiempo real
- **Espectro AF** — mismo motor `SpecCanvas`; rango de 0–3000 Hz, sin superposición de filtro (AF no tiene pasabanda arrastrable)
- **Barra de herramientas AF** — mismos controles que la barra RF (Escala, Ave, Velocidad, alternancia Cascada/Espectro)
- **Panel de texto/RTTY** — cuando se selecciona un modo de modulación de usuario `text` o `text_input`, el recuadro AF se divide horizontalmente. El lado derecho muestra una pantalla de texto de solo lectura (mensajes enviados por el servidor) y, para los modos `text_input`, un cuadro de entrada editable de 3 líneas que envía su contenido como `user_text` cuando el operador presiona Enter. Cada ranura de modo de usuario tiene su propio historial de texto independiente.

---

## Sistema de Audio

El `RTPAudioClient` de la GUI gestiona el canal de audio UDP:

- **Recepción (PTT DESACTIVADO):** El servidor envía un paquete RTP/PCMU cada 20 ms. La GUI decodifica μ-law a PCM de 16 bits y escribe en un flujo de salida PyAudio (altavoz) mediante un búfer de anillo deque y una devolución de llamada PyAudio.
- **Transmisión (PTT ACTIVADO):** La GUI abre un flujo de entrada PyAudio (micrófono), lee tramas PCM de 160 muestras, las codifica a μ-law, las empaqueta en RTP y envía datagramas UDP al servidor.
- **Alimentación del espectro AF:** Las muestras PCM decodificadas se acumulan en un búfer de anillo rodante; un hilo de trabajo en segundo plano realiza una FFT cada ~50 ms y publica el resultado en la cola de eventos Tk de la GUI para su visualización en la cascada/espectro AF.
- El códec μ-law usa tablas de búsqueda precomputadas de 256 entradas para decodificación y 65536 entradas para codificación (construidas una vez al importar) para una ruta de audio sin ramificaciones ni estructuras en cada trama de audio.
- Selección de tarjeta de sonido (micrófono y altavoz de forma independiente) mediante el diálogo Tarjeta de sonido o los parámetros `--audio-mic` / `--audio-speaker`; `--audio-list` imprime todos los índices de dispositivos disponibles.

---

## Reproducción de WAV IQ y Audio (Servidor)

### `--iq_wav RUTA`

Impulsa el espectro RF y la cascada desde una grabación IQ real en lugar del generador de señales sintéticas. Acepta archivos WAV estéreo al estilo SDRplay donde el canal izquierdo es I y el derecho es Q, en cualquier profundidad PCM entera o flotante (8/16/32 bits). Si el archivo contiene un fragmento `auxi`, la frecuencia central grabada se extrae y se usa para inicializar la frecuencia sintonizada inicial.

El archivo se reproduce en bucle indefinido (reproducción en cinta de bucle). Una FFT IQ (`IQ_FFT_SIZE = 4096` bins, ventana Hanning, fftshift) convierte cada bloque a un espectro de potencia aproximado en dBm; el nivel de zoom luego recorta y remuestrea el resultado de ancho de banda completo al ancho de pantalla de la GUI.

Requiere `numpy`.

### `--audio_wav RUTA`

Reemplaza el tono de demostración de 440 Hz incorporado con un archivo WAV real (PCM/float mono o estéreo a cualquier velocidad de muestreo). El estéreo se mezcla a mono; el audio se remuestrea a 8 kHz si su velocidad nativa difiere. El archivo se reproduce en bucle indefinido como la transmisión de audio de recepción simulada entregada a la GUI.

---

## Memorias de Frecuencia

Cada perfil de dispositivo tiene su propio conjunto independiente de memorias: 20 ranuras para cada una de las tres posiciones de frecuencia (LO A, LO B, Sintonizador) = 60 ranuras por dispositivo.

Al abrir el diálogo de memoria (haciendo clic en un botón **M** junto a una pantalla de frecuencia) se envía `get_memories` al servidor. El servidor devuelve las 20 ranuras para esa posición desde el archivo de memoria del dispositivo activo. El operador puede:

- **Recuperar** una ranura de memoria — envía `set_freq` (o equivalente) y cierra el diálogo
- **Guardar** la frecuencia actual en una ranura — abre un diálogo de entrada de etiqueta, luego envía `save_memory`
- **Editar** la etiqueta de una ranura en el lugar

Las memorias se escriben en disco inmediatamente cada vez que se guarda una ranura; sobreviven a los reinicios del servidor y a los cambios de dispositivo.

---

## Perfiles de Dispositivo y Cambio de Dispositivo

Se pueden definir hasta 20 perfiles de dispositivo en la sección `[devices]` de `cat_server.toml`. Cada entrada empareja una etiqueta de visualización con una ruta a un archivo de configuración compatible con `cat_device.toml`.

Cuando el operador hace clic en el botón **Dispositivo**, la GUI envía `get_devices`; el servidor responde con un diálogo de lista. Al seleccionar un dispositivo se envía `select_device`:

1. El servidor guarda el estado GUI del dispositivo actual (frecuencias, modo, filtro, ganancias, alternadores, etc.) en su archivo `.gui_state.json`.
2. Se carga el archivo tipo `cat_device.toml` del nuevo dispositivo; los botones de usuario, botones de modulación, botones RF, velocidades de muestreo, restricciones de banda y puertos de antena se reemplazan.
3. Se restaura el `.gui_state.json` del nuevo dispositivo (frecuencias, modo, alternadores, etc.).
4. Se carga el `.memories.json` del nuevo dispositivo.
5. Se envía un mensaje `reload_state`; la GUI resincroniza todos los widgets.

Al iniciar, si hay una lista `[devices]` configurada y `--device-config` no se pasó explícitamente, el servidor selecciona automáticamente el dispositivo 1 para que su archivo de estado persistido se use desde la primera conexión (evitando un desajuste de identidad "fantasma" en la primera conexión).

---

## HiDPI / Escala

Todas las constantes de geometría se definen en un diccionario `BASE` en escala 1.0. El factor de escala efectivo es `1.25 ^ nivel_escala`. El nivel 0 apunta a una pantalla de 1280×720; la lógica de detección automática selecciona el nivel más alto cuyo tamaño de ventana predeterminado (1520×870 en el nivel 0) cabe en el 90% de la pantalla:

| Nivel de Escala | Factor | Resolución Objetivo |
|:-----------:|:------:|:----------------:|
| −1 | 0.80× | < 1280×720 |
| 0 | 1.00× | 1280×720 |
| 1 | 1.25× | 1920×1080 |
| 2 | 1.56× | 2560×1440 |
| 3 | 1.95× | — |
| 4 | 2.44× | 3840×2160 |
| 5 | 3.05× | — |

Los botones de escala `+` / `−` en la esquina superior derecha de la ventana incrementan/decrementan el nivel en tiempo de ejecución; todos los tamaños de fuente, widgets, relleno y geometría del lienzo se recalculan inmediatamente. La superposición de escala muestra el nivel actual y se desvanece después de unos segundos.

El motor de diseño garantiza que el panel de control inferior (desde la fila del S-meter hasta la fila de fecha/hora) sea **siempre completamente visible** a cualquier altura de ventana: solo la cascada/espectro RF superior se reduce para acomodar el panel inferior.

---

## Temas y Fuentes

### Paleta de Colores

El tema oscuro predeterminado usa un esquema de colores azul marino profundo/verde azulado:

| Rol | Hex | Descripción |
|------|-----|-------------|
| Fondo de ventana / cascada | `#020814` | Azul oscuro profundo |
| Panel de control | `#0c1525` | Azul marino oscuro |
| Fondo del espectro | `#010610` | Azul marino casi negro |
| Traza del espectro | `#22cc44` | Verde |
| Cursor VFO | `#ff2828` | Rojo |
| Dígitos de frecuencia | `#ffb800` | Ámbar |
| Botón activo | `#1a3c6a` / `#50c0ff` | Azul |
| Barra del S-meter | `#28ee50` → `#ff3830` | Verde → rojo |
| Pico retenido | `#e0e8ff` | Blanco-azul |

El parámetro `--bg light` o `bg = "light"` en `cat_gui.toml` reemplaza todas las superficies de fondo con `#FFECD6` (crema cálido), convirtiendo el ámbar de los dígitos de frecuencia a naranja oscuro para mayor legibilidad.

### Fuentes Personalizadas

Se pueden configurar dos rutas de fuente independientes:

- `--freq-font RUTA` — usada exclusivamente para las pantallas de dígitos de frecuencia LO A, LO B y Sintonizador
- `--gui-font RUTA` — propagada a todas las fuentes del sistema nombradas de Tk (`TkDefaultFont`, `TkTextFont`, etc.) para que todos los widgets las tomen automáticamente

La carga de fuentes (TTF/OTF) funciona sin derechos de administrador en Linux, macOS y Windows:

- **Linux:** copia la fuente a `~/.local/share/fonts/`, ejecuta `fc-cache`, luego llama a `FcConfigAppFontAddFile()` en el manejador de fontconfig del proceso activo para que Tk vea la familia inmediatamente
- **macOS:** copia a `~/Library/Fonts/`, luego llama a `CTFontManagerRegisterFontsForURL` con alcance al proceso actual
- **Windows:** llama a `AddFontResourceExW` con `FR_PRIVATE | FR_NOT_ENUM` (no se requieren derechos de administrador)

El nombre de familia PostScript se resuelve mediante fonttools (preferido), luego `fc-query`, y finalmente una heurística basada en el nombre del archivo.

---

## Referencia de Archivos Generados

| Archivo | Creado Por | Contenido |
|---------|-----------|---------|
| `cat_gui.toml` | GUI en la primera ejecución | Configuración de pantalla, conexión y audio de la GUI |
| `cat_server.toml` | Servidor en la primera ejecución | Transporte TCP/UDP, lista de dispositivos |
| `cat_device.toml` | Servidor en la primera ejecución | Perfil de dispositivo predeterminado (botones, modos, SDR, antenas) |
| `<dispositivo>.gui_state.json` | Servidor al cambiar de dispositivo | Configuración persistida del operador por dispositivo |
| `<dispositivo>.memories.json` | Servidor al guardar memoria | Memorias de frecuencia 3×20 por dispositivo |
| `cat_default.gui_state.json` | Respaldo del servidor | Archivo de estado para el perfil predeterminado (sin configuración de dispositivo explícita) |
| `cat_default.memories.json` | Respaldo del servidor | Archivo de memoria para el perfil predeterminado |

Todos los archivos `.toml` son auto-reparables: las claves faltantes se añaden con su valor predeterminado y el archivo se reescribe en su lugar.

---

## Extender el Servidor

El servidor de referencia está estructurado para que la capa de generación de señales sea fácil de reemplazar:

- **`RadioState.apply(cmd)`** — procesa cada comando de la GUI. Agregar nuevos comandos aquí.
- **`ClientHandler._stream_loop()`** — llama a `RadioState.as_dict()` y construye la trama `data` de salida a 10 Hz. Reemplazar la lista sintética de `Signal` con muestras SDR reales para obtener un espectro en vivo.
- **`UDPAudioChannel._tx_loop()`** — envía tramas RTP μ-law desde `AudioWavSource.read_frame()` o `_gen_sine_frame()`. Conectar aquí un demodulador SDR real para entregar audio de recepción real.
- **`UDPAudioChannel._rx_loop()`** — recibe RTP μ-law de la GUI durante PTT. El PCM decodificado se descarta actualmente; enrutarlo aquí a la ruta de transmisión SDR.
- **`IQWavSource`** — un lector de WAV IQ completo e independiente con bucle y salida FFT. Envolver una API SDR real (SoapySDR, enlaces Python de RTL-SDR, etc.) en la misma interfaz (`read_block(n)` → array complejo numpy) para alimentar muestras IQ en vivo a `_iq_fft_spectrum_db()`.

El protocolo JSON es intencionalmente simple: cualquier lenguaje o framework que pueda abrir un socket TCP y escribir JSON terminado en salto de línea puede manejar la GUI.
