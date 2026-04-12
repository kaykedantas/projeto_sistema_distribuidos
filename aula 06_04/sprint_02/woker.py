import socket
import time
import json
import uuid

# Configurações
HOST_MASTER = '10.62.206.45'
PORT = 8000

# Gera um ID único para este worker ou usa um fixo como "W-123"
MEU_UUID = f"W-{str(uuid.uuid4())[:4].upper()}"

def processar_tarefa(user):
    """ Simula o tempo de processamento de uma requisição """
    print(f" -> Processando dados para o usuário: {user}...")
    time.sleep(3) # Simula o trabalho
    return "OK" # Retorna sucesso

def ciclo_trabalho():
    print(f"Iniciando Worker {MEU_UUID}")
    
    while True:
        time.sleep(5) # Aguarda o próximo ciclo
        
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5) # Timeout exigido de 5 segundos
            s.connect((HOST_MASTER, PORT))
            
            # 1. Apresentação
            handshake = json.dumps({
                "WORKER": "ALIVE",
                "WORKER_UUID": MEU_UUID
            }) + "\n"
            s.sendall(handshake.encode())
            
            # 2. Recebe a Tarefa
            resposta = s.recv(1024).decode().strip()
            if not resposta:
                s.close()
                continue
                
            payload_task = json.loads(resposta)
            
            if payload_task.get("TASK") == "NO_TASK":
                print(" Nenhuma tarefa na fila. Aguardando...")
            
            elif payload_task.get("TASK") == "QUERY":
                usuario = payload_task.get("USER", "Desconhecido")
                
                # Processa o trabalho
                status_final = processar_tarefa(usuario)
                
                # 3. Reporta o Status
                reporte = json.dumps({
                    "STATUS": status_final,
                    "TASK": "QUERY",
                    "WORKER_UUID": MEU_UUID
                }) + "\n"
                s.sendall(reporte.encode())
                
                # 4. Aguarda a Confirmação Final (ACK)
                resposta_ack = s.recv(1024).decode().strip()
                payload_ack = json.loads(resposta_ack)
                
                if payload_ack.get("STATUS") == "ACK":
                    print(" Ciclo concluído com Sucesso (ACK recebido).")
            
            s.close()
            
        except Exception as e:
            print(f"[!] Erro de conexão ou Timeout: {e}. Tentando reconectar no próximo ciclo.")

if __name__ == "__main__":
    ciclo_trabalho()