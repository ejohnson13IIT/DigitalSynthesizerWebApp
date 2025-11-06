import sys
import threading
import time
from flask import Flask, jsonify, request
sys.path.append("/usr/share/carla")
import carla_backend

# === Configuration ===
LIB_PATH = "/usr/lib/carla/libcarla_standalone2.so"
PROJECT_PATH = "defaultProj.carxp"
AUDIO_DRIVER = "PulseAudio"
CLIENT_NAME = "WebAppHost"

# === Initialize Carla Host ===
print("Initializing Carla HostDLL...")
host = carla_backend.CarlaHostDLL(LIB_PATH, True)
print("HOST DRIVER COUNT: ", host.get_engine_driver_count())
for i in range(4):
    print(i)
    print(host.get_engine_driver_device_names(i))
    print(host.get_engine_driver_name(i))
    

ok = host.engine_init(AUDIO_DRIVER, CLIENT_NAME)
host.set_engine_option(15, 1, "")
host.set_engine_option(16, 5004, "")
host.set_engine_option(17, 5005, "")
if not ok:
    print("Engine failed to start:", host.get_last_error())
    sys.exit(1)
print("Engine initialized successfully!")

loaded = host.load_project(PROJECT_PATH)
print("Project loaded:", loaded)
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
    params = []
    n_params = host.get_parameter_count(plugin_id)
    for pid in range(n_params):
        pinfo = host.get_parameter_info(plugin_id, pid)
        prange = host.get_parameter_ranges(plugin_id, pid)
        value = host.get_current_parameter_value(plugin_id, pid)
        params.append({
            "id": pid,
            "name": pinfo.get("name", ""),
            "min": prange.get("minimum", 0.0),
            "max": prange.get("maximum", 1.0),
            "value": value
        })
    return jsonify({"plugin_id": plugin_id, "parameters": params})

@app.route("/plugins/set_parameter", methods=["POST"])
def set_parameter():
    """Set parameter value for a plugin"""
    data = request.get_json(force=True)
    plugin_id = int(data["plugin_id"])
    param_id = int(data["param_id"])
    value = float(data["value"])
    host.set_parameter_value(plugin_id, param_id, value)
    return jsonify({"status": "ok", "plugin_id": plugin_id, "param_id": param_id, "value": value})

@app.route("/reload_project", methods=["POST"])
def reload_project():
    """Reload the Carla project"""
    data = request.get_json(force=True)
    project_path = data.get("path", PROJECT_PATH)
    success = host.load_project(project_path.encode("utf-8"))
    return jsonify({"status": success})

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
    app.run(host="0.0.0.0", port=8080)
