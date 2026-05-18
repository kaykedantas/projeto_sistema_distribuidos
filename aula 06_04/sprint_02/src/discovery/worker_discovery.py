
import json
import socket
import uuid
import time
import os
import struct


def make_discovery_message(worker_id=None, hostname=None, reply_port=None):
    payload = {
        'type': 'discovery',
        'version': 1,
        'worker_id': worker_id or str(uuid.uuid4()),
        'hostname': hostname or socket.gethostname()
    }
    if reply_port is not None:
        payload['reply_port'] = int(reply_port)
    return json.dumps(payload).encode('utf-8')


def parse_response(data_bytes):
    return json.loads(data_bytes.decode('utf-8'))


def discover_masters(timeout_ms=3000, group='239.255.0.1', port=50000, mode='multicast'):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # bind to ephemeral port to receive replies
    s.bind(('', 0))
    reply_port = s.getsockname()[1]
    msg = make_discovery_message(reply_port=reply_port)

    if mode == 'multicast':
        ttl = int(os.getenv('DISCOVERY_TTL', '1'))
        try:
            # prefer packed byte for TTL
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, struct.pack('b', ttl))
        except Exception:
            try:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
            except Exception:
                pass
        try:
            s.sendto(msg, (group, port))
        except Exception:
            pass
    else:
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except Exception:
            pass
        try:
            s.sendto(msg, ('255.255.255.255', port))
        except Exception:
            pass

    responses = []
    end = time.time() + (timeout_ms / 1000.0)
    while True:
        remaining = end - time.time()
        if remaining <= 0:
            break
        s.settimeout(remaining)
        try:
            data, addr = s.recvfrom(4096)
            try:
                parsed = parse_response(data)
                parsed['_from'] = addr
                responses.append(parsed)
            except Exception:
                continue
        except socket.timeout:
            break
        except Exception:
            continue
    try:
        s.close()
    except Exception:
        pass
    return responses
