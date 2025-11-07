from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO
import socket
from pythonosc.udp_client import SimpleUDPClient

app = Flask(__name__)

# Local-only configuration (no config file needed)
# For accessing from the same device only
socketio = SocketIO(app)
osc_ip = "127.0.0.1"  # Localhost - Carla must be on same machine
osc_port = 28017      # OSC port (change if your Carla uses different port)
client = SimpleUDPClient(osc_ip, osc_port)

@app.route("/")
def index():
    return render_template("index_local.html")

@socketio.on("knob_change")
def handle_knob_change(data):
    parameterID=data["knob"]
    value = data["value"]
    rackID=data["rack"]
    sentMsg="/Carla/"+str(rackID)+"/set_parameter_value"
    client.send_message(sentMsg, [parameterID, (value/100)*48-24])

if __name__ == "__main__":
    # Local-only: bind to localhost only (127.0.0.1)
    # Access at http://localhost:5000 or http://127.0.0.1:5000
    socketio.run(app, host="127.0.0.1", port=5000, debug=True)
