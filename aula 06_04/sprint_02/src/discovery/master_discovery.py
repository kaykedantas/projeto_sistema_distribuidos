import socket
import json
import struct
import threading


class MasterResponder:
    def __init__(self, group='239.255.0.1', port=50000, mode='multicast'):
        self.group = group
        self.port = port
        self.mode = mode
        self._sock = None
        self._running = False

    def start(self):
        self._running = True
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._sock.bind(('', self.port))
        except Exception:
            self._sock.bind(('', 0))
        if self.mode == 'multicast':
            try:
                mreq = struct.pack('4sL', socket.inet_aton(self.group), socket.INADDR_ANY)
                self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            except Exception:
                pass
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while self._running:
            try:
                data, addr = self._sock.recvfrom(4096)
            except Exception:
                continue
            try:
                msg = json.loads(data.decode('utf-8'))
            except Exception:
                continue
            if msg.get('type') != 'discovery':
                continue
            reply_port = msg.get('reply_port') or addr[1]
            resp = {
                'type': 'discovery_response',
                'version': 1,
                'master_id': 'master-local-1',
                'hostname': socket.gethostname()
            }
            try:
                self._sock.sendto(json.dumps(resp).encode('utf-8'), (addr[0], reply_port))
            except Exception:
                pass

    def stop(self):
        self._running = False
        try:
            self._sock.close()
        except Exception:
            pass
        if hasattr(self, '_thread'):
            self._thread.join(timeout=1)
