"""Check encrypted phase ordering and reject an unexpected config reply."""
import socket
import threading
import unittest
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from tools.loopback_exchange import LoopbackExchange
from tio.protocol.transport import InitialCipher,InitialFrameReader,encode_initial_frame
from tio.protocol.shared_config import decode_shared_config_set,decode_shared_config_data


class SharedConfigDeliveryTests(unittest.TestCase):
    def exchange(self,bad_reply=False):
        with TemporaryDirectory() as directory:
            exchange=LoopbackExchange(Path(directory)/'trace.json')
            server,client=socket.socketpair();errors=[]
            def peer():
                try:
                    reader=InitialFrameReader(InitialCipher('S2C'))
                    outbound=InitialCipher('C2S')
                    _,packets=exchange.receive_frame(client,reader)
                    self.assertEqual(decode_shared_config_set(packets[0])[0].name_bytes,b'items')
                    client.sendall(encode_initial_frame(b'\xb9\x04' if bad_reply else b'\xb9\x02items\0',outbound))
                    if bad_reply:return
                    _,packets=exchange.receive_frame(client,reader)
                    data=decode_shared_config_data(packets[0])
                    xml=zlib.decompress(data.compressed_bytes)
                    self.assertEqual(len(xml),data.decompressed_size)
                    self.assertEqual(xml,(Path(__file__).resolve().parents[1]/'evidence/items_diagnostic.xml').read_bytes())
                    client.sendall(encode_initial_frame(b'\xb9\x04',outbound))
                except BaseException as exc:errors.append(exc)
                finally:client.close()
            thread=threading.Thread(target=peer);thread.start()
            try:
                if bad_reply:
                    with self.assertRaisesRegex(ValueError,'Unexpected shared config reply'):
                        exchange.deliver_shared_config(server,InitialFrameReader(InitialCipher('C2S')),InitialCipher('S2C'))
                else:
                    exchange.deliver_shared_config(server,InitialFrameReader(InitialCipher('C2S')),InitialCipher('S2C'))
                    self.assertEqual(exchange.events[-1]['event'],'shared_config_delivery_acknowledged')
            finally:
                server.close();exchange.listener.close();thread.join(6)
            self.assertFalse(thread.is_alive())
            if errors:raise errors[0]

    def test_order_and_compression(self):self.exchange()
    def test_reject_wrong_reply(self):self.exchange(True)
