# Digital Synthesizer Web App

A browser-based control interface for [Carla](https://kx.studio/Applications:Carla) running headless on a Raspberry Pi. Instead of needing a monitor and peripherals attached to the Pi, this app lets you load, browse, and tweak audio plugins from any device on your local network through a web browser.

---

## Overview

This project bridges low-level Linux audio software (JACK, Carla, OSC) with a real-time web UI. Plugin parameters are controlled via interactive knobs in the browser; each knob movement is sent over WebSockets and translated into an OSC UDP message that Carla receives instantly.

```
Browser Knob → WebSocket → Flask → OSC/UDP → Carla (headless on Pi)
```

---

## Architecture

The system is composed of three layers:

### 1. Carla Startup API (`CarlaStartupAPI/` — port 8080)
A REST API that directly interfaces with Carla's Python bindings (`libcarla_standalone2.so`). It is responsible for starting the Carla audio engine, loading project files, and managing plugins. Exposes the following endpoints:

| Endpoint | Method | Description |
|---|---|---|
| `/plugins` | GET | List all loaded plugins |
| `/plugins/{id}/parameters` | GET | Get parameters for a plugin |
| `/plugins/add` | POST | Add a plugin to the rack |
| `/plugin-db` | GET | Browse available plugins |

### 2. Flask Web Server (`app.py` — port 5000)
The middleware layer between the browser and Carla. It:
- Serves the HTML frontend (`templates/index.html`)
- Proxies REST requests to the Carla API
- Handles real-time knob events via **Flask-SocketIO** (WebSockets)
- Translates knob changes into **OSC (Open Sound Control)** messages over UDP

OSC messages follow this path format:
```
/{client_name}/{rackID}/set_parameter_value  [parameterID, value]
```

### 3. Frontend (`templates/index.html`)
A browser UI with interactive knobs rendered per plugin parameter. Knob changes are emitted as `knob_change` WebSocket events containing the parameter ID, rack slot, normalized value, and display value.

---

## Project Structure

```
DigitalSynthesizerWebApp/
├── app.py                    # Flask web server + SocketIO + OSC dispatcher
├── app_local.py              # Local development variant of app.py
├── config.yaml               # Main configuration file
├── config_local.yaml.example # Template for local environment overrides
├── config_loader.py          # YAML config parsing helpers
├── monitor_parameter.py      # Utility to monitor OSC parameter changes
├── carla_test.py             # Carla integration test script
├── requirements.txt          # Python dependencies
├── test.xml                  # Test/example Carla project XML
├── CarlaStartupAPI/          # REST API for Carla engine management
├── templates/                # Jinja2 HTML templates (Flask frontend)
├── data/                     # Plugin database definitions (JSON)
├── potdemo/                  # Potentiometer hardware input demo (C/C++)
├── Carla/                    # Carla-related assets or configs
└── venv/                     # Python virtual environment
```

---

## Prerequisites

### On the Raspberry Pi
- **Carla** audio plugin host (`apt install carla` or from [KX Studio](https://kx.studio))
- **JACK** audio server (`apt install jackd2`)
- **Python 3.8+**
- Carla shared library at `/usr/lib/carla/libcarla_standalone2.so`
- Carla Python bindings at `/usr/share/carla`

### Python Dependencies
Install via pip:
```bash
pip install -r requirements.txt
```

| Package | Version | Purpose |
|---|---|---|
| Flask | >=2.0.0 | Web framework |
| flask-socketio | >=5.0.0 | WebSocket support |
| python-osc | >=1.8.0 | OSC UDP messaging |
| PyYAML | >=6.0 | Config file parsing |
| python-socketio | >=5.0.0 | SocketIO backend |
| eventlet | >=0.33.0 | Async networking for SocketIO |

---

## Configuration

All settings live in `config.yaml`. Create a `config_local.yaml` to override settings for your local environment without modifying the main config file.

```yaml
carla:
  library_path: "/usr/lib/carla/libcarla_standalone2.so"
  python_path:  "/usr/share/carla"
  audio_driver: "JACK"           # JACK | ALSA | PulseAudio | Dummy
  client_name:  "WebAppHost"
  project_file: "defaultProj.carxp"

osc:
  ip:       "127.0.0.1"
  udp_port: 28017
  tcp_port: 5004

flask:
  host:  "0.0.0.0"   # All interfaces (accessible on local network)
  port:  5000
  debug: false

carla_api:
  host: "0.0.0.0"
  port: 8080

plugin_database:
  path: "data/plugin_database.json"
```

---

## Running the App

### 1. Start JACK
```bash
jackd -d alsa -r 44100 &
```

### 2. Start the Carla API server
```bash
cd CarlaStartupAPI
python main.py
```
This starts the REST API on port 8080, loads Carla, and opens the project file.

### 3. Start the Flask web server
```bash
python app.py
```
This starts the web UI on port 5000.

### 4. Open the UI
Navigate to `http://<raspberry-pi-ip>:5000` from any browser on your network.

---

## How It Works

1. The browser loads the plugin list from `/api/plugins`, which fetches each plugin and its parameters from the Carla API.
2. Each parameter is rendered as an interactive knob.
3. When a knob is moved, a `knob_change` event is emitted over WebSocket with the rack ID, parameter ID, and value.
4. Flask-SocketIO receives the event and sends an OSC UDP message to Carla:
   ```
   /WebAppHost/{rackID}/set_parameter_value  [paramID, displayValue]
   ```
5. Carla applies the parameter change in real time.

---

## Local Development

For local development (without a Pi/JACK), use the local app variant:
```bash
python app_local.py
```

Copy `config_local.yaml.example` to `config_local.yaml` and adjust paths and ports for your machine. Settings in `config_local.yaml` override `config.yaml`.

---

## Hardware Notes

The `potdemo/` directory contains a C/C++ demo for reading physical potentiometer input (analog knobs via ADC) that was developed to control analog knobs to control the Carla API directly.

---

## License

This project does not currently include a license file. All rights reserved by the author unless otherwise specified.
