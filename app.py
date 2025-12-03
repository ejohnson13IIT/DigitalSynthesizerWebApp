from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO
from pythonosc.udp_client import SimpleUDPClient
from werkzeug.utils import secure_filename
from config_loader import (
    get_osc_config,
    get_flask_config,
    get_carla_config,
    get_carla_api_config,
)
import logging
import requests
import os
import shutil

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Load configuration
osc_cfg = get_osc_config()
flask_cfg = get_flask_config()
carla_cfg = get_carla_config()
carla_api_cfg = get_carla_api_config()

socketio = SocketIO(app, cors_allowed_origins="*")
osc_ip = osc_cfg.get("ip", "127.0.0.1")
osc_port = osc_cfg.get("udp_port", 28017)
client = SimpleUDPClient(osc_ip, osc_port)

# Get Carla client name for OSC path
carla_client_name = carla_cfg.get("client_name", "Carla")
logger.info(f"OSC client configured: {osc_ip}:{osc_port}")
logger.info(f"Carla client name: {carla_client_name}")

# Prepare Carla API base URL (fallback to localhost if host is 0.0.0.0)
raw_api_host = carla_api_cfg.get("host", "127.0.0.1")
api_host = "127.0.0.1" if raw_api_host in ("0.0.0.0", "::") else raw_api_host
api_port = carla_api_cfg.get("port", 8080)
carla_api_base = f"http://{api_host}:{api_port}"
logger.info(f"Carla API base URL: {carla_api_base}")

#Setting allowed file types for file uploads
lv2_dir = "/home/jmehta18/.lv2"
vst2_dir = "/home/jmehta18/.vst3"
vst3_dir = "/home/jmehta18/.vst3"

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/plugins", methods=["GET"])
def fetch_plugins():
    """Fetch plugins and their parameters from the Carla API."""
    try:
        plugins_resp = requests.get(f"{carla_api_base}/plugins", timeout=5)
        plugins_resp.raise_for_status()
        plugin_list = plugins_resp.json().get("plugins", [])

        detailed_plugins = []
        for plugin in plugin_list:
            plugin_id = plugin.get("id")
            if plugin_id is None:
                continue

            params_resp = requests.get(
                f"{carla_api_base}/plugins/{plugin_id}/parameters", timeout=5
            )
            params_resp.raise_for_status()
            parameters = params_resp.json().get("parameters", [])
            plugin_with_params = {
                **plugin,
                "parameters": parameters,
            }
            detailed_plugins.append(plugin_with_params)

        return jsonify({"plugins": detailed_plugins})
    except requests.exceptions.RequestException as err:
        logger.error("Failed to fetch plugin metadata from Carla API: %s", err)
        return jsonify({"error": "Failed to reach Carla API", "detail": str(err)}), 502
    except Exception as exc:
        logger.exception("Unexpected error while fetching plugins")
        return jsonify({"error": "Unexpected server error", "detail": str(exc)}), 500


@app.route("/api/plugin-db", methods=["GET"])
def fetch_plugin_database():
    """Fetch available plugins from the Carla API plugin database."""
    try:
        resp = requests.get(f"{carla_api_base}/plugin-db", timeout=5)
        resp.raise_for_status()
        return jsonify(resp.json())
    except requests.exceptions.RequestException as err:
        logger.error("Failed to fetch plugin database from Carla API: %s", err)
        return jsonify({"error": "Failed to reach Carla API", "detail": str(err)}), 502
    except Exception as exc:
        logger.exception("Unexpected error while fetching plugin database")
        return jsonify({"error": "Unexpected server error", "detail": str(exc)}), 500


@app.route("/api/plugins/discover", methods=["GET"])
def discover_plugins():
    """Discover available plugins from configured plugin paths using Carla's discovery system."""
    try:
        resp = requests.get(f"{carla_api_base}/plugins/discover", timeout=30)
        resp.raise_for_status()
        return jsonify(resp.json())
    except requests.exceptions.RequestException as err:
        logger.error("Failed to discover plugins from Carla API: %s", err)
        return jsonify({"error": "Failed to reach Carla API", "detail": str(err)}), 502
    except Exception as exc:
        logger.exception("Unexpected error while discovering plugins")
        return jsonify({"error": "Unexpected server error", "detail": str(exc)}), 500


@app.route("/api/plugins/add", methods=["POST"])
def proxy_add_plugin():
    """Proxy request to add a plugin via the Carla API."""
    try:
        payload = request.get_json(force=True)
        resp = requests.post(f"{carla_api_base}/plugins/add", json=payload, timeout=5)
        content = resp.json() if resp.content else {}
        return jsonify(content), resp.status_code
    except requests.exceptions.RequestException as err:
        logger.error("Failed to add plugin via Carla API: %s", err)
        return jsonify({"error": "Failed to reach Carla API", "detail": str(err)}), 502
    except Exception as exc:
        logger.exception("Unexpected error while adding plugin")
        return jsonify({"error": "Unexpected server error", "detail": str(exc)}), 500


