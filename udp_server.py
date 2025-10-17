import socket

def udp_server(host="0.0.0.0", udp_port=5002):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, udp_port))
    print(f"UDP server listening on {host}:{udp_port}")

    while True:
        data, addr = sock.recvfrom(1024)
        print(f"UDP message from {addr}: {data.decode()}")
        sock.sendto(f"UDP echo: {data.decode()}".encode(), addr)
