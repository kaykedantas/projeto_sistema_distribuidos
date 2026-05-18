import socket
import json
import struct
import threading
import uuid
import time


class MasterResponder:
    def __init__(self, group='239.255.0.1', port=50000, mode='multicast', tcp_port=50010, master_name=None):
        self.group = group
        self.port = port
        self.mode = mode
        self.tcp_port = tcp_port
        self.master_name = master_name or f"MASTER_{str(uuid.uuid4())[:8]}"
        self.master_id = str(uuid.uuid4())
        self._sock = None
        self._tcp_sock = None
        self._running = False
        self._tcp_running = False

    def start(self):
        self._running = True
        # UDP listener
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

        # TCP server for election/handshake
        try:
            self._tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._tcp_sock.bind(('', self.tcp_port))
            self._tcp_sock.listen(5)
            self._tcp_running = True
            self._tcp_thread = threading.Thread(target=self._tcp_accept_loop, daemon=True)
            self._tcp_thread.start()
        except Exception:
            # if TCP cannot bind, mark tcp as not running
            self._tcp_running = False

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
            # Accept both lower-case and upper-case discovery indicators
            msg_type = msg.get('type') or msg.get('TYPE')
            if not msg_type or msg_type.lower() != 'discovery':
                continue
            reply_port = msg.get('reply_port') or msg.get('REPLY_PORT') or addr[1]
            resp = {
                # both formats for compatibility
                'type': 'discovery_response',
                'TYPE': 'DISCOVERY_REPLY',
                'version': 1,
                'master_id': self.master_id,
                'MASTER_ID': self.master_id,
                'MASTER_NAME': self.master_name,
                'master_name': self.master_name,
                'MASTER_PORT': self.tcp_port,
                'master_port': self.tcp_port,
                'hostname': socket.gethostname(),
                'ip': addr[0]
            }
            try:
                self._sock.sendto(json.dumps(resp).encode('utf-8'), (addr[0], reply_port))
            except Exception:
                pass

    def _tcp_accept_loop(self):
        while self._tcp_running:
            try:
                client, addr = self._tcp_sock.accept()
            except Exception:
                time.sleep(0.01)
                continue
            threading.Thread(target=self._handle_tcp_client, args=(client, addr), daemon=True).start()

    def _handle_tcp_client(self, client, addr):
        try:
            f = client.makefile('rwb')
            line = f.readline()
            if not line:
                client.close()
                return
            try:
                msg = json.loads(line.decode('utf-8').strip())
            except Exception:
                client.close()
                return
            msg_type = msg.get('TYPE') or msg.get('type')
            if msg_type and msg_type.upper() == 'ELECTION':
                # send ELECTION_ACK
                ack = {
                    'TYPE': 'ELECTION_ACK',
                    'type': 'election_ack',
                    'STATUS': 'ACCEPTED',
                    'status': 'accepted',
                    'MASTER_NAME': self.master_name,
                    'MASTER_ID': self.master_id
                }
                try:
                    f.write((json.dumps(ack) + '\n').encode('utf-8'))
                    f.flush()
                except Exception:
                    pass
        finally:
            try:
                client.close()
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
