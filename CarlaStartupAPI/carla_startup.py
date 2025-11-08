import sys
import os
import json
import threading
import time
from typing import Any, Dict, List
from flask import Flask, jsonify, request

# Add project root to path for config loader
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
from config_loader import (
    get_carla_config,
    get_osc_config,
    get_carla_api_config,
    get_plugin_database_config,
)

# Load configuration
carla_cfg = get_carla_config()
osc_cfg = get_osc_config()
api_cfg = get_carla_api_config()
plugin_db_cfg = get_plugin_database_config()

# Add Carla Python backend to path
sys.path.append(carla_cfg.get("python_path", "/usr/share/carla"))
import carla_backend

# Import ENGINE_OPTION constants for better code clarity
from carla_backend import (
    ENGINE_OPTION_OSC_ENABLED,
    ENGINE_OPTION_OSC_PORT_TCP,
    ENGINE_OPTION_OSC_PORT_UDP
)

# === Configuration ===
LIB_PATH = carla_cfg.get("library_path", "/usr/lib/carla/libcarla_standalone2.so")
# Get absolute path to project file (relative to this script's directory)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
project_file = carla_cfg.get("project_file", "defaultProj.carxp")
PROJECT_PATH = os.path.join(SCRIPT_DIR, project_file)
AUDIO_DRIVER = carla_cfg.get("audio_driver", "JACK")
CLIENT_NAME = carla_cfg.get("client_name", "WebAppHost")
OSC_UDP_PORT = osc_cfg.get("udp_port", 28017)
OSC_TCP_PORT = osc_cfg.get("tcp_port", 5004)

# === Initialize Carla Host ===
print("Initializing Carla HostDLL...")
host = carla_backend.CarlaHostDLL(LIB_PATH, True)
driver_count = host.get_engine_driver_count()
print(f"HOST DRIVER COUNT: {driver_count}")
for i in range(driver_count):
    print(f"Driver {i}:")
    print(f"  Name: {host.get_engine_driver_name(i)}")
    print(f"  Devices: {host.get_engine_driver_device_names(i)}")

# Configure OSC (Open Sound Control) BEFORE initializing engine
# These options must be set before engine_init() for them to take effect
host.set_engine_option(ENGINE_OPTION_OSC_ENABLED, 1, "")
host.set_engine_option(ENGINE_OPTION_OSC_PORT_TCP, OSC_TCP_PORT, "")
host.set_engine_option(ENGINE_OPTION_OSC_PORT_UDP, OSC_UDP_PORT, "")

# Initialize the audio engine
ok = host.engine_init(AUDIO_DRIVER, CLIENT_NAME)
if not ok:
    print("Engine failed to start:", host.get_last_error())
    sys.exit(1)
print("Engine initialized successfully!")

loaded = host.load_project(PROJECT_PATH)
if not loaded:
    error_msg = host.get_last_error() or "Unknown error"
    print(f"Failed to load project: {error_msg}")
    sys.exit(1)
print("Project loaded successfully!")
print("Plugins in project:", host.get_current_plugin_count())

# === Plugin Database Loading ===
PLUGIN_DB_PATH = plugin_db_cfg.get("path")
PLUGIN_DATABASE: List[Dict[str, Any]] = []

BACKEND_TYPE_MAP = {
    "PLUGIN_NONE": carla_backend.PLUGIN_NONE,
    "NONE": carla_backend.PLUGIN_NONE,
    "PLUGIN_INTERNAL": carla_backend.PLUGIN_INTERNAL,
    "INTERNAL": carla_backend.PLUGIN_INTERNAL,
    "PLUGIN_LADSPA": carla_backend.PLUGIN_LADSPA,
    "LADSPA": carla_backend.PLUGIN_LADSPA,
    "PLUGIN_DSSI": carla_backend.PLUGIN_DSSI,
    "DSSI": carla_backend.PLUGIN_DSSI,
    "PLUGIN_LV2": carla_backend.PLUGIN_LV2,
    "LV2": carla_backend.PLUGIN_LV2,
    "PLUGIN_VST2": carla_backend.PLUGIN_VST2,
    "VST2": carla_backend.PLUGIN_VST2,
    "PLUGIN_VST3": carla_backend.PLUGIN_VST3,
    "VST3": carla_backend.PLUGIN_VST3,
    "PLUGIN_SF2": carla_backend.PLUGIN_SF2,
    "SF2": carla_backend.PLUGIN_SF2,
    "PLUGIN_SFZ": carla_backend.PLUGIN_SFZ,
    "SFZ": carla_backend.PLUGIN_SFZ,
    "PLUGIN_JSFX": carla_backend.PLUGIN_JSFX,
    "JSFX": carla_backend.PLUGIN_JSFX,
    "PLUGIN_JACK": carla_backend.PLUGIN_JACK,
    "JACK": carla_backend.PLUGIN_JACK,
    "PLUGIN_CLAP": carla_backend.PLUGIN_CLAP,
    "CLAP": carla_backend.PLUGIN_CLAP,
}

