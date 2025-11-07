from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO
import socket
from pythonosc.udp_client import SimpleUDPClient
from config_loader import get_osc_config, get_flask_config, get_carla_config

app = Flask(__name__)

# Load configuration
osc_cfg = get_osc_config()
flask_cfg = get_flask_config()
carla_cfg = get_carla_config()

socketio = SocketIO(app)
osc_ip = osc_cfg.get("ip", "127.0.0.1")
osc_port = osc_cfg.get("udp_port", 28017)
client = SimpleUDPClient(osc_ip, osc_port)

# Get Carla client name for OSC path
carla_client_name = carla_cfg.get("client_name", "Carla")

@app.route("/")
def index():
    return render_template("index.html")

@socketio.on("knob_change")
def handle_knob_change(data):
    parameterID=data["knob"]
    value = data["value"]
    rackID=data["rack"]
    sentMsg=f"/{carla_client_name}/{rackID}/set_parameter_value"
    client.send_message(sentMsg, [parameterID, (value/100)*48-24])

if __name__ == "__main__":
    flask_host = flask_cfg.get("host", "0.0.0.0")
    flask_port = flask_cfg.get("port", 5000)
    flask_debug = flask_cfg.get("debug", False)
    socketio.run(app, host=flask_host, port=flask_port, debug=flask_debug)
