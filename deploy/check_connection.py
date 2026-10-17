"""Read the original encrypted TIO challenge. Does not authenticate or change saves."""
import argparse
from pathlib import Path
import socket
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tio.protocol.transport import InitialCipher, InitialFrameReader, decode_initial_challenge


def check(host, port):
    with socket.create_connection((host, port), timeout=5) as connection:
        reader = InitialFrameReader(InitialCipher('S2C'))
        while True:
            data = connection.recv(1024)
            if not data:
                raise RuntimeError('Disconnected before TIO challenge')
            packets = reader.feed(data)
            if packets:
                decode_initial_challenge(packets[0])
                print(f'TIO transport challenge OK: {host}:{port}/TCP (not a full game-login test)')
                return


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--port', type=int, default=28512)
    args = parser.parse_args()
    check(args.host, args.port)
