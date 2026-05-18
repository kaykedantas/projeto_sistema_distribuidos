import socket
import threading
import json
import time
import queue

HOST = '10.62.206.45' 
PORT = 8000

# Fila de tarefas pendentes (Thread-safe)
fila_tarefas = queue.Queue()

def gerar_carga_simulada():
    """ Thread para simular clientes enviando requisições ao Master """
    contador = 1
    while True:
        time.sleep(10) # A cada 10 segundos chega uma nova tarefa
        fila_tarefas.put(f"Usuario_{contador}")
        print(f"[!] Nova requisição recebida. Fila atual: {fila_tarefas.qsize()}")
        contador += 1

def handle_worker(conn, addr):
    try:
        # 1. Aguarda a apresentação do Worker
        data = conn.recv(1024)
        if not data:
            return
            
        # Lê o JSON e remove o \n
        mensagem_bruta = data.decode().strip()
        payload = json.loads(mensagem_bruta)
        
        # Verifica se é uma apresentação válida
        if payload.get("WORKER") == "ALIVE" and "WORKER_UUID" in payload:
            worker_id = payload["WORKER_UUID"]
            print(f"[*] Handshake OK com {worker_id} ({addr})")
            
            # 2. Verifica a Fila e Distribui Tarefa
            if not fila_tarefas.empty():
                usuario = fila_tarefas.get()
                resposta_task = json.dumps({"TASK": "QUERY", "USER": usuario}) + "\n"
                conn.sendall(resposta_task.encode())
                
                # 3. Aguarda o Reporte de Status do Worker
                data_status = conn.recv(1024)
                status_payload = json.loads(data_status.decode().strip())
                
                if status_payload.get("STATUS") in ["OK", "NOK"]:
                    print(f"[*] Tarefa {status_payload['TASK']} do {worker_id} -> STATUS: {status_payload['STATUS']}")
                    
                    # 4. Envia o ACK Final para liberar o Worker
                    ack = json.dumps({"STATUS": "ACK", "WORKER_UUID": worker_id}) + "\n"
                    conn.sendall(ack.encode())
            else:
                # Fila Vazia
                resposta_vazia = json.dumps({"TASK": "NO_TASK"}) + "\n"
                conn.sendall(resposta_vazia.encode())
                
    except Exception as e:
        print(f"[Erro na comunicação com {addr}]: {e}")
    finally:
        conn.close()

def start_master():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen()
    print(f"Master (Sprint 2) rodando em {HOST}:{PORT}")
    
    # Inicia o gerador de tarefas
    threading.Thread(target=gerar_carga_simulada, daemon=True).start()
    
    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_worker, args=(conn, addr)).start()

if __name__ == "__main__":
    start_master()