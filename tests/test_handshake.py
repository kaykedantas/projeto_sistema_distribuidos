from unittest.mock import MagicMock, patch
from src.handshake import perform_handshake

def test_perform_handshake_accept():
    fake_sock = MagicMock()
    fake_sock.recv.return_value = b'{"TYPE":"ELECTION_ACK","STATUS":"ACCEPTED","MASTER_NAME":"MASTER_1"}'
    with patch('socket.create_connection', return_value=fake_sock):
        ok = perform_handshake('127.0.0.1', 6000, 'W-101', 'MASTER_1')
        assert ok is True
