from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO
from pythonosc.udp_client import SimpleUDPClient
from config_loader import (
    get_osc_config,
    get_flask_config,
    get_carla_config,
    get_carla_api_config,
)
import logging
import requests

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

@socketio.on("knob_change")
def handle_knob_change(data):
    try:
        parameterID = data["knob"]
        normalized_value = float(data["value"])
        display_value = data.get("displayValue")

        if display_value is not None:
            try:
                value_to_send = float(display_value)
            except (TypeError, ValueError):
                logger.warning(
                    "Invalid displayValue %s for parameter %s; falling back to normalized value",
                    display_value,
                    parameterID,
                )
                value_to_send = normalized_value
        else:
            value_to_send = normalized_value
        rackID = data["rack"]
        sentMsg = f"/{carla_client_name}/{rackID}/set_parameter_value"
        client.send_message(sentMsg, [parameterID, value_to_send])

        if display_value is not None:
            logger.info(
                "OSC sent: %s [%s, %.4f] (actual: %.4f)",
                sentMsg,
                parameterID,
                normalized_value,
                value_to_send,
            )
        else:
            logger.info(
                "OSC sent: %s [%s, %.4f]",
                sentMsg,
                parameterID,
                value_to_send,
            )
    except Exception as e:
        logger.error(f"Error in handle_knob_change: {e}")

if __name__ == "__main__":
    flask_host = flask_cfg.get("host", "0.0.0.0")
    flask_port = flask_cfg.get("port", 5000)
    flask_debug = flask_cfg.get("debug", False)
    socketio.run(app, host=flask_host, port=flask_port, debug=flask_debug)
