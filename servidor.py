import socket

HOST = '10.62.206.46' # Endereço IP local (localhost)
PORT = 8000        # Porta específica exigida no requisito

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