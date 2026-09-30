import socket
import unittest
from workos.server import LocalServer,Handler

class PortIsolationTests(unittest.TestCase):
 def test_exclusive_listener_cannot_shadow_wildcard_service(self):
  sock=socket.socket()
  if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):
   sock.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
  sock.bind(('0.0.0.0',0));sock.listen(1)
  port=sock.getsockname()[1]
  try:
   with self.assertRaises(OSError):LocalServer(('127.0.0.1',port),Handler)
  finally:sock.close()

if __name__=='__main__':unittest.main()
