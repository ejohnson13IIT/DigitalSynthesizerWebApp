from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO
import socket
from pythonosc.udp_client import SimpleUDPClient

app = Flask(__name__)


socketio = SocketIO(app)
osc_ip = "127.0.0.1"   # change if your OSC target is on another device
osc_port = 28017        # Carlas OSC UDP port (make sure this matches Carla)
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
    socketio.run(app, host="127.0.0.1", port=5000)
