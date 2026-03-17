import socket 
import json

HOST = '10.62.206.46'
PORT = 8000
J2={
    "SERVER_UUID": "...",
    "TASK": "HEARTBEAT",
    "RESPONSE": "ALIVE"
}
MENSAGEM2 = json.dumps(J2)

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

s.bind((HOST, PORT))

s.listen()
print(f"Servidor escutando na porta: {PORT}...")

conn, addr = s.accept()

with conn:
    mensagem = conn.recv(1024)
    print(f'{mensagem.decode()}')

    conn.sendall(MENSAGEM2.encode())



