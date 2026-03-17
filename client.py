
import socket 
import time 
HOST = '10.62.206.46'
PORT = 8000
ALUNO = 'Kayke Andrade Dantas '
MENSAGEM = f'Olá: {HOST} \n {ALUNO}'
MENSAGEM_2 = f'Olá: {HOST} \n {ALUNO} \n Mensagem 2'

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect((HOST, PORT))
s.sendall(MENSAGEM.encode())


print('Mensagem enviada com sucesso')
teste = s.recv(1024)
teste = teste.decode()
print(teste)
if teste == "NOK":
    print("Mensagem não foi enviada")
s.sendall(MENSAGEM_2.encode())
s.close()
    
#time.sleep(5)
