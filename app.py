from flask import Flask, render_template
from flask_socketio import SocketIO
import socket
from pythonosc.udp_client import SimpleUDPClient

app = Flask(__name__)
socketio = SocketIO(app)
osc_ip = "127.0.0.1"   # change if your OSC target is on another device
osc_port = 5005        # Carlas OSC UDP port (make sure this matches Carla)
client = SimpleUDPClient(osc_ip, osc_port)

@app.route("/")
def index():
    return render_template("index.html")

@socketio.on("knob_change")
def handle_knob_change(data):
    value = data["value"]
    client.send_message("/Carla/1/set_parameter_value", [0, (value/100)*48-24])
    

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000)
