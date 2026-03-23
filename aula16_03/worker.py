import socket 
import json 

HOST = '10.62.206.46'
PORT = 8000

J= {
"SERVER_UUID": "Master_A",
"TASK": "HEARTBEAT"
}
MENSAGEM = f" ola {HOST} /n {json.dumps(J)}"

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect((HOST, PORT))
s.sendall(MENSAGEM.encode())
print('Mensagem enviada com sucesso')
print(json.dumps(J))

teste = s.recv(1024)
teste = teste.decode()
print (teste)
