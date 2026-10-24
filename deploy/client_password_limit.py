"""Exact idempotent 16 -> 64 password-edit patch for the current native image."""
import hashlib
BASE_SHA = '717d89cd25912d593ac9b6cf0f593faac509f42d7572ccf63ba063f41cef9625'
PATCHED_SHA = '7fd0a3b221e6bd967faed999de90b77b54f04ec16864fc4ea85d19b6d68fbe96'

def patch(data):
    digest = hashlib.sha256(data).hexdigest()
    if digest == PATCHED_SHA: return data
    if digest != BASE_SHA or data[0x47e1b8:0x47e1bf] != bytes.fromhex('c6838002000010'):
        raise ValueError('Unsupported password-edit client image')
    result = bytearray(data); result[0x47e1be] = 64
    assert hashlib.sha256(result).hexdigest() == PATCHED_SHA
    return bytes(result)
