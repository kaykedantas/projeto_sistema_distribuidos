import socket 
import time 
import shutil
import threading 

PORT = 8000
host_master = '10.62.206.45'  
meu_ip = '10.62.206.46'       
# VEJA QUE A LISTA IPS_REDE FOI EXCLUÍDA!

erros_conexao = 0
sou_master = False
em_eleicao = False
votos_eleicao = {}

def escutar_eleicao_udp():
    """ Escuta os gritos (Broadcast) da rede sem precisar saber quem enviou """
    global em_eleicao, votos_eleicao
    
    server_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_udp.bind(('', PORT))
    
    while True:
        data, addr = server_udp.recvfrom(1024)
        menssagem = data.decode()
        
        if "MEUS_DADOS" in menssagem:
            partes = menssagem.split("|")
            ip_colega = partes[1]
            espaco_colega = int(partes[2])
            
            votos_eleicao[ip_colega] = espaco_colega
            print(f"Recebi via Broadcast do {ip_colega}: {espaco_colega} bytes")
            
            # Se recebi dados de eleição e ainda não mandei os meus, mando agora!
            if not em_eleicao:
                threading.Thread(target=iniciar_eleicao).start()

def escutar_heartbeat_tcp():
    """ Fica escutando conexões TCP apenas caso este nó vire o Master """
    global sou_master
    
    server_tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_tcp.bind(('', PORT))
    server_tcp.listen()
    
    while True:
        conn, addr = server_tcp.accept()
        try:
            menssagem = conn.recv(1024).decode()
            if sou_master and menssagem == "Ta vivo ?":
                conn.sendall("to vivo".encode())
        except:
            pass
        finally:
            conn.close()

def iniciar_eleicao():
    global em_eleicao, votos_eleicao, host_master, sou_master, erros_conexao
    if em_eleicao: 
        return
        
    em_eleicao = True
    print("\nMaster morreu! Gritando meus dados na rede (Broadcast)...")
    
    meu_espaco = shutil.disk_usage("/").free
    votos_eleicao[meu_ip] = meu_espaco 
    
    # Manda para a rede inteira no IP de Broadcast (255.255.255.255)
    # Não precisamos saber quem está do outro lado!
    try: 
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(f"MEUS_DADOS|{meu_ip}|{meu_espaco}".encode(), ('255.255.255.255', PORT))
        s.close()
    except Exception as a:
        print(f"Erro ao mandar Broadcast: {a}")
    
    time.sleep(4) # Espera dar tempo da rede inteira processar e receber os gritos
    
    # Todo mundo calcula quem ganhou sozinho e chega no mesmo resultado
    vencedor = max(votos_eleicao, key=votos_eleicao.get)
    print(f"\nFim da votação! Todo mundo verificou que o novo master é: {vencedor}")
    
    host_master = vencedor
    if vencedor == meu_ip:
        print("-> Eu sou o novo master!")
        sou_master = True
    else:
        print("-> Continuo como worker, alterando rota para o novo master.")
        sou_master = False
        
    erros_conexao = 0
    em_eleicao = False
    votos_eleicao.clear() 

def hertbeat():
    global erros_conexao
    while True: 
        time.sleep(5)
        
        if sou_master or em_eleicao:
            continue
            
        try: 
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect((host_master, PORT))
            
            s.sendall("Ta vivo ?".encode())
            
            resp = s.recv(1024)
            if resp:
                print(f"Master ({host_master}) está vivo!")
                erros_conexao = 0
            s.close()
            
        except Exception as a:
            erros_conexao += 1
            print(f"Erro de conexão com o master - tentativa {erros_conexao}")
            
            if erros_conexao >= 4:
                iniciar_eleicao()

# Inicia as três funções simultaneamente
threading.Thread(target=escutar_eleicao_udp, daemon=True).start()
threading.Thread(target=escutar_heartbeat_tcp, daemon=True).start()
time.sleep(1)
hertbeat()