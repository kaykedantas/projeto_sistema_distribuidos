"""
messaging.py — Serialização/desserialização do protocolo JSON sobre TCP.

Conforme o "Payload Padrão" do plano do projeto, toda mensagem trafega como
um objeto JSON terminado pelo caractere de nova linha (``\\n``). Esse
delimitador permite que o receptor saiba onde uma mensagem termina e a
próxima começa dentro do stream TCP.

Este módulo concentra a (de)serialização para que Master e Worker compartilhem
exatamente o mesmo formato de fio (wire format).
"""

import json
from typing import Any, Optional, Union

# Delimitador de mensagem exigido pelo protocolo do projeto.
DELIMITER = "\n"


def encode_message(obj: Any) -> bytes:
    """Serializa ``obj`` em JSON e acrescenta o delimitador ``\\n``.

    Retorna ``bytes`` prontos para serem escritos no socket.
    """
    data = json.dumps(obj, ensure_ascii=False)
    return (data + DELIMITER).encode("utf-8")


def decode_message(data: Union[bytes, str]) -> Any:
    """Converte uma linha JSON (com ou sem ``\\n``) em objeto Python."""
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return json.loads(data.strip())


# --- Helpers assíncronos usados pelo servidor (Master) e cliente (Worker) ---

async def send_message(writer, obj: Any) -> None:
    """Escreve uma mensagem JSON delimitada por ``\\n`` no ``StreamWriter``."""
    writer.write(encode_message(obj))
    await writer.drain()


async def read_message(reader) -> Optional[Any]:
    """Lê uma única mensagem (até o ``\\n``) do ``StreamReader``.

    Retorna ``None`` quando a conexão é encerrada (EOF) — assim o chamador
    consegue distinguir "conexão fechada" de "mensagem vazia".
    """
    line = await reader.readline()
    if not line:  # EOF: peer fechou a conexão
        return None
    return decode_message(line)
