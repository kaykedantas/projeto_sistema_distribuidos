
import socket 
import time 
HOST = '10.62.206.45'
PORT = 8000
ALUNO = 'Kayke Andrade Dantas '
MENSAGEM = f'Olá: {HOST} \n {ALUNO}'

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect((HOST, PORT))
s.sendall(MENSAGEM.encode())


print('Mensagem enviada com sucesso')
teste = s.recv(1024)
teste = teste.decode()
print(teste)
if teste == "NOK":
    print("Mensagem não foi enviada")
    s.sendall(MENSAGEM.encode())
s.close()
    
#time.sleep(5)

