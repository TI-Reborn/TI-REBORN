"""Offline application packet inspection; does not assume wire framing."""
import argparse
import json
from dataclasses import asdict
from .protocol.login import LSAuthResult, decode_ls_auth_result, encode_ls_auth_result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    decode = sub.add_parser('decode-auth-result')
    decode.add_argument('hex')
    encode = sub.add_parser('encode-auth-result')
    encode.add_argument('--status', type=lambda s:int(s,0), required=True)
    encode.add_argument('--unknown-u32-01', type=lambda s:int(s,0))
    args = parser.parse_args()
    try:
        if args.command == 'decode-auth-result':
            packet = decode_ls_auth_result(bytes.fromhex(args.hex))
            print(json.dumps({'layer':'application','name':'RECV_LSAuthResult',**asdict(packet)}))
        else:
            packet = LSAuthResult(args.status,args.unknown_u32_01)
            print(encode_ls_auth_result(packet).hex(' '))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
