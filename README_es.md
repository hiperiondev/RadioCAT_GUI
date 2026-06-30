<div align="center">
  <a href="https://github.com/hiperiondev/RadioCAT_GUI">
    <img src="images/full_gui.png" alt="captura de pantalla">
  </a>
</div>

# CAT GUI — Interfaz de Control SDR para Radio Aficionado

Un sistema cliente-servidor en Python para controlar un transceptor de Radio Definida por Software (SDR). `cat_gui.py` es una interfaz de escritorio Tkinter con todas las funciones; `cat_server.py` es un backend compatible con el protocolo que incluye un simulador de señales integrado para que la GUI funcione de inmediato — y puede ser reemplazado (o extendido) con un driver de hardware SDR real.

---

## Tabla de Contenidos

- [Descripción General](#descripción-general)
- [Arquitectura del Sistema](#arquitectura-del-sistema)
- [Características Destacadas](#características-destacadas)
- [Requisitos e Instalación](#requisitos-e-instalación)
- [Instalación y Uso en Windows](#instalación-y-uso-en-windows)
- [Inicio Rápido](#inicio-rápido)
- [Archivos de Configuración](#archivos-de-configuración)
  - [cat\_gui.toml — Configuración de la GUI](#cat_guitoml--configuración-de-la-gui)
  - [cat\_server.toml — Transporte y Lista de Dispositivos](#cat_servertoml--transporte-y-lista-de-dispositivos)
  - [cat\_device.toml — Perfil de Dispositivo](#cat_devicetoml--perfil-de-dispositivo)
  - [Archivos de Estado y Memorias por Dispositivo](#archivos-de-estado-y-memorias-por-dispositivo)
- [Referencia de Línea de Comandos](#referencia-de-línea-de-comandos)
  - [cat\_gui.py](#flags-cli-de-cat_guipy)
  - [cat\_server.py](#flags-cli-de-cat_serverpy)
- [Especificación del Protocolo TCP](#especificación-del-protocolo-tcp)
  - [Comandos GUI → Servidor](#comandos-gui--servidor)
  - [Mensajes Servidor → GUI](#mensajes-servidor--gui)
- [Diseño de la GUI y Controles](#diseño-de-la-gui-y-controles)
  - [Cascada y Espectro RF](#cascada-y-espectro-rf)
  - [Barra de Herramientas](#barra-de-herramientas)
  - [Panel de Control Izquierdo](#panel-de-control-izquierdo)
  - [Cascada AF, Espectro y Panel de Texto](#cascada-af-espectro-y-panel-de-texto)
- [Sistema de Audio](#sistema-de-audio)
- [Reproducción de WAV IQ y Audio (Servidor)](#reproducción-de-wav-iq-y-audio-servidor)
- [Memorias de Frecuencia](#memorias-de-frecuencia)
- [Perfiles de Dispositivo y Cambio entre Dispositivos](#perfiles-de-dispositivo-y-cambio-entre-dispositivos)
- [HiDPI / Escalado](#hidpi--escalado)
- [Temas y Fuentes](#temas-y-fuentes)
- [Referencia de Archivos Generados](#referencia-de-archivos-generados)
- [Extender el Servidor](#extender-el-servidor)

---

## Descripción General

CAT GUI implementa una interfaz completa de control de radio modelada en el aspecto visual de los transceptores SDR de alta gama. La GUI se conecta al servidor a través de un socket TCP local (o remoto) y se comunica mediante un protocolo JSON simple delimitado por saltos de línea. Un canal UDP independiente transporta audio bidireccional en tiempo real (audio de recepción del servidor al altavoz de la GUI; audio del micrófono de la GUI al servidor cuando PTT está activo).

El servidor de referencia incluido aquí es un **simulador**: genera señales portadoras RF sintéticas en un espectro de 192 kHz de ancho, produce un tono de audio de recepción de 440 Hz, acepta todos los comandos de la GUI y refleja todos los cambios de estado. Se pueden reproducir grabaciones IQ reales y audio de recepción real a través de él con dos flags (`--iq_wav` y `--audio_wav`). La arquitectura del servidor es intencionalmente mínima para que sea sencillo reemplazar el stub de generación de señales con un driver de hardware SDR real (SoapySDR, RTL-SDR, SDRplay, etc.).

---

## Arquitectura del Sistema

```
┌────────────────────────────────────────────────────┐
│                  cat_gui.py (cliente)              │
│                                                    │
│  ┌───────────┐  ┌──────────┐  ┌─────────────────┐  │
│  │  WFCanvas │  │SpecCanvas│  │  FreqDisp (×3)  │  │
│  │(cascada)  │  │(espectro)│  │  LO A / LO B /  │  │
│  └───────────┘  └──────────┘  │  Sintonía       │  │
│                               └─────────────────┘  │
│  ┌──────────────┐  ┌────────────────────────────┐  │
│  │RTPAudioClient│  │     NetClient (TCP)        │  │
│  │  UDP/G.711μ  │  │  JSON delimitado por \n    │  │
│  └──────────────┘  └────────────────────────────┘  │
└──────────────┬──────────────────────┬──────────────┘
               │  TCP (control)       │  UDP (audio)
               ▼                      ▼
┌────────────────────────────────────────────────────┐
│                cat_server.py (servidor)            │
│                                                    │
│  ┌────────────┐  ┌───────────────┐  ┌───────────┐  │
│  │RadioState  │  │ClientHandler  │  │UDPAudio   │  │
│  │  (todo el  │  │  (hilo TCP    │  │Channel    │  │
│  │  estado)   │  │  por cliente) │  │(TX+RX RTP)│  │
│  └────────────┘  └───────────────┘  └───────────┘  │
│  ┌────────────┐  ┌───────────────┐                 │
│  │IQWavSource │  │AudioWavSource │                 │
│  │(--iq_wav)  │  │(--audio_wav)  │                 │
│  └────────────┘  └───────────────┘                 │
└────────────────────────────────────────────────────┘
```

**Canal de control TCP** — objetos JSON UTF-8 delimitados por salto de línea. La GUI envía un objeto de comando por línea; el servidor responde con `{"resp": "ok"}` para cada comando. Solo para `hello` y `select_device`, la respuesta también incluye un diccionario de estado completo: `{"resp": "ok", "state": {...}}`. Durante la ejecución, el servidor además envía tramas `{"type": "data", ...}` a ~10 Hz con datos frescos de espectro, S-meter y squelch.

**Canal de audio UDP** — datagramas RTP con un encabezado de 12 bytes y una carga útil G.711 μ-law (PCMU) a 8 kHz / 8 bits / mono / tramas de 20 ms (160 bytes de μ-law por paquete). Bidireccional: servidor → GUI cuando PTT está desactivado (audio de recepción); GUI → servidor cuando PTT está activo (audio de micrófono para TX).

---

## Características Destacadas

### Visualización
- **Cascada RF** — desplazamiento incremental O(ancho) por trama con `PhotoImage.put()`, velocidad ajustable (1–10), se congela con la insignia "● TX" durante la transmisión
- **Espectro RF** — canvas de elementos retenidos (sin `delete("all")` por trama), superposición de pasabanda IF arrastrable, visualización de pico sostenido con decaimiento configurable, línea de cursor VFO
- **Cascada AF** — mismo motor que la cascada RF; impulsada desde el audio RTP decodificado localmente (no un valor calculado por el servidor), por lo que lo que se dibuja siempre coincide con lo que se escucha
- **Espectro AF** — FFT local del PCM recibido; se aplica una ventana de Hamming en todos los casos; usa `numpy.fft.rfft` cuando está disponible, y recurre a una FFT pura en Python Cooley-Tukey radix-2 en caso contrario
- Nivel de referencia (ESCALA) ajustable en pasos de ±5 dB; promediado FFT (AVE) 1–10; alternancia Cascada / Espectro por cuadro
- Líneas de cuadrícula y etiquetas del eje de frecuencias escaladas automáticamente a un paso "conveniente" para cualquier span o nivel de zoom

### Control de Frecuencia
- **LO dual (VFO A / B)** más una pantalla de **Sintonía** — tres lecturas de frecuencia ámbar independientes de 9 dígitos con separadores de miles
- Incremento/decremento con rueda del ratón por dígito (o clic izquierdo/derecho); doble clic abre un diálogo de entrada directa en Hz
- **Modo SPLIT** — LO A como RX, LO B como TX; etiquetas TX/RX mostradas junto a cada pantalla LO cuando está activo
- **Botones de banda** — 160 m a 6 m (rangos de la Región 2 de la UIT); al presionar uno se sintoniza directamente a la frecuencia central de la banda
- **Restricciones de banda** por dispositivo y por antena — los botones de banda deshabilitados aparecen en gris automáticamente
- **Botones M (Memoria)** — junto a cada fila de frecuencia; abre un diálogo de memoria de 20 ranuras por dispositivo

### Controles de Procesamiento de Señal
- Volumen, Umbral AGC, Ganancia RF, Squelch — controles deslizantes horizontales, reflejados instantáneamente al servidor
- **Botones de modo** — LSB, USB, AM, FM, CW, y hasta 10 modos de modulación definidos por el usuario
- **AGC** — desactivado / lento / medio / rápido, más un control deslizante de umbral AGC configurable
- **Filtro** — pasabanda arrastrado directamente en el canvas del espectro IF; bordes alto y bajo ajustables independientemente
- **Zoom** — botones de entrada/salida o rueda del ratón en el espectro IF; el zoom reduce el span RF mostrado
- Botones de alternancia: NB (eliminador de ruido), NR (reducción de ruido), NB RF, NB IF, AFC, ANF, Notch, Silencio
- **S-meter** — medidor analógico tipo arco con aguja animada, barra de pico sostenido, LED de squelch abierto/cerrado. Durante la transmisión, el arco cambia automáticamente a un **medidor ROS** (escala 1.0–5.0) con zonas codificadas por colores (verde → rojo) y un área de texto ROS numérico

### Gestión de Radio
- **Iniciar / Detener** — activa o desactiva el SDR (el servidor comienza o detiene el streaming de datos)
- **PTT** — botón circular, conmutación TX/RX instantánea; cascada/espectro congelados con insignia durante TX
- **INTERCAMBIAR** — intercambia las frecuencias LO A y LO B con un clic
- **BLOQUEAR** — bloquea el LO activo (o ambos LOs cuando SPLIT está activo) para evitar cambios accidentales de frecuencia; las pantallas de frecuencia y los botones **M** de los LOs bloqueados se deshabilitan
- **Barra de transporte** — Grabar ●, Reproducir ▶, Pausa ⏸, Detener ■, Rebobinar ◀◀, Avance rápido ▶▶, Bucle ∞
- **Selector de dispositivo** — hasta 20 perfiles de dispositivo con nombre; al cambiar guarda el estado actual y restaura el estado persistido del dispositivo destino y sus memorias
- **Selector de ancho de banda** — combobox poblado desde el `bandwidth_map` del servidor para el modo actual; los botones de paso `◄` / `►` desplazan el LO activo por el ancho de banda seleccionado
- **Selector de potencia TX** — se muestra cuando el perfil del dispositivo define `power_levels`; abre un diálogo modal que envía `set_power` al servidor
- **Selector de antena** — hasta 10 puertos etiquetados por dispositivo, cada uno con su propia restricción de banda opcional
- **Selector de tasa de muestreo** — lista de tasas de muestreo SDR seleccionables por dispositivo
- **Selector de tarjeta de sonido** — enumeración de dispositivos PyAudio; selección independiente de micrófono y altavoz
- **Botones definidos por el usuario** — 14 botones programables (2 filas de 7), cada uno independientemente `normal` (momentáneo) o `push` (alternancia/latch)
- **Botones RF de usuario** — 11 botones programables a la izquierda del arreglo de bandas, mismos tipos normal/push; una **pulsación larga (≥ 3 s)** abre un diálogo de configuración en la aplicación cuyos widgets se definen por botón en la clave `config_N` del perfil de dispositivo
- **Panel de texto/RTTY** — los modos de modulación definidos por el usuario pueden dividir el cuadro AF para revelar un panel de texto de solo lectura o un panel de chat bidireccional estilo RTTY en vivo

### Ventana y Escalado
- Detecta automáticamente los DPI de la pantalla y elige el mejor nivel de escala; botones de escala `+` / `−` manuales siempre disponibles
- Factor de escala de 1,25ˢᶜᵃˡᵉ (p.ej., nivel 2 = 1,5625×); rango −5 a +5
- El panel de control inferior **siempre permanece completamente visible** a cualquier tamaño de ventana — la cascada/espectro RF se reducen primero
- Manejador de redimensionamiento `<Configure>` con debounce evita saltos de diseño durante el arrastre de la ventana
- Flag `--full-screen`; alternancia con triple-Esc mientras se ejecuta
- Flags `--resolution WxH` y `--aspect-ratio W:H`; la relación de aspecto se aplica después de que el diseño se estabilice

---

## Requisitos e Instalación

### Versión de Python
Python **3.9** o posterior. Python 3.11+ incluye `tomllib` en la biblioteca estándar; las versiones anteriores necesitan `tomli`.

### Dependencia Principal
`tkinter` está incluido en la biblioteca estándar pero puede requerir un paquete de SO separado en algunas distribuciones de Linux:

```bash
# Debian / Ubuntu
sudo apt install python3-tk

# Fedora / RHEL
sudo dnf install python3-tkinter
```

### Dependencias Opcionales

| Paquete | Propósito | Instalación |
|---------|-----------|-------------|
| `numpy` | FFT acelerada para espectro (ambos lados); requerida para `--iq_wav` en el servidor | `pip install numpy` |
| `tomli` | Soporte de configuración TOML en Python < 3.11 | `pip install tomli` |
| `pyaudio` | Audio de micrófono y altavoz (solo GUI) | `pip install pyaudio` |
| `fonttools` | Búsqueda autoritativa del nombre de familia PostScript para fuentes personalizadas | `pip install fonttools` |

Sin `pyaudio` la GUI funciona normalmente pero la entrada/salida de audio se desactiva silenciosamente. Sin `numpy` el renderizado del espectro recurre a una FFT pura en Python (correcta pero más lenta). Sin `tomli`/`tomllib` se usa un analizador TOML mínimo incorporado (cubre todas las claves que producen las plantillas de configuración incluidas).

### Instalación

```bash
# Clonar o descargar el repositorio, luego:
pip install numpy tomli pyaudio fonttools   # todas opcionales, instalar según necesidad
```

No se requiere `setup.py` ni `pyproject.toml` — ambos scripts se ejecutan directamente.

---

## Instalación y Uso en Windows

Todo en este proyecto funciona en Windows sin dependencias específicas de UNIX. Los pasos a continuación cubren una máquina limpia desde cero.

### 1. Instalar Python

Descargue el instalador de **Python 3.11** (o posterior) desde [python.org/downloads](https://www.python.org/downloads/windows/).

Durante la instalación:

- Marque **"Add python.exe to PATH"** en la primera pantalla — esta opción está desmarcada por defecto.
- Haga clic en **"Customize installation"** y confirme que **"tcl/tk and IDLE"** esté marcado. Esto instala `tkinter`, el toolkit de GUI usado por `cat_gui.py`. Si omite esto, la GUI no podrá importar `tkinter` y no arrancará.

Verifique después de la instalación abriendo el **Símbolo del sistema** (`Win + R` → `cmd`) y ejecutando:

```cmd
python --version
python -c "import tkinter; print('tkinter OK')"
```

Ambos comandos deben completarse sin error.

### 2. Instalar Dependencias Opcionales

Abra el **Símbolo del sistema** o **PowerShell** y ejecute:

```cmd
pip install numpy tomli pyaudio fonttools
```

#### PyAudio en Windows

`pip install pyaudio` falla frecuentemente en Windows porque intenta compilar una extensión C sin un compilador presente. La solución más limpia es instalar un wheel precompilado:

```cmd
pip install pipwin
pipwin install pyaudio
```

Alternativamente, descargue el archivo `.whl` correspondiente a su versión de Python desde la página [Unofficial Windows Binaries for Python Extension Packages](https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio) (busque `PyAudio‑0.2.x‑cpXXX‑cpXXX‑win_amd64.whl` donde `XXX` coincide con su versión de Python), luego instálelo directamente:

```cmd
pip install PyAudio-0.2.14-cp311-cp311-win_amd64.whl
```

Si no se puede instalar PyAudio, la GUI sigue funcionando completamente — la entrada/salida de audio se deshabilita silenciosamente y se imprime un aviso en la consola.

### 3. Obtener los Scripts

Descargue `cat_gui.py` y `cat_server.py` (y `morgenta_regular.ttf` si desea la fuente de frecuencia incluida) en la misma carpeta, por ejemplo `C:\CAT`.

### 4. Abrir un Directorio de Trabajo

Todos los archivos de configuración, estado y memoria se crean en el **directorio de trabajo actual** cuando los scripts se ejecutan por primera vez. Es recomendable hacer `cd` hacia su carpeta de proyecto antes de iniciar cualquier cosa:

```cmd
cd C:\CAT
```

### 5. Ejecutar el Servidor

```cmd
python cat_server.py
```

En la primera ejecución (cuando no existen `cat_server.toml` ni `cat_device.toml`), el servidor crea archivos de plantilla `.example` anotados junto a donde vivirían las configuraciones reales, y luego se ejecuta con los valores predeterminados incorporados. La consola mostrará:

```
[config] cat_server.toml not found — using built-in defaults (copy cat_server.toml.example to cat_server.toml to customise)
[config] cat_device.toml not found — using built-in defaults (copy cat_device.toml.example to cat_device.toml to customise)
[cat_server] listening on 0.0.0.0:50101
```

Para persistir su configuración, copie (o renombre) los archivos `.example`:

```cmd
copy cat_server.toml.example cat_server.toml
copy cat_device.toml.example cat_device.toml
```

**Aviso del Firewall de Windows** — Windows puede mostrar una alerta de seguridad la primera vez que el servidor abre un socket. Haga clic en **"Permitir acceso"** (como mínimo para redes privadas) para que la GUI pueda alcanzarlo, incluso cuando ambos procesos están en la misma máquina.

### 6. Ejecutar la GUI

Abra una **segunda** ventana del Símbolo del sistema, haga `cd` a la misma carpeta y ejecute:

```cmd
python cat_gui.py
```

En la primera ejecución se crea `cat_gui.toml`. Se abre la ventana de la GUI. Escriba `127.0.0.1` en el campo **Host** y `50101` en el campo **Puerto** (estos son los valores predeterminados ya mostrados), luego haga clic en **Conectar** seguido de **Iniciar**.

> **Consejo — autoconexión:** Para omitir la fila Host/Puerto/Conectar completamente en lanzamientos posteriores, edite `cat_gui.toml` y configure:
> ```toml
> [connection]
> host = "127.0.0.1"
> port = 50101
> autoconnect = true
> ```
> La GUI se conectará automáticamente al inicio y la fila de conexión quedará oculta.

### 7. Ejecutar en Ventanas Separadas (Recomendado)

Dado que el servidor y la GUI son procesos separados, es conveniente ejecutar cada uno en su propia ventana. Un archivo batch simple para esto:

**`start_all.bat`** (guardar en `C:\CAT`):

```bat
@echo off
cd /d %~dp0
start "CAT Server" cmd /k python cat_server.py
timeout /t 1 >nul
start "CAT GUI"    cmd /k python cat_gui.py
```

Haga doble clic en `start_all.bat` para iniciar ambos en ventanas con título separado. Cerrar cualquiera de las ventanas detiene ese proceso limpiamente.

### 8. Notas Específicas de Windows

#### Selección de Dispositivo de Audio

Windows frecuentemente tiene múltiples endpoints de audio (p.ej., altavoces, auriculares, cable virtual). Para listar todos los dispositivos y sus índices:

```cmd
python cat_gui.py --audio-list
```

Luego inicie la GUI apuntando a dispositivos específicos:

```cmd
python cat_gui.py --audio-mic 1 --audio-speaker 2
```

O configúrelos de forma persistente en `cat_gui.toml`:

```toml
[audio]
mic = 1
speaker = 2
```

#### Fuentes Personalizadas

Las fuentes TTF/OTF personalizadas funcionan en Windows sin derechos de administrador. La GUI llama a `AddFontResourceExW` con los flags `FR_PRIVATE | FR_NOT_ENUM`, que registra la fuente solo en el proceso — sin instalación a nivel de sistema y sin solicitud de UAC. Simplemente apunte `--freq-font` a cualquier archivo `.ttf` u `.otf`:

```cmd
python cat_gui.py --freq-font "C:\Fonts\MyFont.ttf"
```

O en `cat_gui.toml`:

```toml
[display]
freq_font = "C:\\Fonts\\MyFont.ttf"
```

Note las **barras invertidas dobles** en los strings TOML, o use barras diagonales (ambas funcionan en Windows):

```toml
freq_font = "C:/Fonts/MyFont.ttf"
```

#### HiDPI / Pantallas 4K

En monitores de alta DPI, Windows aplica escalado de pantalla. Si la GUI aparece borrosa o sobredimensionada, Python puede estar recibiendo coordenadas pre-escaladas de Windows. La lógica de autoescala ya compensa leyendo la resolución real de la pantalla y seleccionando el mejor nivel de escala, pero puede anularlo:

```cmd
python cat_gui.py --scale 2
```

O configúrelo en `cat_gui.toml`:

```toml
[display]
scale = 2
disable_scale = false
```

También puede hacer clic derecho en `python.exe` → Propiedades → Compatibilidad → Cambiar configuración de DPI alto → **"Invalidar comportamiento de escalado de DPI alto: Aplicación"** para que Python maneje los DPI en lugar de Windows.

#### Modo Pantalla Completa

```cmd
python cat_gui.py --full-screen
```

Una vez en ejecución, presione **Esc tres veces en un segundo** para alternar pantalla completa.

#### Firewall y Conexiones Remotas

Si el servidor y la GUI se ejecutan en **máquinas diferentes** (p.ej., servidor en un PC de la estación, GUI en una laptop por LAN), debe permitir conexiones entrantes tanto en el puerto de control TCP como en el puerto de audio UDP a través del Firewall de Windows Defender:

1. Abra **Firewall de Windows Defender con seguridad avanzada** (`wf.msc`).
2. Agregue una **Regla de entrada** → Tipo de regla: Puerto → TCP → puerto `50101` → Permitir.
3. Agregue una segunda **Regla de entrada** → Tipo de regla: Puerto → UDP → puerto `5004` → Permitir.

Luego inicie el servidor normalmente y apunte la GUI a la IP LAN del servidor:

```cmd
python cat_gui.py --host 192.168.1.10 --port 50101
```

#### Problemas con PATH

Si `python` no se encuentra después de la instalación, use la ruta completa (`C:\Users\SuNombre\AppData\Local\Programs\Python\Python311\python.exe`) o vuelva a ejecutar el instalador de Python y marque **"Add Python to environment variables"** en el paso de personalización.

Si `pip` no se encuentra, ejecute:

```cmd
python -m pip install numpy tomli pyaudio fonttools
```

#### Codificación de la Consola

Si la consola imprime caracteres ilegibles (raro en Windows 10/11 moderno), configure la página de código a UTF-8 antes de ejecutar:

```cmd
chcp 65001
python cat_server.py
```

---

## Inicio Rápido

**1. Inicie el servidor** (puerto predeterminado 50101, señales RF simuladas):

```bash
python cat_server.py
```

En la primera ejecución, si `cat_server.toml` o `cat_device.toml` están ausentes, el servidor crea archivos de plantilla `.example` y se ejecuta con los valores predeterminados incorporados. Copie los ejemplos para activar la configuración personalizada:

```bash
cp cat_server.toml.example cat_server.toml
cp cat_device.toml.example cat_device.toml
```

**2. Inicie la GUI** (se conecta a 127.0.0.1:50101 por defecto):

```bash
python cat_gui.py
```

**3.** En la GUI, haga clic en **Conectar**, luego en **Iniciar**.

La cascada RF y el espectro comenzarán a desplazarse, el S-meter se animará y un tono de recepción de 440 Hz se reproducirá a través del altavoz del sistema (si PyAudio está instalado).

---

## Archivos de Configuración

Ambos lados **se autocorrigen** en sus archivos de configuración TOML en cada ejecución: si falta una clave (p.ej., después de una actualización que agrega una nueva opción), se añade con su valor predeterminado y el archivo se reescribe en su lugar.

### cat\_gui.toml — Configuración de la GUI

Creado en el directorio de trabajo como `cat_gui.toml` (anulable con `--config RUTA`).

```toml
# Configuración de CAT GUI
# Los flags de CLI anulan estos valores en tiempo de ejecución sin modificar este archivo.

[display]
bg = "dark"           # "light" o "dark"
full_screen = false   # iniciar en modo pantalla completa
scale = 0             # nivel de escala HiDPI, -5 a 5
disable_scale = false # ocultar los controles de escala +/-
freq_font = ""        # ruta a fuente TTF/OTF para pantallas de dígitos de frecuencia
gui_font = ""         # ruta a fuente TTF/OTF para el resto del texto de la GUI

[connection]
# Tanto host como port deben estar configurados, y autoconnect = true, para conectar al inicio.
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

Creado como `cat_server.toml` (anulable con `--config RUTA`). Contiene la configuración de transporte del servidor y la lista de hasta 20 perfiles de dispositivo con nombre.

```toml
[server]
host = "0.0.0.0"
port = 50101

[audio]
audio_port = 5004
no_audio = false

[devices]
# Hasta 20 perfiles de dispositivo. Etiqueta vacía = ranura no usada.
label_1 = "Main SDR"
config_1 = "devcfg_main.toml"
label_2 = ""
config_2 = ""
# ... label_3 / config_3 ... label_20 / config_20
```

### cat\_device.toml — Perfil de Dispositivo

Creado como `cat_device.toml` (anulable con `--device-config RUTA`). Define el diseño de la GUI para un dispositivo: sus botones programables, modos de modulación, tasas de muestreo SDR y puertos de antena.

```toml
[user_buttons]
# Hasta 14 botones definidos por el usuario. Las ranuras deben llenarse en orden (sin saltos).
label_1 = "CW Spot"
type_1 = "push"     # "normal" (momentáneo), "push" (alternancia/latch), o "list" (lista desplegable)
list_1 = ""         # ítems desplegables separados por comas cuando el tipo es "list" (máx. 20 chars cada uno)
label_2 = ""
# ... label_3 / type_3 / list_3 ... label_14 / type_14 / list_14

[user_mods]
# Hasta 10 botones de modulación definidos por el usuario. Las ranuras deben llenarse en orden.
label_1 = "RTTY"
type_1 = "text_input"  # "normal", "text", o "text_input"
# ... label_2 / type_2 ... label_10 / type_10

[rf_usr_btns]
# Hasta 11 botones mostrados a la izquierda del arreglo de bandas en el panel RF.
# Los botones con etiquetas vacías se ocultan en la GUI.
label_1 = "ATU"
mode_1 = "push"     # "normal" (momentáneo) o "push" (alternancia push-push)
# config_1: dict codificado en JSON que define el diálogo de configuración de pulsación larga (≥ 3 s).
# String vacío o "{}" = sin diálogo para este botón.
# Cada clave es la etiqueta del widget; el valor es un objeto de especificación de widget.
# Se admiten cuatro tipos de widget:
#   slide  → {"type": "slide", "range": [min, max]}
#   list   → {"type": "list", "values": [{"key": "Etiqueta", "val": "valor"}, …]}
#   check  → {"type": "check"}
#   radio  → {"type": "radio", "options": ["val1", "val2", …]}
# Ejemplo (deslizador 0–100, un grupo de radio de dos opciones y una casilla de verificación):
config_1 = '{"Power": {"type":"slide","range":[0,100]}, "Band": {"type":"radio","options":["HF","VHF"]}, "Bypass": {"type":"check"}}'
# ... label_2 / mode_2 / config_2 ... label_11 / mode_11 / config_11

[bandwidth]
# Anchos de banda de filtro disponibles (Hz) para cada modo de modulación.
# Se requiere una entrada coincidente para cada etiqueta definida en [user_mods];
# el servidor se negará a iniciar (sys.exit) si falta alguna etiqueta aquí.
AM  = "3000,6000,9000,10000"
FM  = "12500,25000"
LSB = "2700,3600"
USB = "2700,3600"
CW  = "250,500,1000,2000"
# RTTY = "250,500"   ← agregar una línea por cada etiqueta de [user_mods] que defina

[sdr]
sample_rate = 192000
# Lista separada por comas de tasas seleccionables para este dispositivo.
sample_rates = "192000,250000,500000,1000000,2000000"
# Lista separada por comas de bandas a las que puede sintonizarse este dispositivo (vacío = todas).
allowed_bands = "160m,80m,60m,40m,30m,20m,17m,15m,12m,10m,6m"
# Niveles de potencia TX separados por comas en vatios; vacío = selector de potencia oculto.
power_levels = "5.0,10.0,25.0,50.0,100.0"

[antenna]
# Hasta 10 puertos de antena. Etiqueta vacía = ranura no usada/oculta.
label_1 = "Dipolo"
allowed_bands_1 = ""          # vacío = heredar allowed_bands del nivel de dispositivo
label_2 = "Vertical HF"
allowed_bands_2 = "40m,20m,15m,10m"
# ... label_3 / allowed_bands_3 ... label_10 / allowed_bands_10
```

Cada entrada en la sección `[devices]` de `cat_server.toml` apunta a un archivo compatible con `cat_device.toml` **separado** para ese perfil. Cambiar de dispositivo en la GUI carga los botones, tasas de muestreo, memorias y último estado de GUI guardado de ese perfil.

### Archivos de Estado y Memorias por Dispositivo

Estos se generan automáticamente junto al archivo de configuración de cada dispositivo:

| Archivo | Contenido |
|---------|-----------|
| `<dispositivo>.gui_state.json` | Configuración persistida del operador: frecuencias (LO A/B/Sintonía), modo, filtro, AGC, ganancias, squelch, alternancias, zoom, tasa de muestreo, estados de botones, selección de antena, configuración de pantalla de espectro, ancho de banda seleccionado (`selected_bw`), valores del diálogo de configuración de botones RF de usuario (`rf_usr_btn_config_vals`) |
| `<dispositivo>.memories.json` | 3 × 20 memorias de frecuencia (LO A, LO B, Sintonía) con etiquetas y frecuencias |

El estado se guarda cuando el operador cambia de dispositivo y se restaura cuando regresa. Las ranuras de memoria se escriben inmediatamente cada vez que se guarda una ranura desde la GUI.

---

## Referencia de Línea de Comandos

### Flags CLI de cat\_gui.py

```
python cat_gui.py [OPCIONES]

Conexión:
  --host HOST            Nombre de host o IP del servidor (debe combinarse con --port)
  --port PORT            Puerto TCP del servidor (debe combinarse con --host)
  --autoconnect          Conectar automáticamente al inicio; oculta la fila
                         host/puerto/conectar en la GUI

Visualización:
  --bg {light,dark}      Tema de fondo ("dark" es el predeterminado)
  --full-screen          Iniciar en modo pantalla completa (triple-Esc para alternar)
  --resolution WxH       Tamaño inicial de la ventana en píxeles, p.ej. 1280x720
  --aspect-ratio W:H     Bloquear la ventana a una relación de aspecto, p.ej. 16:9 o 4:3
                         (ignorado cuando se usa --full-screen)
  --scale INT            Nivel de escala HiDPI inicial, -5 a 5 (0 = detección automática)
  --disable-scale        Ocultar los botones de escala +/- (combinar con --scale)
  --freq-font RUTA       Archivo de fuente TTF/OTF para las pantallas de frecuencia LO/Sintonía
  --gui-font RUTA        Archivo de fuente TTF/OTF para el resto del texto de la GUI

Audio:
  --audio-list           Imprimir todos los índices de dispositivos de audio y salir
  --audio-mic ÍNDICE     Seleccionar dispositivo de micrófono por índice (combinar con --audio-speaker)
  --audio-speaker ÍNDICE Seleccionar dispositivo de altavoz por índice (combinar con --audio-mic)
  --disable-soundcard-select
                         Ocultar el botón de Tarjeta de Sonido en la GUI

Varios:
  --config RUTA          Cargar configuración TOML de la GUI desde RUTA en lugar de ./cat_gui.toml
  --debug                Activar salida de depuración detallada en la consola

Restricción de Banda:
  --restrict-band        Bloquear cualquier cambio de LO que caiga fuera de las
                         allowed_bands del dispositivo activo (las bandas amateur estándar
                         fuera de esa lista siempre se rechazan). Sin este flag,
                         allowed_bands solo pone en gris los botones de banda; la entrada
                         de frecuencia por teclado y rueda del ratón no tiene restricciones.
```

### Flags CLI de cat\_server.py

```
python cat_server.py [OPCIONES]

Transporte:
  --host HOST            Dirección de escucha TCP (predeterminado: 0.0.0.0)
  --port PORT            Puerto de escucha TCP (predeterminado: 50101)
  --audio-port PORT      Puerto de audio RTP UDP (predeterminado: 5004)
  --no-audio             Deshabilitar el canal de audio UDP completamente

Archivos de configuración:
  --config RUTA          Cargar cat_server.toml desde RUTA en lugar de ./cat_server.toml
  --device-config RUTA   Cargar cat_device.toml desde RUTA en lugar de ./cat_device.toml

IQ y Audio:
  --iq_wav RUTA          Archivo WAV de muestras IQ para el espectro/cascada RF
                         (PCM/float estéreo, I=izquierda, Q=derecha; chunk auxi opcional
                         para frecuencia central). En bucle infinito. Requiere numpy.
  --audio_wav RUTA       Archivo WAV para transmitir como audio de recepción simulado (en bucle).
                         Remuestreado a 8 kHz mono. Reemplaza el tono de 440 Hz incorporado.

Botones definidos por el usuario (también configurables via cat_device.toml):
  --user-button-label-N TEXTO   Etiqueta para el botón de usuario N (1–14, máx. 7 chars)
  --user-button-type-N TIPO     "normal" o "push" para el botón de usuario N

Modos de modulación definidos por el usuario:
  --user_mod_N ETIQUETA  Etiqueta para el botón de modo de usuario N (1–10, máx. 4 chars)
  --user_mod_type_N TIPO "normal", "text", o "text_input" para la ranura N

Botones RF de usuario:
  --rf_usr_btn_N ETIQUETA   Etiqueta para el botón RF de usuario N (1–11, máx. 7 chars)
  --rf_usr_btn_mode_N M     "normal" o "push" para el botón RF de usuario N
```

> **Prioridad:** Los flags CLI siempre superan al archivo de configuración TOML, que supera a los valores predeterminados incorporados. Los flags de ranuras de botones/modos deben especificarse secuencialmente (1, 2, 3 …) sin saltos; el servidor dará error si se omite una ranura.

---

## Especificación del Protocolo TCP

Todos los mensajes son objetos JSON UTF-8 terminados en salto de línea (`\n`). Un objeto por línea en ambas direcciones. El servidor acepta múltiples clientes TCP simultáneos (cada uno en su propio hilo).

### Comandos GUI → Servidor

Cada comando recibe una respuesta inmediata `{"resp": "ok"}`. Los comandos marcados con ★ también devuelven un diccionario de estado completo en la misma respuesta: `{"resp": "ok", "state": {...estado completo del radio...}}`.

#### Inicio

| Comando | Campos | Notas |
|---------|--------|-------|
| `hello` ★ | — | Enviado al conectar; activa un push de `reload_state` y devuelve el estado completo |

#### Frecuencia

| Comando | Campos | Notas |
|---------|--------|-------|
| `set_freq` | `hz: int` | Establecer frecuencia LO A (recepción principal) |
| `set_lo_a_freq` | `hz: int` | Alias de `set_freq` |
| `set_lo_b_freq` | `hz: int` | Establecer frecuencia LO B (TX en split) |
| `set_tune_freq` | `hz: int` | Establecer frecuencia de Sintonía (desplazamiento BFO/IF) |
| `set_lo` | `lo: "A"\|"B"` | Seleccionar LO activo |

#### Modo y DSP

| Comando | Campos | Notas |
|---------|--------|-------|
| `set_mode` | `mode: str` | p.ej. `"USB"`, `"LSB"`, `"AM"`, `"FM"`, `"CW"` |
| `set_agc` | `mode: str` | `"off"`, `"slow"`, `"medium"`, `"fast"` |
| `set_agc_thresh` | `value: float` | Umbral AGC en dBm (−140 a −20) |
| `set_filter` | `lo: int, hi: int` | Bordes de pasabanda IF en Hz (p.ej. `lo=100, hi=2800`) |
| `set_zoom` | `value: int` | Factor de zoom (≥ 1) |
| `set_rf_gain` | `value: float` | Ganancia RF en dB (0–60) |
| `set_volume` | `value: float` | Volumen de audio (0–100) |
| `set_squelch` | `value: float` | Nivel de squelch en dBm (−140 a 0) |
| `set_nb` | `enabled: bool` | Eliminador de ruido (audio/IF) |
| `set_nbrf` | `enabled: bool` | Eliminador de ruido (RF) |
| `set_nbif` | `enabled: bool` | Eliminador de ruido (IF) |
| `set_nr` | `enabled: bool` | Reducción de ruido |
| `set_afc` | `enabled: bool` | Control automático de frecuencia |
| `set_anf` | `enabled: bool` | Filtro de muesca automático |
| `set_notch` | `enabled: bool` | Filtro de muesca manual |
| `set_mute` | `enabled: bool` | Silencio de audio |
| `set_selected_bw` | `value: int` | Establecer el ancho de banda activo desde la lista `bandwidth_map` del modo actual (Hz) |

#### Pantalla de Espectro

| Comando | Campos | Notas |
|---------|--------|-------|
| `set_spec_ref` | `box: "rf"\|"af", value: float` | Nivel de referencia (parte superior de la pantalla) en dB, ajustado al múltiplo de 5 dB más cercano, rango −50 a +10 |
| `set_spec_ave` | `box: "rf"\|"af", value: int` | Cantidad de promediado FFT, 1–10 |

#### PTT, SPLIT, Transporte

| Comando | Campos | Notas |
|---------|--------|-------|
| `set_ptt` | `enabled: bool, udp_port: int` | Activar/desactivar PTT; `udp_port` indica al servidor dónde enviar el audio TX |
| `set_split` | `enabled: bool` | Activar/desactivar SPLIT (LO A RX, LO B TX) |
| `start` | — | Iniciar streaming SDR |
| `stop` | — | Detener streaming SDR |
| `transport` | `action: str` | `"rec"`, `"play"`, `"pause"`, `"stop"`, `"rw"`, `"ff"`, `"infinite"` |

#### Dispositivo y Hardware

| Comando | Campos | Notas |
|---------|--------|-------|
| `get_devices` | — | Devuelve `{"type": "device_list", "devices": [...]}` |
| `select_device` ★ | `index: int` | Índice de dispositivo base-1; guarda el estado actual, carga el nuevo dispositivo |
| `get_sample_rates` | — | Devuelve `{"type": "sample_rate_list", "rates": [...], "current": N}` |
| `set_sample_rate` | `value: int` | Establecer tasa de muestreo (debe estar en la lista configurada de este dispositivo) |
| `get_antennas` | — | Devuelve `{"type": "antenna_list", "antennas": [...], "current": N, "device_allowed_bands": [...]}` |
| `select_antenna` | `index: int` | Índice de puerto de antena base-1 (0 = deseleccionar) |
| `get_power_levels` | — | Devuelve la lista de niveles de potencia TX para el dispositivo actual |
| `set_power` | `index: int` | Seleccionar nivel de potencia TX por índice base-0 desde la lista `power_levels` del dispositivo; ignorado silenciosamente (con aviso en consola) si el índice está fuera de rango |

#### Botones de Usuario y Texto

| Comando | Campos | Notas |
|---------|--------|-------|
| `user_button` | `index: int` | Pulsación momentánea del botón de usuario N (base-1) |
| `user_button` | `index: int, enabled: bool` | Estado push-push (alternancia) del botón de usuario N |
| `user_button` | `index: int, choice: int` | Índice de selección para un botón de usuario tipo `"list"` |
| `rf_usr_button` | `index: int` | Pulsación momentánea o alternancia push-push del botón RF de usuario N (1–11, izquierda de los botones de banda) |
| `rf_usr_button` | `index: int, enabled: bool` | Estado push explícito para un botón RF de usuario tipo `"push"` |
| `rf_usr_btn_config_set` | `index: int, values: {name: value, …}` | Almacenar valores del diálogo de configuración para el botón RF de usuario N; persistido en `.gui_state.json` |
| `user_text` | `index: int, text: str` | Texto enviado por el operador en un panel de modo `text_input` |
| `ui_display` | `box: str, view: str` | Alternancia de vista Cascada / Espectro |
| `ui_toolbar` | `box: str, action: str` | Clic en botón de barra de herramientas (barra de Cascada / Espectro) |
| `ui_smeter_btn` | `action: str` | Clic en botón del S-meter (Pico / S-unidades / Squelch) |
| `ui_button` | `action: str` | Botón de control de GUI (Pantalla Completa, Dispositivo SDR, Gestión de Frecuencia, Minimizar, Salir) |
| `memory` | — | Pulsación momentánea legada del botón "M" (sin operación; mantenido por compatibilidad con versiones anteriores de la GUI) |

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

#### Trama de Datos en Streaming (~10 Hz mientras se ejecuta)

```json
{
  "type": "data",
  "f_start": 28390000,
  "f_stop": 28590000,
  "spectrum": [-120.5, -118.3, ...],       // valores dBm de NUM_BINS
  "af_range": 3000,
  "af_spectrum": [-95.1, -93.0, ...],      // valores dBm de AF_BINS (0..3000 Hz)
  "smeter_dbm": -73.0,
  "smeter_text": "S9",
  "squelch_open": true,
  "swr": null,                             // float (p.ej. 1.35) mientras PTT activo; null si no
  "state": { ... }                         // campos de estado incrementales
}
```

La GUI usa `f_start`/`f_stop` para posicionar el eje de frecuencias del espectro/cascada RF; `af_range` (siempre 3000 Hz) para el eje de visualización AF.

#### Envíos No Solicitados

| Tipo | Campos | Significado |
|------|--------|-------------|
| `audio_port` | `port, sample_rate, frame_ms, codec` | Emitido al conectar el cliente; indica a la GUI qué puerto UDP abrir para audio |
| `reload_state` | — | La GUI debe resincronizar todos los widgets desde el estado `resp:ok` precedente |
| `device_list` | `devices: [{index, label}]` | Respuesta a `get_devices` |
| `sample_rate_list` | `rates: [int], current: int` | Respuesta a `get_sample_rates` |
| `antenna_list` | `antennas: [...], current: int, device_allowed_bands: [...]` | Respuesta a `get_antennas` |
| `memory_list` | `position: str, memories: [{label, freq}×20]` | Respuesta a `get_memories` o `save_memory` |
| `power_level_list` | `levels: [str], current: int` | Respuesta a `get_power_levels`; impulsa el diálogo del selector de potencia TX |
| `bandwidth_map` | `map: {mode: [int, ...]}` | Enviado al conectar y al cambiar de dispositivo; llena el combobox del selector de ancho de banda por modo |
| `user_text` | `index: int, text: str` | Texto enviado por el servidor a una ranura de panel `text`/`text_input` |
| `disconnected` | (`reason` opcional) | Emitido internamente por la GUI cuando cae la conexión TCP |

#### Diccionario de Estado

El diccionario de estado completo (enviado en `resp:ok` para `hello` / `select_device`, e incrementalmente en tramas `data`) contiene:

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

Notas clave:
- `rf_usr_btn_config_vals` — dict indexado por índice de botón base-1 (como string); el valor es un dict `{name: value}` de los últimos valores enviados via `rf_usr_btn_config_set`. Persistido en `.gui_state.json`.
- `selected_bw` — ancho de banda seleccionado actualmente como string en Hz (p.ej. `"2700"`). Persistido por dispositivo.
- `active_device_index` — índice base-1 del perfil de dispositivo activo (0 = ninguno). Usado por la GUI para restaurar la etiqueta del dispositivo al inicio y marcar el dispositivo activo en el diálogo de dispositivos.
- `antenna_allowed_bands` — lista de 10 listas de nombres de banda ordenadas (una por ranura de antena). Lista interna vacía = heredar `allowed_bands` del nivel de dispositivo.
- `swr` **solo en tramas data** — valor ROS flotante (p.ej. `1.35`) mientras PTT está activo; `null` cuando PTT está inactivo. Impulsa el medidor ROS en el S-meter. (No en el dict de estado; solo en tramas `type: "data"`.)

---

## Diseño de la GUI y Controles

### Cascada y Espectro RF

El panel RF ocupa la parte superior de la ventana y se divide en dos subpaneles apilados verticalmente:

**Cascada RF** (`WFCanvas`) — el panel más grande y expandible en la parte superior. Las nuevas filas de espectro se anteponen en la parte superior para que los datos más recientes estén siempre arriba y el historial se desplace hacia abajo. La velocidad de desplazamiento se controla con el control de Velocidad en la barra de herramientas. Durante PTT, la cascada se congela y se muestra la insignia "● TX".

**Espectro RF** (`SpecCanvas`) — tira de altura fija debajo de la cascada. Dibujado con una técnica de objeto retenido (todos los elementos del canvas se crean una vez al inicio; cada trama solo actualiza las coordenadas). Muestra: traza de espectro con relleno verde, una superposición de pasabanda IF semitransparente (rectángulo azul con bordes arrastrables), una línea de cursor VFO (rojo), y una línea de pico sostenido (azul-blanco). Los bordes del filtro IF se pueden arrastrar directamente con el ratón. La rueda del ratón sobre el espectro hace zoom de entrada/salida.

### Barra de Herramientas

Una tira estrecha entre el panel RF y la fila inferior contiene controles por cuadro para el panel RF (arriba) y el panel AF (abajo):

- **Cascada / Espectro** — botones de alternancia mutuamente excluyentes para cambiar el modo de visualización de este cuadro
- **ESCALA** — nivel de referencia (parte superior de la pantalla) en dB; botones +/− avanzan de 5 en 5 dB (rango −50 a +10)
- **AVE** — cantidad de promediado FFT; botones +/− avanzan de 1 en 1 (rango 1–10)
- **VELOCIDAD** — velocidad de desplazamiento de la cascada; botones +/− avanzan de 1 en 1 (rango 1–10)
- Etiquetas **RBW** / **Span** (informativas)

### Panel de Control Izquierdo

El panel izquierdo tiene ancho fijo y aloja todos los controles del transceptor, de arriba a abajo:

**Fila S-meter** — canvas de S-meter analógico tipo arco con aguja animada, indicador de pico sostenido, LED de squelch abierto/cerrado, y un botón PTT circular fijado a la derecha. Cuando PTT está activo, el medidor de arco cambia automáticamente a un **medidor ROS** (escala 1.0–5.0) con zonas codificadas por colores (verde para ROS bajo, pasando por ámbar a rojo para ROS alto); el área de texto dBm / S-unidad se reemplaza con una lectura ROS numérica. El S-meter se reanuda cuando se libera PTT.

**Pantallas de frecuencia** — tres widgets `FreqDisp` (LO A, LO B, Sintonía). Cada uno muestra 9 dígitos ámbar con separadores de miles. Una fila de botones selectores LO A/B se sitúa entre las pantallas; el estado SPLIT muestra etiquetas TX/RX junto a los LOs activos. Un botón **M** junto a cada fila abre el diálogo de memoria de frecuencia para esa fila.

**Fila INTERCAMBIAR / BLOQUEAR / BW** — inmediatamente debajo de los botones selectores LO:
- **INTERCAMBIAR** — intercambia las frecuencias LO A y LO B con un clic.
- **BLOQUEAR** — alterna un bloqueo de frecuencia en el LO activo. Cuando está bloqueado, la pantalla de frecuencia y el botón **M** de ese LO se deshabilitan para prevenir un cambio de frecuencia accidental. Con SPLIT activo, BLOQUEAR se aplica a LO A y LO B simultáneamente.
- **◄ / ►** — desplazan el LO activo hacia abajo o arriba por el ancho de banda seleccionado actualmente.
- **Combobox de ancho de banda** — lista desplegable poblada desde `bandwidth_map[modo_actual]`; seleccionar un valor envía `set_selected_bw` al servidor.

**Botones de banda** — 11 bandas ITU Región 2 (160 m – 6 m). Al hacer clic sintoniza el LO al centro de la banda. Los botones fuera de las `allowed_bands` del dispositivo (o la restricción de la antena seleccionada) aparecen en gris automáticamente.

**Volumen / Umbral AGC / Ganancia RF / Squelch** — cuatro controles deslizantes horizontales con etiquetas.

**Dispositivo / Tasa de muestreo / Tarjeta de sonido** — botones que abren diálogos de selección modal.

**Potencia** — botón de nivel de potencia TX; mostrado solo cuando el servidor reporta `power_levels` para el dispositivo actual. Abre un diálogo de selección de nivel; el nivel elegido se envía como `set_power`.

**Botones de modo** — modos de modulación estándar (LSB, USB, AM, FM, CW, …) más hasta 10 modos de modulación de usuario definidos por el servidor.

**Alternancias DSP** — NB, NR, AGC, Filtro, AFC, ANF, Notch, Silencio — cada uno un botón de dos estados con resaltado verde cuando está activo.

**Barra de transporte** — Grabar ●, Reproducir ▶, Pausa ⏸, Detener ■, Rebobinar ◀◀, Avance rápido ▶▶, Bucle ∞.

**Botón Iniciar** — activa/desactiva el SDR. El texto cambia a "Detener" mientras se ejecuta.

**Filas de botones definidos por el usuario** — 14 botones en dos filas de 7. Las etiquetas y tipos provienen del servidor; los botones sin etiqueta se ocultan.

**Botones RF de usuario** — 11 botones mostrados sobre los botones de banda en el panel RF, a la izquierda del arreglo de bandas. Una **pulsación larga (≥ 3 segundos)** en cualquier botón abre un diálogo de configuración en tiempo de ejecución. Los widgets del diálogo se definen en la clave `config_N` del perfil de dispositivo para ese botón (ver `cat_device.toml` arriba); los valores enviados en el diálogo se envían como `rf_usr_btn_config_set` y se persisten en `.gui_state.json`.

**Fecha/hora + controles de conexión** — reloj UTC (verde); campos de host/puerto y un botón Conectar con un LED de estado. En modo de autoconexión, toda la fila está oculta.

### Cascada AF, Espectro y Panel de Texto

La mitad derecha de la fila inferior es el panel de Frecuencia de Audio, impulsado íntegramente desde el audio RTP decodificado localmente (no calculado por el servidor):

- **Cascada AF** — mismo motor `WFCanvas`; muestra contenido de frecuencia de audio 0–3000 Hz en desplazamiento en tiempo real
- **Espectro AF** — mismo motor `SpecCanvas`; rango 0–3000 Hz, sin superposición de filtro (AF no tiene pasabanda arrastrable)
- **Barra de herramientas AF** — mismos controles que la barra RF (Escala, Ave, Velocidad, alternancia Cascada/Espectro)
- **Panel de Texto/RTTY** — cuando se selecciona un modo de usuario `text` o `text_input`, el cuadro AF se divide horizontalmente. El lado derecho muestra una pantalla de texto de solo lectura (mensajes enviados por el servidor) y, para modos `text_input`, una caja de entrada editable de 3 líneas que envía su contenido como `user_text` cuando el operador presiona Enter. Cada ranura de modo de usuario tiene su propio historial de texto independiente.

---

## Sistema de Audio

El `RTPAudioClient` de la GUI gestiona el canal de audio UDP:

- **Recepción (PTT DESACTIVADO):** El servidor envía un paquete RTP/PCMU cada 20 ms. La GUI decodifica μ-law a PCM de 16 bits y escribe en un stream de salida PyAudio (altavoz) a través de un buffer de anillo deque y un callback de PyAudio.
- **Transmisión (PTT ACTIVADO):** La GUI abre un stream de entrada PyAudio (micrófono), lee tramas PCM de 160 muestras, codifica a μ-law, empaqueta en RTP y envía datagramas UDP al servidor.
- **Alimentación del espectro AF:** Las muestras PCM decodificadas se acumulan en un buffer de anillo continuo; un hilo de trabajo en segundo plano ejecuta una FFT cada ~50 ms y publica el resultado en la cola de eventos Tk de la GUI para su visualización en la cascada/espectro AF.
- El codec μ-law usa tablas de búsqueda precomputadas de 256 entradas para decodificación y 65536 entradas para codificación (construidas una vez al importar) para un hot path sin ramas ni structs en cada trama de audio.
- Selección de tarjeta de sonido (micrófono y altavoz independientemente) a través del diálogo de Tarjeta de Sonido o los flags `--audio-mic` / `--audio-speaker`; `--audio-list` imprime todos los índices de dispositivos disponibles.

---

## Reproducción de WAV IQ y Audio (Servidor)

### `--iq_wav RUTA`

Impulsa el espectro y la cascada RF desde una grabación IQ real en lugar del generador de señales sintéticas. Acepta archivos WAV estéreo estilo SDRplay donde el canal izquierdo es I y el canal derecho es Q, en cualquier profundidad PCM entera o flotante (8/16/32 bits). Si el archivo contiene un chunk `auxi`, la frecuencia central grabada se extrae y se usa para inicializar la frecuencia sintonizada inicial.

El archivo se repite indefinidamente (reproducción en bucle). Una FFT IQ (`IQ_FFT_SIZE = 4096` bins, ventana Hanning, fftshift) convierte cada bloque a un espectro de potencia aproximado en dBm; el nivel de zoom entonces recorta y remuestrea el resultado de ancho de banda completo al ancho de visualización de la GUI.

Requiere `numpy`.

### `--audio_wav RUTA`

Reemplaza el tono de demostración de 440 Hz incorporado con un archivo WAV real (PCM/float mono o estéreo a cualquier tasa de muestreo). El estéreo se mezcla a mono; el audio se remuestrea a 8 kHz si su tasa nativa difiere. El archivo se repite indefinidamente como el stream de audio de recepción simulado entregado a la GUI.

---

## Memorias de Frecuencia

Cada perfil de dispositivo tiene su propio conjunto independiente de memorias: 20 ranuras para cada una de tres posiciones de frecuencia (LO A, LO B, Sintonía) = 60 ranuras por dispositivo.

Abrir el diálogo de memoria (haciendo clic en un botón **M** junto a una pantalla de frecuencia) envía `get_memories` al servidor. El servidor devuelve las 20 ranuras para esa posición desde el archivo de memoria del dispositivo activo. El operador puede:

- **Recordar** una ranura de memoria — envía `set_freq` (o equivalente) y cierra el diálogo
- **Guardar** la frecuencia actual en una ranura — abre un diálogo de entrada de etiqueta, luego envía `save_memory`
- **Editar** la etiqueta de una ranura en el lugar

Las memorias se escriben en disco inmediatamente cada vez que se guarda una ranura; sobreviven a los reinicios del servidor y cambios de dispositivo.

---

## Perfiles de Dispositivo y Cambio entre Dispositivos

Se pueden definir hasta 20 perfiles de dispositivo en la sección `[devices]` de `cat_server.toml`. Cada entrada empareja una etiqueta de visualización con una ruta a un archivo de configuración compatible con `cat_device.toml`.

Cuando el operador hace clic en el botón **Dispositivo**, la GUI envía `get_devices`; el servidor responde con un diálogo de lista. Seleccionar un dispositivo envía `select_device`:

1. El servidor guarda el estado de GUI del dispositivo actual (frecuencias, modo, filtro, ganancias, alternancias, etc.) en su archivo `.gui_state.json`.
2. El archivo tipo `cat_device.toml` del nuevo dispositivo se carga; los botones de usuario, botones de modulación, botones RF, tasas de muestreo, restricciones de banda y puertos de antena se reemplazan.
3. El `.gui_state.json` del nuevo dispositivo se restaura (frecuencias, modo, alternancias, etc.).
4. El `.memories.json` del nuevo dispositivo se carga.
5. Se envía un mensaje `reload_state`; la GUI resincroniza todos los widgets.

Al inicio, si hay una lista `[devices]` configurada y no se pasó `--device-config` explícitamente, el servidor selecciona automáticamente el dispositivo 1 para que su archivo de estado persistido se use desde la primera conexión (evitando un conflicto de identidad "fantasma" en la primera conexión).

---

## HiDPI / Escalado

Todas las constantes de geometría se definen en un diccionario `BASE` a escala 1.0. El factor de escala efectivo es `1.25 ^ nivel_de_escala`. El nivel 0 apunta a una pantalla de 1280×720; la lógica de detección automática elige el nivel más grande cuyo tamaño de ventana predeterminado (1520×870 en el nivel 0) cabe en el 90% de la pantalla:

| Nivel de Escala | Factor | Resolución Objetivo |
|:---------------:|:------:|:-------------------:|
| −5 | 0,33× | pantallas muy pequeñas |
| −4 | 0,41× | — |
| −3 | 0,51× | — |
| −2 | 0,64× | — |
| −1 | 0,80× | < 1280×720 |
| 0 | 1,00× | 1280×720 |
| 1 | 1,25× | 1920×1080 |
| 2 | 1,56× | 2560×1440 |
| 3 | 1,95× | — |
| 4 | 2,44× | 3840×2160 |
| 5 | 3,05× | — |

Los botones de escala `+` / `−` en la esquina superior derecha de la ventana incrementan/decrementan el nivel en tiempo de ejecución; todos los tamaños de fuentes, widgets, rellenos y geometría del canvas se recalculan inmediatamente. La superposición de escala muestra el nivel actual y se desvanece después de unos segundos.

El motor de diseño asegura que el panel de control inferior (fila del S-meter hasta la fila de fecha/hora) sea **siempre completamente visible** a cualquier altura de ventana: solo la cascada/espectro RF de arriba se reduce para acomodar el panel inferior.

---

## Temas y Fuentes

### Paleta de Colores

El tema oscuro predeterminado usa una combinación de colores azul marino/verde azulado oscuro:

| Rol | Hex | Descripción |
|-----|-----|-------------|
| Fondo de ventana / cascada | `#020814` | Azul oscuro profundo |
| Panel de control | `#0c1525` | Azul marino oscuro |
| Fondo del espectro | `#010610` | Azul marino casi negro |
| Traza del espectro | `#22cc44` | Verde |
| Cursor VFO | `#ff2828` | Rojo |
| Dígitos de frecuencia | `#ffb800` | Ámbar |
| Botón activo | `#1a3c6a` / `#50c0ff` | Azul |
| Barra S-meter | `#28ee50` → `#ff3830` | Verde → rojo |
| Pico sostenido | `#e0e8ff` | Azul-blanco |

El flag `--bg light` o `bg = "light"` en `cat_gui.toml` reemplaza todas las superficies de fondo con `#FFECD6` (crema cálida), convirtiendo el ámbar de los dígitos de frecuencia a naranja oscuro para mayor legibilidad.

### Fuentes Personalizadas

Se pueden configurar dos rutas de fuentes independientes:

- `--freq-font RUTA` — usada exclusivamente para las pantallas de dígitos de frecuencia LO A, LO B y Sintonía
- `--gui-font RUTA` — propagada a todas las fuentes de sistema con nombre de Tk (`TkDefaultFont`, `TkTextFont`, etc.) para que cada widget la adopte automáticamente

La carga de fuentes (TTF/OTF) funciona sin derechos de administrador en Linux, macOS y Windows:

- **Linux:** copia la fuente a `~/.local/share/fonts/`, ejecuta `fc-cache`, luego llama a `FcConfigAppFontAddFile()` en el handle de fontconfig del proceso en curso para que Tk vea la familia inmediatamente
- **macOS:** copia a `~/Library/Fonts/`, luego llama a `CTFontManagerRegisterFontsForURL` con alcance al proceso actual
- **Windows:** llama a `AddFontResourceExW` con `FR_PRIVATE | FR_NOT_ENUM` (no requiere derechos de administrador)

El nombre de familia PostScript se resuelve con fonttools (preferido), luego `fc-query`, luego una heurística basada en el nombre del archivo.

---

## Referencia de Archivos Generados

| Archivo | Creado Por | Contenido |
|---------|-----------|-----------|
| `cat_gui.toml` | GUI en la primera ejecución | Configuración de pantalla, conexión y audio de la GUI |
| `cat_server.toml.example` | Servidor en la primera ejecución (si `cat_server.toml` está ausente) | Plantilla anotada — copiar a `cat_server.toml` para personalizar |
| `cat_device.toml.example` | Servidor en la primera ejecución (si `cat_device.toml` está ausente) | Plantilla anotada — copiar a `cat_device.toml` para personalizar |
| `<dispositivo>.gui_state.json` | Operador (debe crearse manualmente) | Configuración persistida del operador por dispositivo; el servidor guarda en él pero nunca lo crea |
| `<dispositivo>.memories.json` | Servidor en el primer guardado de memoria | Memorias de frecuencia 3×20 por dispositivo |
| `<dispositivo>.gui_state.json.example` | Servidor en la primera ejecución | Archivo gui_state de ejemplo como referencia / punto de partida |
| `<dispositivo>.memories.json.example` | Servidor en la primera ejecución | Archivo de memorias de ejemplo como referencia / punto de partida |

> **Creación de archivos de configuración:** Cuando `cat_server.toml` o `cat_device.toml` están ausentes, el servidor escribe un archivo compañero `<nombre>.toml.example` y se ejecuta con los valores predeterminados incorporados para esa sesión. El archivo `.toml` real **nunca** se crea automáticamente; el operador debe copiar o renombrar el archivo `.example` para activar la configuración personalizada.

> **Archivos gui_state:** El servidor guarda en `<dispositivo>.gui_state.json` pero nunca lo creará si no existe. Una versión `.example` se escribe en la primera ejecución como referencia. El operador debe crear el archivo real (p.ej. copiando el ejemplo) para que el estado por dispositivo persista entre reinicios.

Todos los archivos `.toml` son autocorrectivos: las claves faltantes se añaden con su valor predeterminado y el archivo se reescribe en su lugar.

---

## Extender el Servidor

El servidor de referencia está estructurado para que la capa de generación de señales sea fácil de reemplazar:

- **`RadioState.apply(cmd)`** — procesa cada comando de la GUI. Agregue nuevos comandos aquí.
- **`ClientHandler._stream_loop()`** — llama a `RadioState.as_dict()` y construye la trama `data` saliente a 10 Hz. Reemplace la lista sintética de `Signal` con muestras SDR reales para obtener un espectro en vivo.
- **`UDPAudioChannel._tx_loop()`** — envía tramas RTP μ-law desde `AudioWavSource.read_frame()` o `_gen_sine_frame()`. Conecte un demodulador SDR real aquí para entregar audio de recepción real.
- **`UDPAudioChannel._rx_loop()`** — recibe RTP μ-law de la GUI durante PTT. El PCM decodificado se descarta actualmente; enrútelo a su camino de transmisión SDR aquí.
- **`IQWavSource`** — un lector de WAV IQ completo y autónomo con bucle y salida FFT. Envuelva una API SDR real (SoapySDR, bindings Python de RTL-SDR, etc.) en la misma interfaz (`read_block(n)` → array numpy complejo) para alimentar muestras IQ en vivo a `_iq_fft_spectrum_db()`.

El protocolo JSON es intencionalmente simple: cualquier lenguaje o framework que pueda abrir un socket TCP y escribir JSON terminado en salto de línea puede controlar la GUI.

> **Validación de `[bandwidth]`:** El servidor realiza una **verificación fatal** (`sys.exit(1)`) al inicio si alguna etiqueta definida en `[user_mods]` carece de una entrada coincidente en la sección `[bandwidth]` de la configuración del dispositivo activo. Agregue siempre una entrada `[bandwidth]` para cada modo de modulación personalizado que defina, o el servidor se negará a iniciar.

# Mapa Hamlib

`cat_gui.py` utiliza un **protocolo JSON personalizado sobre TCP** (objetos JSON delimitados por nueva línea) que se comunica con un backend Python propietario (`cat_server.py`). El `rigctld` de Hamlib utiliza un **protocolo de comandos de texto** (tokens de un solo carácter o `\long_name value\n` sobre el puerto TCP 4532). Los dos protocolos son arquitectónicamente diferentes en varios aspectos clave:

## 1. Resumen

| Dimensión | Protocolo Personalizado cat_gui.py | Hamlib rigctld |
|---|---|---|
| **Formato de transmisión** | Objetos JSON, delimitados por nueva línea | Tokens de texto plano, separados por espacios, terminados con `\n` |
| **Transporte** | TCP (puerto configurable) + UDP RTP audio | Solo TCP (4532 por defecto) |
| **Modelo Push** | El servidor **envía** espectro/estado continuamente | El cliente **consulta** cada `get_*` |
| **Audio** | Flujo de audio RTP/G.711 µ-law integrado | Sin audio — solo radio |
| **Sincronización de estado** | `resp:ok` + `reload_state` envía estado completo | El cliente lee cada parámetro individualmente |
| **Tokens de Modo** | Etiquetas arbitrarias definidas por el servidor (hasta 10 ranuras) | Conjunto fijo: USB, LSB, CW, FM, AM, RTTY… |
| **Memoria** | Objeto JSON con freq/modo/etiqueta | Utilidad `rigmem`; canal de comandos CAT |

## 2. Comandos Salientes (`net.send`) → Equivalentes en Hamlib

Comandos enviados **desde la GUI al servidor**.

| # | `cmd` de cat_gui.py | Parámetros | Equivalente en Hamlib | Hamlib Corto/Largo | Estado |
|---|---|---|---|---|---|
| 1 | `hello` | — | *(handshake — sin equivalente directo)* | `\dump_caps` (más cercano: consulta de capacidades) | ⚠️ **Diferente** — Hamlib no tiene hello de sesión; `dump_caps` es lo más cercano |
| 2 | `start` | — | *(sin equivalente — inicio/parada de streaming específico de SDR)* | — | ❌ **Ausente en Hamlib** |
| 3 | `stop` | — | *(sin equivalente)* | — | ❌ **Ausente en Hamlib** |
| 4 | `set_lo_a_freq` | `hz` (int) | `set_freq` en VFOA | `F` / `\set_freq` | ⚠️ **Diferente** — Hamlib establece freq de VFO; cat_gui usa "LO A" (concepto de oscilador local SDR) |
| 5 | `set_lo_b_freq` | `hz` (int) | `set_freq` en VFOB | `F` / `\set_freq` (con VFO=VFOB) | ⚠️ **Diferente** — requiere selección explícita de VFO en Hamlib |
| 6 | `set_lo` | `lo` ("A"\|"B") | `set_vfo` | `V` / `\set_vfo` | ✅ **Mapea** — Selección de VFO A/B |
| 7 | `set_tune_freq` | `hz` (int) | *(sin equivalente directo — concepto de offset IF/tune)* | RIT/XIT `J`/`Z` (parcial) | ⚠️ **Diferente** — RIT/XIT de Hamlib es offset relativo; tune_freq es absoluto |
| 8 | `set_mode` | `mode` (string) | `set_mode` | `M` / `\set_mode` | ⚠️ **Diferente** — Hamlib usa conjunto fijo de tokens; cat_gui usa etiquetas arbitrarias definidas por servidor |
| 9 | `set_filter` | `lo`, `hi` (Hz) | passband de `set_mode` | `M` / `\set_mode` (2do arg) | ⚠️ **Diferente** — Hamlib establece passband como entero de ancho único; cat_gui usa par lo/hi |
| 10 | `set_ptt` | `enabled` (bool), `udp_port` (int) | `set_ptt` | `T` / `\set_ptt` | ⚠️ **Diferente** — Valores PTT de Hamlib: 0=RX,1=TX,2=TX-mic,3=TX-data; cat_gui usa bool + puerto UDP RTP |
| 11 | `set_split` | `enabled` (bool) | `set_split_vfo` | `S` / `\set_split_vfo` | ⚠️ **Diferente** — Hamlib también requiere token TX VFO; cat_gui usa bool simple |
| 12 | `set_volume` | `value` (float 0–100) | `set_level AF` | `L AF` / `\set_level AF` | ✅ **Mapea** — Nivel AF |
| 13 | `set_rf_gain` | `value` (float dB) | `set_level RF` | `L RF` / `\set_level RF` | ✅ **Mapea** — Nivel de ganancia RF |
| 14 | `set_squelch` | `value` (float dBm) | `set_level SQL` | `L SQL` / `\set_level SQL` | ✅ **Mapea** — Nivel de squelch |
| 15 | `set_agc_thresh` | `value` (float dB) | `set_level AGC` | `L AGC` / `\set_level AGC` | ⚠️ **Diferente** — AGC de Hamlib es enum (OFF/SLOW/MEDIUM/FAST/AUTO); cat_gui usa umbral float en dB |
| 16 | `set_zoom` | `value` (int) | *(sin equivalente — zoom de espectro SDR)* | — | ❌ **Ausente en Hamlib** |
| 17 | `set_selected_bw` | `value` (int Hz) | passband de `set_mode` | `M` / `\set_mode` | ⚠️ **Diferente** — Hamlib fusiona modo+BW en un comando |
| 18 | `set_spec_ref` | `box`, `value` (dB) | *(sin equivalente — parámetro de visualización)* | — | ❌ **Ausente en Hamlib** |
| 19 | `set_spec_ave` | `box`, `value` (int) | *(sin equivalente — parámetro de visualización)* | — | ❌ **Ausente en Hamlib** |
| 20 | `ui_display` | `box`, `view` | *(sin equivalente — comando de capa GUI)* | — | ❌ **Ausente en Hamlib** |
| 21 | `transport` | `action` (rec/play/pause/stop/rw/ff/infinite) | *(sin equivalente — transporte de medios)* | — | ❌ **Ausente en Hamlib** |
| 22 | `get_devices` | — | *(sin equivalente — enumeración de dispositivos)* | `\dump_caps` (parcial) | ❌ **Ausente en Hamlib** |
| 23 | `select_device` | `index` (int) | *(sin equivalente — cambio de dispositivo)* | `-m model` solo CLI | ❌ **Ausente en Hamlib** (bandera CLI, no comando en tiempo de ejecución) |
| 24 | `get_sample_rates` | — | *(sin equivalente — específico de SDR)* | — | ❌ **Ausente en Hamlib** |
| 25 | `set_sample_rate` | `value` (int Hz) | *(sin equivalente — específico de SDR)* | — | ❌ **Ausente en Hamlib** |
| 26 | `get_antennas` | — | `get_ant` | `y` / `\get_ant` | ⚠️ **Diferente** — Hamlib retorna número de antena; cat_gui solicita lista de puertos etiquetados |
| 27 | `select_antenna` | `index` (int, 1-based) | `set_ant` | `Y` / `\set_ant` | ✅ **Mapea** — selección de antena por índice |
| 28 | `get_power_levels` | — | `get_level RFPOWER` | `l RFPOWER` / `\get_level RFPOWER` | ⚠️ **Diferente** — Hamlib retorna escalar; cat_gui solicita lista de presets nombrados |
| 29 | `set_power` | `index` (int) | `set_level RFPOWER` | `L RFPOWER` / `\set_level RFPOWER` | ⚠️ **Diferente** — Hamlib usa float 0.0–1.0; cat_gui usa índice de preset |
| 30 | `user_button` | `index`, opcional `enabled` / `choice` | `set_func` | `U` / `\set_func` | ⚠️ **Diferente** — Hamlib tiene tokens de función fijos; cat_gui soporta botones arbitrarios definidos por servidor |
| 31 | `user_text` | `index`, `text` (string) | `send_morse` (b) — análogo más cercano | `b` / `\send_morse` | ⚠️ **Diferente** — Hamlib envía Morse; cat_gui envía texto libre para entrada de modo digital |
| 32 | `rf_usr_button` | `index`, opcional `enabled` | `set_func` | `U` / `\set_func` | ⚠️ **Diferente** — igual que `user_button` — Hamlib no tiene concepto de botón personalizado en dominio RF |
| 33 | `rf_usr_btn_config_set` | `index`, `values` (dict) | *(sin equivalente)* | — | ❌ **Ausente en Hamlib** |
| 34 | `get_memories` | `position` (int) | `get_mem` (lectura de memoria de canal) | `\get_mem` | ⚠️ **Diferente** — Hamlib lee un canal a la vez; cat_gui retorna lista desde una posición |
| 35 | `save_memory` | `position`, `freq`, `mode`, `label` | `set_mem` / `set_channel` | `\set_mem` / `\set_channel` | ⚠️ **Diferente** — memoria de Hamlib no tiene campo de etiqueta de usuario en el protocolo |
| 36 | `audio_hello` | `udp_port` (int) | *(sin equivalente — configuración de canal audio RTP)* | — | ❌ **Ausente en Hamlib** |

## 3. Mensajes Entrantes (Servidor → GUI) → Equivalentes en Hamlib

Mensajes **recibidos por la GUI** del servidor y procesados en `_handle()`.

| # | `type` de cat_gui.py | Campos Clave del Payload | Equivalente en Hamlib | Estado |
|---|---|---|---|---|
| 1 | `data` | `f_start`, `f_stop`, `spectrum[]`, `smeter_dbm`, `smeter_text`, `swr` | *(sin equivalente — push continuo de SDR)* | ❌ **Sin análogo en Hamlib** — Hamlib usa polling `get_level STRENGTH`; sin push de espectro |
| 2 | `af_local` | `af_spectrum[]`, `af_range` | *(sin equivalente — FFT AF calculado localmente)* | ❌ **Sin análogo en Hamlib** |
| 3 | `reload_state` | Dict de estado completo (todos los parámetros) | *(sin equivalente — push de estado completo)* | ❌ **Sin análogo en Hamlib** — Hamlib requiere polls individuales `get_*` |
| 4 | `resp:ok` (vía clave `"state"`) | Dict de estado fusionado | `RPRT 0` (solo acuse de recibo de éxito) | ⚠️ **Diferente** — Hamlib retorna `RPRT 0`; cat_gui adjunta estado completo al acuse |
| 5 | `audio_port` | `port` (UDP int), `sample_rate`, `frame_ms` | *(sin equivalente)* | ❌ **Ausente en Hamlib** |
| 6 | `disconnected` | `reason` opcional | `RPRT -1` (respuesta de error) | ⚠️ **Diferente** — Error de Hamlib es por comando; desconexión de cat_gui es evento asíncrono |
| 7 | `device_list` | `devices[]` | *(sin equivalente)* | ❌ **Ausente en Hamlib** |
| 8 | `sample_rate_list` | `rates[]`, `current` | *(sin equivalente)* | ❌ **Ausente en Hamlib** |
| 9 | `antenna_list` | `antennas[]`, `current`, `device_allowed_bands` | Respuesta `get_ant` (solo escalar) | ⚠️ **Diferente** — Hamlib retorna número único de antena; cat_gui retorna lista completa etiquetada con restricciones de banda |
| 10 | `power_level_list` | `levels[]`, `current` | `get_level RFPOWER` (escalar) | ⚠️ **Diferente** — cat_gui entrega lista de presets nombrados |
| 11 | `memory_list` | `memories[]` | `get_mem` (un canal) | ⚠️ **Diferente** — Hamlib lee un canal; cat_gui envía página de entradas etiquetadas |
| 12 | `user_text` | `index`, `text` | *(sin equivalente)* | ❌ **Ausente en Hamlib** |

## 4. Variables de Estado → Mapeo de Nivel/Func/Parámetro de Hamlib

Pares clave-valor almacenados en `self.state` (poblados desde JSON empujado por el servidor).

| # | Clave de Estado cat_gui.py | Tipo | Descripción | Equivalente en Hamlib | Comando Hamlib | Estado |
|---|---|---|---|---|---|---|
| 1 | `lo_freq` | int Hz | Frecuencia LO A (VFO principal) | Frecuencia VFOA | `f` / `\get_freq` | ✅ **Mapea** |
| 2 | `lo_b_freq` | int Hz | Frecuencia LO B (segundo VFO) | Frecuencia VFOB | `f` (con VFO=VFOB) | ✅ **Mapea** |
| 3 | `tune_freq` | int Hz | Frecuencia IF/tune (absoluta) | RIT (`j`) o XIT (`z`) — solo relativo | ⚠️ **Diferente** — RIT/XIT de Hamlib es offset; esto es absoluto |
| 4 | `lo_active` | "A"\|"B" | Qué LO/VFO está activo | VFO actual | `v` / `\get_vfo` | ✅ **Mapea** |
| 5 | `mode` | string | Etiqueta de modo de modulación actual | Token de modo | `m` / `\get_mode` | ⚠️ **Diferente** — modo de cat_gui es string arbitrario del servidor; Hamlib usa enum fijo |
| 6 | `filter_lo` / `filter_hi` | int Hz | Bordes inferior/superior del passband IF | Passband (entero de ancho único) | `m` / `\get_mode` (2do valor) | ⚠️ **Diferente** — passband de Hamlib es ancho; cat_gui usa par absoluto lo/hi |
| 7 | `ptt` | bool | Estado Push-to-talk | Estado PTT | `t` / `\get_ptt` | ✅ **Mapea** |
| 8 | `split` | bool | Split TX/RX habilitado | Split VFO | `s` / `\get_split_vfo` | ✅ **Mapea** |
| 9 | `volume` | float 0–100 | Volumen de salida de audio | Nivel AF | `l AF` / `\get_level AF` | ✅ **Mapea** |
| 10 | `rf_gain` | float dB | Ganancia RF | Nivel RF | `l RF` / `\get_level RF` | ✅ **Mapea** |
| 11 | `squelch` | float dBm | Umbral de squelch | Nivel SQL | `l SQL` / `\get_level SQL` | ✅ **Mapea** |
| 12 | `agc_thresh` | float dB | Umbral AGC | Nivel AGC | `l AGC` / `\get_level AGC` | ⚠️ **Diferente** — AGC de Hamlib es enum, no umbral |
| 13 | `sample_rate` | int Hz | Tasa de muestreo SDR | *(sin equivalente)* | — | ❌ **Ausente en Hamlib** |
| 14 | `zoom` | int | Nivel de zoom del espectro | *(sin equivalente)* | — | ❌ **Ausente en Hamlib** |
| 15 | `running` | bool | Streaming SDR activo | *(sin equivalente)* | — | ❌ **Ausente en Hamlib** |
| 16 | `user_mod_labels` | list[str] | Etiquetas de botones de modo definidas por servidor | Tokens de modo | `m` / `\get_mode` | ⚠️ **Diferente** — fijo vs. dinámico |
| 17 | `user_mod_types` | list[str] | Tipo de modo (normal/text/text_input) | *(sin equivalente)* | — | ❌ **Ausente en Hamlib** |
| 18 | `user_buttons` | list[dict] | Botones auxiliares definidos por servidor | Tokens `set_func` / `get_func` | `U` / `u` | ⚠️ **Diferente** — Hamlib tiene conjunto fijo de funciones |
| 19 | `user_btn_state` | list[bool] | Estado de toggle por botón de usuario | `get_func` | `u` / `\get_func` | ⚠️ **Parcial** |
| 20 | `user_btn_list_sel` | list[int] | Selecciones de botones de tipo lista | *(sin equivalente)* | — | ❌ **Ausente en Hamlib** |
| 21 | `rf_usr_btns` | list[dict] | Botones de usuario en dominio RF | `set_func` / `get_func` | `U` / `u` | ⚠️ **Diferente** — igual que user_buttons |
| 22 | `rf_usr_btn_state` | list[bool] | Estados de toggle de botones RF | `get_func` | `u` | ⚠️ **Parcial** |
| 23 | `rf_usr_btn_config_vals` | dict | Valores de parámetros de configuración por botón | *(sin equivalente)* | — | ❌ **Ausente en Hamlib** |
| 24 | `antenna_index` | int (1-based) | Antena seleccionada actualmente | Número de antena | `y` / `\get_ant` | ✅ **Mapea** |
| 25 | `antenna_labels` | list[str] | Etiquetas de puertos de antena nombrados | *(no en protocolo Hamlib)* | — | ❌ **Ausente en Hamlib** |
| 26 | `antenna_allowed_bands` | list[list[str]] | Restricciones de banda por antena | *(sin equivalente)* | — | ❌ **Ausente en Hamlib** |
| 27 | `allowed_bands` | list[str] | Bandas de radioaficionado permitidas activas | *(sin equivalente)* | — | ❌ **Ausente en Hamlib** |
| 28 | `power_index` | int | Índice de preset de potencia TX seleccionado | Nivel RFPOWER (float 0–1) | `l RFPOWER` | ⚠️ **Diferente** — índice vs. float |
| 29 | `power_levels` | list | Presets de potencia TX nombrados | *(sin equivalente como lista)* | — | ❌ **Ausente en Hamlib** |
| 30 | `selected_bw` | int Hz | Selector de BW (tamaño de paso) | Passband | `m` / `\get_mode` | ⚠️ **Parcial** |
| 31 | `bandwidth_map` | dict | Mapa de presets de BW | *(sin equivalente)* | — | ❌ **Ausente en Hamlib** |
| 32 | `active_device_index` | int | Dispositivo SDR activo actualmente | *(sin equivalente — específico de SDR)* | — | ❌ **Ausente en Hamlib** |
| 33 | `spec_ref_rf` / `spec_ref_af` | float dB | Nivel de referencia del espectro | *(sin equivalente)* | — | ❌ **Ausente en Hamlib** |
| 34 | `spec_ave_rf` / `spec_ave_af` | int | Conteo de promediador de espectro | *(sin equivalente)* | — | ❌ **Ausente en Hamlib** |
| 35 | `toolbar_view_rf` / `toolbar_view_af` | string | Modo de visualización (Waterfall/Spectrum) | *(sin equivalente)* | — | ❌ **Ausente en Hamlib** |

## 5. Funciones de Hamlib NO Presentes en cat_gui.py

Comandos estándar de Hamlib/rigctld que **no tienen contraparte** en el protocolo de cat_gui.py.

| # | Comando Hamlib | Corto | Descripción | Notas |
|---|---|---|---|---|
| 1 | `set_rit` / `get_rit` | `J` / `j` | Receiver Incremental Tuning (offset Hz) | cat_gui usa `tune_freq` absoluto; RIT requeriría conversión |
| 2 | `set_xit` / `get_xit` | `Z` / `z` | Transmitter Incremental Tuning | Igual que nota de RIT |
| 3 | `set_ts` / `get_ts` | `N` / `n` | Tamaño de paso de sintonía en Hz | Sin concepto de paso en cat_gui (usa paso BW personalizado) |
| 4 | `set_rptr_shift` / `get_rptr_shift` | `R` / `r` | Repeater shift (operaciones FM) | No relevante para app enfocada en SDR |
| 5 | `set_rptr_offs` / `get_rptr_offs` | `O` / `o` | Offset de repeater en Hz | Igual que arriba |
| 6 | `set_ctcss_tone` / `get_ctcss_tone` | `C` / `c` | Tono CTCSS (décimas de Hz) | Sub-tono FM — no soportado |
| 7 | `set_dcs_code` / `get_dcs_code` | `D` / `d` | Código DCS | No soportado |
| 8 | `set_ctcss_sql` / `get_ctcss_sql` | `0x90` / `0x91` | Tono de squelch CTCSS | No soportado |
| 9 | `set_func NB` / `get_func NB` | `U NB` / `u NB` | Noise Blanker on/off | cat_gui no tiene toggle NB visible en protocolo (puede estar en user_button) |
| 10 | `set_func COMP` | `U COMP` | Compresor de voz | No soportado |
| 11 | `set_func VOX` | `U VOX` | TX activado por voz | No soportado |
| 12 | `set_func TONE` / `TSQL` | `U TONE` | Squelch de tono CTCSS | No soportado |
| 13 | `set_func LOCK` | `U LOCK` | Bloqueo VFO | cat_gui implementa bloqueo de frecuencia solo en cliente (sin cmd servidor) |
| 14 | `set_func AFC` | `U AFC` | Control Automático de Frecuencia | Puede estar en user_button; no en protocolo explícito |
| 15 | `set_func ANF` | `U ANF` | Filtro Notch Automático | Puede estar en user_button |
| 16 | `set_func NR` | `U NR` | Reducción de Ruido | Puede estar en user_button |
| 17 | `set_level PREAMP` | `L PREAMP` | Nivel de preamplificador | No en protocolo explícito |
| 18 | `set_level ATT` | `L ATT` | Configuración de atenuador | No en protocolo explícito |
| 19 | `set_level MICGAIN` | `L MICGAIN` | Ganancia de micrófono | No en protocolo explícito |
| 20 | `set_level KEYSPD` | `L KEYSPD` | Velocidad de keyer CW (WPM) | No soportado |
| 21 | `set_level NOTCHF` | `L NOTCHF` | Frecuencia de notch manual | Puede estar en user_button/config |
| 22 | `send_morse` | `b` | Enviar cadena de código Morse | No soportado |
| 23 | `get_dcd` | `0x8b` | Detección de Portadora de Datos / squelch abierto | No en protocolo explícito |
| 24 | `dump_caps` | `\dump_caps` | Volcar todas las capacidades del rig | Cubierto parcialmente por `get_devices` + `reload_state` |
| 25 | `set_lock_mode` | *(solo rigctld)* | Prevenir cambios de modo desde otros clientes | No necesario (diseño de un solo cliente) |

## 6. Resumen de Diferencias Arquitectónicas

```
Protocolo personalizado cat_gui.py          Hamlib rigctld
─────────────────────────────────           ──────────────────────────────────
JSON {cmd, ...} → servidor                  \command value\n → rigctld
servidor empuja espectro/estado             cliente consulta cada parámetro
Audio RTP UDP integrado                     Sin canal de audio
Handshake de sesión (hello)                 Command/response sin estado
Etiquetas dinámicas de modo/botones         Conjunto fijo de tokens modo/func
Conceptos SDR (LO, zoom, sample_rate)       Conceptos de Rig (VFO, RIT, CTCSS)
Cambio de dispositivo en tiempo de ejecución Model seleccionado al inicio (-m)
Restricción de banda (allowed_bands)        Sin restricción de banda en protocolo
Config persistente por dispositivo          Config backend solo al inicio (--set-conf)
```

## 7. Resumen de Cobertura de Mapeo

| Categoría | Total ítems cat_gui | ✅ Mapeo Directo | ⚠️ Parcial/Diferente | ❌ Sin Equivalente en Hamlib |
|---|---|---|---|---|
| Comandos Salientes | 36 | 4 (11%) | 16 (44%) | 16 (45%) |
| Mensajes Entrantes | 12 | 0 (0%) | 5 (42%) | 7 (58%) |
| Variables de Estado | 35 | 8 (23%) | 9 (26%) | 18 (51%) |
| **Totales** | **83** | **12 (14%)** | **30 (36%)** | **41 (49%)** |
