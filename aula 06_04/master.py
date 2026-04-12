import socket
import threading

# IP do Master Original exigido pelo professor
HOST = '10.62.206.45' 
PORT = 8000

def handle_worker(conn, addr):
    """ Função que atende cada worker separadamente """
    print(f"Worker conectado: {addr}")
    while True:
        try:
            data = conn.recv(1024)
            if not data:
                break
            
            menssagem = data.decode()
            if menssagem == "Ta vivo ?":
                conn.sendall("to vivo".encode())
        except Exception as a:
            break
            
    conn.close()
    print(f"Worker desconectado: {addr}")

def start_master():
    """ Inicia o servidor e cria uma Thread para cada novo worker """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen()
    print(f"Master inicial rodando em {HOST}:{PORT}")
    
    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_worker, args=(conn, addr)).start()

# Inicia o código
start_master()