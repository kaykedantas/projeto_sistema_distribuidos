
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


def _get_field(obj, *keys):
    for k in keys:
        if k in obj:
            return obj[k]
    return None


def elect_master(responses, worker_uuid=None, tcp_timeout=2.0):
    """
    Determine selected master by deterministic lexicographic rule and perform TCP election handshake.
    Returns dict with selected master info on success, or None on failure.
    """
    if not responses:
        return None
    # Extract candidate names with original response
    candidates = []
    for r in responses:
        name = _get_field(r, 'MASTER_NAME', 'master_name', 'hostname', 'master_id')
        if name is None:
            # fallback to master_id or hostname
            name = _get_field(r, 'master_id', 'hostname')
        if name is None:
            continue
        candidates.append((str(name), r))

    if not candidates:
        return None

    # Deterministic lexicographic selection (ascending)
    candidates.sort(key=lambda x: x[0])
    selected_name, selected_resp = candidates[0]

    # Determine IP and TCP port to connect
    ip = _get_field(selected_resp, 'ip') or (selected_resp.get('_from')[0] if selected_resp.get('_from') else None)
    port = _get_field(selected_resp, 'MASTER_PORT') or _get_field(selected_resp, 'master_port') or _get_field(selected_resp, 'master_port')
    try:
        port = int(port)
    except Exception:
        port = None

    if not ip or not port:
        return None

    # TCP handshake: send ELECTION and expect ELECTION_ACK
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(tcp_timeout)
        s.connect((ip, port))
        payload = {
            'TYPE': 'ELECTION',
            'WORKER_UUID': worker_uuid or str(uuid.uuid4()),
            'SELECTED_MASTER': selected_name
        }
        s.sendall((json.dumps(payload) + '\n').encode('utf-8'))
        # read response until newline
        f = s.makefile('rb')
        line = f.readline()
        if not line:
            s.close()
            return None
        try:
            resp = json.loads(line.decode('utf-8').strip())
        except Exception:
            s.close()
            return None
        resp_type = _get_field(resp, 'TYPE', 'type')
        status = _get_field(resp, 'STATUS', 'status')
        if resp_type and str(resp_type).upper() == 'ELECTION_ACK' and str(status).upper() == 'ACCEPTED':
            s.close()
            result = {'selected_name': selected_name, 'selected_response': selected_resp, 'master_ip': ip, 'master_port': port}
            return result
    except Exception:
        return None
    return None


def perform_discovery_and_election(timeout_ms=3000, group='239.255.0.1', port=50000, mode='multicast', worker_uuid=None):
    responses = discover_masters(timeout_ms=timeout_ms, group=group, port=port, mode=mode)
    election = elect_master(responses, worker_uuid=worker_uuid)
    return election