@app.route("/api/plugins/move", methods=["POST"])
def proxy_move_plugin():
    """Proxy request to move a plugin in the chain via the Carla API."""
    try:
        payload = request.get_json(force=True)
        resp = requests.post(f"{carla_api_base}/plugins/move", json=payload, timeout=5)
        content = resp.json() if resp.content else {}
        return jsonify(content), resp.status_code
    except requests.exceptions.RequestException as err:
        logger.error("Failed to move plugin via Carla API: %s", err)
        return jsonify({"error": "Failed to reach Carla API", "detail": str(err)}), 502
    except Exception as exc:
        logger.exception("Unexpected error while moving plugin")
        return jsonify({"error": "Unexpected server error", "detail": str(exc)}), 500

@app.route("/api/plugins/remove", methods=["POST"])
def proxy_remove_plugin():
    """Proxy request to remove a plugin via the Carla API."""
    try:
        payload = request.get_json(force=True)
        resp = requests.post(f"{carla_api_base}/plugins/remove", json=payload, timeout=5)
        content = resp.json() if resp.content else {}
        return jsonify(content), resp.status_code
    except requests.exceptions.RequestException as err:
        logger.error("Failed to remove plugin via Carla API: %s", err)
        return jsonify({"error": "Failed to reach Carla API", "detail": str(err)}), 502
    except Exception as exc:
        logger.exception("Unexpected error while removing plugin")
        return jsonify({"error": "Unexpected server error", "detail": str(exc)}), 500

@app.route("/api/upload-plugin", methods=["POST"])
def upload_plugin():
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["file"]
        
        if not file.filename.lower().endswith(".zip"):
            return jsonify({"error": "Only .zip files are allowed"}), 400

        filename = secure_filename(file.filename)
        temp_zip_path = os.path.join("/tmp", filename)
        
        # Save ZIP to /tmp
        file.save(temp_zip_path)

        # Create temp extract directory
        extract_dir = os.path.join("/tmp", filename + "_extract")
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)
        os.makedirs(extract_dir, exist_ok=True)

        # Extract ZIP
        import zipfile
        with zipfile.ZipFile(temp_zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)

        os.remove(temp_zip_path)

        # Determine plugin type by scanning extracted contents
        installed_plugins = []

        for root, dirs, files in os.walk(extract_dir):
            # LV2 bundles (folders ending in .lv2/)
            for d in dirs:
                if d.endswith(".lv2"):
                    src = os.path.join(root, d)
                    dst = os.path.join(lv2_dir, d)
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                    installed_plugins.append(d)

            # VST3 bundles (folders ending in .vst3/)
            for d in dirs:
                if d.endswith(".vst3"):
                    src = os.path.join(root, d)
                    dst = os.path.join(vst3_dir, d)
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                    installed_plugins.append(d)

            # VST2 (.so or .dll files)
            for f in files:
                if f.endswith(".dll"):
                    src = os.path.join(root, f)
                    dst = os.path.join(vst2_dir, f)
                    shutil.copy2(src, dst)
                    installed_plugins.append(f)

        shutil.rmtree(extract_dir)

        if not installed_plugins:
            return jsonify({"error": "No valid plugin files (.lv2, .vst3, .so, .dll) found inside ZIP"}), 400

        # Trigger plugin discovery
        try:
            requests.get(f"{carla_api_base}/plugins/discover", timeout=10)
        except:
            pass

        return jsonify({
            "success": True,
            "installed": installed_plugins
        }), 200

    except Exception as e:
        logger.exception("Upload failed")
        return jsonify({"error": str(e)}), 500


@socketio.on("knob_change")
def handle_knob_change(data):
    try:
        parameterID = data["knob"]
        # Frontend now sends actual (unnormalized) value in 'value' field
        actual_value = float(data["value"])
        display_value = data.get("displayValue")  # Same as actual value for logging
        
        # Send the actual value directly to OSC (no normalization)
        value_to_send = actual_value
        
        rackID = data["rack"]
        sentMsg = f"/{carla_client_name}/{rackID}/set_parameter_value"
        client.send_message(sentMsg, [parameterID, value_to_send])

        if display_value is not None:
            logger.info(
                "OSC sent: %s [%s, %.4f] (actual value, display: %.4f)",
                sentMsg,
                parameterID,
                value_to_send,
                display_value,
            )
        else:
            logger.info(
                "OSC sent: %s [%s, %.4f] (actual value)",
                sentMsg,
                parameterID,
                value_to_send,
            )
    except Exception as e:
        logger.error(f"Error in handle_knob_change: {e}")

if __name__ == "__main__":
    print("WEBAPP_READY", flush=True)
    flask_host = flask_cfg.get("host", "0.0.0.0")
    flask_port = flask_cfg.get("port", 5000)
    flask_debug = flask_cfg.get("debug", False)
    socketio.run(app, host=flask_host, port=flask_port, debug=flask_debug)