CATEGORY_MAP = {
    "PLUGIN_CATEGORY_NONE": carla_backend.PLUGIN_CATEGORY_NONE,
    "NONE": carla_backend.PLUGIN_CATEGORY_NONE,
    "PLUGIN_CATEGORY_SYNTH": carla_backend.PLUGIN_CATEGORY_SYNTH,
    "SYNTH": carla_backend.PLUGIN_CATEGORY_SYNTH,
    "PLUGIN_CATEGORY_DELAY": carla_backend.PLUGIN_CATEGORY_DELAY,
    "DELAY": carla_backend.PLUGIN_CATEGORY_DELAY,
    "PLUGIN_CATEGORY_EQ": carla_backend.PLUGIN_CATEGORY_EQ,
    "EQ": carla_backend.PLUGIN_CATEGORY_EQ,
    "PLUGIN_CATEGORY_FILTER": carla_backend.PLUGIN_CATEGORY_FILTER,
    "FILTER": carla_backend.PLUGIN_CATEGORY_FILTER,
    "PLUGIN_CATEGORY_DISTORTION": carla_backend.PLUGIN_CATEGORY_DISTORTION,
    "DISTORTION": carla_backend.PLUGIN_CATEGORY_DISTORTION,
    "PLUGIN_CATEGORY_DYNAMICS": carla_backend.PLUGIN_CATEGORY_DYNAMICS,
    "DYNAMICS": carla_backend.PLUGIN_CATEGORY_DYNAMICS,
    "PLUGIN_CATEGORY_MODULATOR": carla_backend.PLUGIN_CATEGORY_MODULATOR,
    "MODULATOR": carla_backend.PLUGIN_CATEGORY_MODULATOR,
    "PLUGIN_CATEGORY_UTILITY": carla_backend.PLUGIN_CATEGORY_UTILITY,
    "UTILITY": carla_backend.PLUGIN_CATEGORY_UTILITY,
    "PLUGIN_CATEGORY_OTHER": carla_backend.PLUGIN_CATEGORY_OTHER,
    "OTHER": carla_backend.PLUGIN_CATEGORY_OTHER,
}

OPTION_MAP = {
    "PLUGIN_OPTION_FIXED_BUFFERS": carla_backend.PLUGIN_OPTION_FIXED_BUFFERS,
    "PLUGIN_OPTION_FORCE_STEREO": carla_backend.PLUGIN_OPTION_FORCE_STEREO,
    "PLUGIN_OPTION_MAP_PROGRAM_CHANGES": carla_backend.PLUGIN_OPTION_MAP_PROGRAM_CHANGES,
    "PLUGIN_OPTION_USE_CHUNKS": carla_backend.PLUGIN_OPTION_USE_CHUNKS,
    "PLUGIN_OPTION_SEND_CONTROL_CHANGES": carla_backend.PLUGIN_OPTION_SEND_CONTROL_CHANGES,
    "PLUGIN_OPTION_SEND_CHANNEL_PRESSURE": carla_backend.PLUGIN_OPTION_SEND_CHANNEL_PRESSURE,
    "PLUGIN_OPTION_SEND_NOTE_AFTERTOUCH": carla_backend.PLUGIN_OPTION_SEND_NOTE_AFTERTOUCH,
    "PLUGIN_OPTION_SEND_PITCHBEND": carla_backend.PLUGIN_OPTION_SEND_PITCHBEND,
    "PLUGIN_OPTION_SEND_ALL_SOUND_OFF": carla_backend.PLUGIN_OPTION_SEND_ALL_SOUND_OFF,
    "PLUGIN_OPTION_SEND_PROGRAM_CHANGES": carla_backend.PLUGIN_OPTION_SEND_PROGRAM_CHANGES,
    "PLUGIN_OPTION_SKIP_SENDING_NOTES": carla_backend.PLUGIN_OPTION_SKIP_SENDING_NOTES,
}


def _resolve_path(path_value: str) -> str:
    """Resolve a config path relative to project root and expand user/home."""
    if not path_value:
        return ""
    expanded = os.path.expanduser(path_value)
    if os.path.isabs(expanded):
        return expanded
    return os.path.join(PROJECT_ROOT, expanded)


