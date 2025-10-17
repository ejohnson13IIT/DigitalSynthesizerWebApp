import socket
import threading

def tcp_server(host="0.0.0.0", tcp_port=5001):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind((host, tcp_port))
    server_socket.listen(5)
    print(f"TCP server listening on {host}:{tcp_port}")

    while True:
        conn, addr = server_socket.accept()
        print(f"TCP connection from {addr}")
        data = conn.recv(1024).decode()
        print(f"TCP received: {data}")
        conn.sendall(f"TCP echo: {data}".encode())
        conn.close()
