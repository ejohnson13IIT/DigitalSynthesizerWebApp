import sys
import os
import threading
import time
from flask import Flask, jsonify, request

# Add project root to path for config loader
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config_loader import get_carla_config, get_osc_config, get_carla_api_config

# Load configuration
carla_cfg = get_carla_config()
osc_cfg = get_osc_config()
api_cfg = get_carla_api_config()

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
