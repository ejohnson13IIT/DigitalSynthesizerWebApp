from flask import Flask, request, render_template
import threading, time, socket
from tcp_server import tcp_server
from udp_server import udp_server

app = Flask(__name__)

@app.route("/", methods=["GET"])
def home():
    return render_template("index.html", result=None)

@app.route("/send", methods=["POST"])
def send_message():
    msg = request.form["msg"]
    proto = request.form["proto"]

    host = "127.0.0.1"  # Pi itself
    port = 5001

    if proto == "tcp":
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        start = time.time()
        s.connect((host, port))
        s.sendall(msg.encode())
        data = s.recv(1024).decode()
        end = time.time()
        s.close()
    else:  # UDP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        start = time.time()
        s.sendto(msg.encode(), (host, port))
        data, _ = s.recvfrom(1024)
        data = data.decode()
        end = time.time()
        s.close()

    latency_ms = (end - start) * 1000
    result = f"{proto.upper()} reply: {data} | Latency: {latency_ms:.2f} ms"

    return render_template("index.html", result=result)

if __name__ == "__main__":
    # Start TCP and UDP servers in background threads
    threading.Thread(target=tcp_server, daemon=True).start()
    threading.Thread(target=udp_server, daemon=True).start()
    
    app.run(host="0.0.0.0", port=5000, debug=True)
