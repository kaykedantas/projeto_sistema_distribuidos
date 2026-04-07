
import socket 
import time 
host = '10.62.206.46'
PORT = 8000

def hertbeat():
    while True: 
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        menssagem = f"Ta vivo ?"
        s.connect((host,PORT))

        try: 
            while True:  
                s.sendall(menssagem.encode())
                print("Mensagem enviada com sucesso")
                time.sleep(10)
        except Exception as a:
            print(f"Erro:{a}")
        finally:
            s.close()

hertbeat()
    
#time.sleep(5)
