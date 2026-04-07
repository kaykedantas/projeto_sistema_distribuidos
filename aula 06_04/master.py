import socket
import time 
import threading 
host = '10.62.206.45' # Endereço IP local (localhost)
PORT = 8000        # Porta específica exigida no requisito

last_heatbeat = time.time()


def monitor ():
    global last_heatbeat
    while True: 
        time.sleep(5)
        if time.time() - last_heatbeat > 15:
            print("worker morreu!")
            break
def handle_clientt(conn):
    global last_heatbeat
    while True: 
        data = conn.recv(1024)
        if not data:
            print("worker morreu!")
            break
        menssagem = data.decode()
        if menssagem =="Ta vivo ?":
            last_heatbeat = time.time()
            print("Worker está vivo!")
    conn.close()


def start_master():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((host, PORT))
    server.listen()
    
    print("Master aguardando conexão...")
    conn, addr = server.accept()

    print("Worker conectado:", addr)

    threading.Thread(target=monitor).start()
    handle_clientt(conn) 




start_master()






#  Criação do Socket: IPv4 (AF_INET) e TCP (SOCK_STREAM)
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s: #AF_INET é o que define que o protocolo será ipv4
    # Vínculo (Bind): Associa o socket ao IP e porta
    s.bind((HOST, PORT))
    
    #  Deixa o servidor no mode de espera
    s.listen()
    print(f"Servidor escutando na porta {PORT}...")
    
    #  aceita a conexao 
    conn, addr = s.accept()
    with conn:
        print(f"Nova conexão estabelecida com: {addr}")
        
        # le os dados e discripto grafa eles 
        data = conn.recv(1024)
        print(f"Mensagem recebida do cliente: {data.decode()}")
        
        #  manda devolva uma resposta 
        resposta = " Foi recebido por mim(Servidor)!"
        conn.sendall(resposta.encode())
        
        # falta a confirmacao do ok 
        confirmacao = conn.recv(1024)
        print(f"Confirmação final do cliente: {confirmacao.decode()}")
        
        
    print("Conexão encerrada pelo servidor.")