def load_plugin_database() -> None:
    """Load plugin database from configured path."""
    global PLUGIN_DATABASE
    if not PLUGIN_DB_PATH:
        print("No plugin database path configured; plugin addition disabled.")
        PLUGIN_DATABASE = []
        return

    db_path = _resolve_path(PLUGIN_DB_PATH)
    if not os.path.exists(db_path):
        print(f"Plugin database file not found at {db_path}; plugin addition disabled.")
        PLUGIN_DATABASE = []
        return

    try:
        with open(db_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            PLUGIN_DATABASE = data.get("plugins", [])
        elif isinstance(data, list):
            PLUGIN_DATABASE = data
        else:
            print(f"Unexpected plugin database format in {db_path}; expected list or dict.")
            PLUGIN_DATABASE = []
    except Exception as exc:
        print(f"Failed to load plugin database from {db_path}: {exc}")
        PLUGIN_DATABASE = []


load_plugin_database()

# === Keep the engine alive ===
def idle_loop():
    """Keeps the Carla engine responsive."""
    while True:
        try:
            host.engine_idle()
            time.sleep(0.05)  # run ~20 times per second
        except Exception as e:
            print("Idle loop stopped:", e)
            break

threading.Thread(target=idle_loop, daemon=True).start()

# === Flask app ===
app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    """API information and available endpoints"""
    return jsonify({
        "name": "Carla Startup API",
        "version": "1.0",
        "endpoints": {
            "GET /plugins": "List all loaded plugins",
            "GET /plugins/<id>/parameters": "List parameters for a plugin",
            "POST /plugins/set_parameter": "Set a parameter value (body: {plugin_id, param_id, value})",
            "GET /plugin-db": "List available plugins from configured database",
            "POST /plugins/add": "Add a plugin from the database (body: {plugin_id})",
            "POST /reload_project": "Reload the Carla project (optional body: {path})",
            "POST /shutdown": "Shutdown the Carla engine"
        }
    })

@app.route("/plugins", methods=["GET"])
def list_plugins():
    """List all loaded plugins"""
    plugins = []
    count = host.get_current_plugin_count()
    for i in range(count):
        info = host.get_plugin_info(i)
        plugins.append({
            "id": i,
            "name": info.get("name", ""),
            "label": info.get("label", "")
        })
    return jsonify({"plugins": plugins})

@app.route("/plugins/<int:plugin_id>/parameters", methods=["GET"])
def list_parameters(plugin_id):
    """List parameters for a given plugin"""
    try:
        plugin_count = host.get_current_plugin_count()
        if plugin_id < 0 or plugin_id >= plugin_count:
            return jsonify({"error": f"Invalid plugin_id: {plugin_id}. Valid range: 0-{plugin_count-1}"}), 400
        
        params = []
        n_params = host.get_parameter_count(plugin_id)
        for pid in range(n_params):
            pinfo = host.get_parameter_info(plugin_id, pid)
            prange = host.get_parameter_ranges(plugin_id, pid)
            value = host.get_current_parameter_value(plugin_id, pid)
            params.append({
                "id": pid,
                "name": pinfo.get("name", "") if pinfo else "",
                "min": prange.get("minimum", 0.0) if prange else 0.0,
                "max": prange.get("maximum", 1.0) if prange else 1.0,
                "value": value
            })
        return jsonify({"plugin_id": plugin_id, "parameters": params})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/plugins/set_parameter", methods=["POST"])
def set_parameter():
    """Set parameter value for a plugin"""
    try:
        data = request.get_json(force=True)
        plugin_id = int(data["plugin_id"])
        param_id = int(data["param_id"])
        value = float(data["value"])
        
        # Validate plugin_id
        plugin_count = host.get_current_plugin_count()
        if plugin_id < 0 or plugin_id >= plugin_count:
            return jsonify({"error": f"Invalid plugin_id: {plugin_id}"}), 400
        
        # Validate param_id
        param_count = host.get_parameter_count(plugin_id)
        if param_id < 0 or param_id >= param_count:
            return jsonify({"error": f"Invalid param_id: {param_id} for plugin {plugin_id}"}), 400
        
        host.set_parameter_value(plugin_id, param_id, value)
        return jsonify({"status": "ok", "plugin_id": plugin_id, "param_id": param_id, "value": value})
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({"error": f"Invalid request data: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/reload_project", methods=["POST"])
def reload_project():
    """Reload the Carla project"""
    try:
        data = request.get_json(force=True) if request.is_json else {}
        project_path = data.get("path", PROJECT_PATH)
        
        # If relative path, make it relative to script directory
        if not os.path.isabs(project_path):
            project_path = os.path.join(SCRIPT_DIR, project_path)
        
        # load_project accepts string, not bytes (based on test.py line 13)
        success = host.load_project(project_path)
        if not success:
            error_msg = host.get_last_error() or "Unknown error"
            return jsonify({"status": False, "error": error_msg}), 500
        return jsonify({"status": True, "path": project_path})
    except Exception as e:
        return jsonify({"status": False, "error": str(e)}), 500

@app.route("/plugin-db", methods=["GET"])
def plugin_database():
    """Return the configured plugin database entries."""
    if not PLUGIN_DATABASE:
        return jsonify({"plugins": [], "warning": "Plugin database not configured or empty."})

    entries = []
    for entry in PLUGIN_DATABASE:
        entries.append({
            "id": entry.get("id"),
            "display_name": entry.get("display_name", entry.get("name", entry.get("label", "Unnamed Plugin"))),
            "description": entry.get("description", ""),
            "backend_type": entry.get("backend_type"),
            "category": entry.get("category"),
        })
    return jsonify({"plugins": entries})


def _normalize_backend_type(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        key = value.strip().upper()
        return BACKEND_TYPE_MAP.get(key, BACKEND_TYPE_MAP.get(f"PLUGIN_{key}", carla_backend.PLUGIN_NONE))
    return carla_backend.PLUGIN_NONE


def _normalize_category(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        key = value.strip().upper()
        return CATEGORY_MAP.get(key, CATEGORY_MAP.get(f"PLUGIN_CATEGORY_{key}", carla_backend.PLUGIN_CATEGORY_NONE))
    return carla_backend.PLUGIN_CATEGORY_NONE


def _normalize_options(options: Any) -> int:
    if not options:
        return 0
    if isinstance(options, int):
        return options
    if isinstance(options, list):
        bitmask = 0
        for item in options:
            if isinstance(item, int):
                bitmask |= item
            elif isinstance(item, str):
                key = item.strip().upper()
                bitmask |= OPTION_MAP.get(key, OPTION_MAP.get(f"PLUGIN_OPTION_{key}", 0))
        return bitmask
    return 0


def _find_plugin_entry(plugin_id: str) -> Dict[str, Any]:
    for entry in PLUGIN_DATABASE:
        if entry.get("id") == plugin_id:
            return entry
    return {}


@app.route("/plugins/add", methods=["POST"])
def add_plugin():
    """Add a new plugin from the plugin database to the current project."""
    if not PLUGIN_DATABASE:
        return jsonify({"error": "Plugin database not configured"}), 400

    try:
        data = request.get_json(force=True)
        plugin_id = data.get("plugin_id")
        if not plugin_id:
            return jsonify({"error": "plugin_id is required"}), 400

        entry = _find_plugin_entry(plugin_id)
        if not entry:
            return jsonify({"error": f"Plugin id '{plugin_id}' not found in database"}), 404

        backend_type = _normalize_backend_type(entry.get("backend_type", carla_backend.PLUGIN_INTERNAL))
        category = _normalize_category(entry.get("category", carla_backend.PLUGIN_CATEGORY_NONE))
        filename = entry.get("filename", "") or ""
        name = entry.get("name", "")
        label = entry.get("label", "")
        unique_id = int(entry.get("unique_id", 0))
        options = _normalize_options(entry.get("options", []))

        success = host.add_plugin(
            backend_type,
            category,
            filename,
            name,
            label,
            unique_id,
            None,
            options,
        )

        if not success:
            error_msg = host.get_last_error() or "Unknown error while adding plugin"
            return jsonify({"error": error_msg}), 500

        new_plugin_index = host.get_current_plugin_count() - 1
        plugin_info = host.get_plugin_info(new_plugin_index)
        return jsonify({"status": "ok", "plugin": plugin_info, "plugin_id": new_plugin_index})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@app.route("/shutdown", methods=["POST"])
def shutdown():
    """Gracefully close the Carla engine"""
    try:
        host.engine_close()
        print("Engine closed cleanly.")
    finally:
        func = request.environ.get("werkzeug.server.shutdown")
        if func:
            func()
    return jsonify({"status": "engine closed"})

# === Run server ===
if __name__ == "__main__":
    api_host = api_cfg.get("host", "0.0.0.0")
    api_port = api_cfg.get("port", 8080)
    app.run(host=api_host, port=api_port)
