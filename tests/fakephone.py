"""A pretend iPhone passkey, for tests: makes the same bytes a real one does."""

import hashlib
import json
import os
import struct

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from tessera.webauthn import FLAG_AT, FLAG_UP, FLAG_UV, b64url


def cbor(value):
    """A tiny CBOR encoder, enough for attestation objects."""
    def head(major, n):
        if n < 24:
            return bytes([major << 5 | n])
        for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
            if n < 1 << (8 * size):
                return bytes([major << 5 | info]) + n.to_bytes(size, "big")
    if isinstance(value, bool):
        return bytes([0xF5 if value else 0xF4])
    if isinstance(value, int):
        return head(0, value) if value >= 0 else head(1, -1 - value)
    if isinstance(value, bytes):
        return head(2, len(value)) + value
    if isinstance(value, str):
        raw = value.encode()
        return head(3, len(raw)) + raw
    if isinstance(value, list):
        return head(4, len(value)) + b"".join(cbor(v) for v in value)
    if isinstance(value, dict):
        return head(5, len(value)) + b"".join(cbor(k) + cbor(v) for k, v in value.items())
    raise TypeError(value)


class FakePhone:
    def __init__(self, rp_id="beansasset.github.io", origin="https://beansasset.github.io"):
        self.rp_id, self.origin = rp_id, origin
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(20)
        self.count = 0

    def _auth(self, flags, extra=b""):
        return hashlib.sha256(self.rp_id.encode()).digest() + bytes([flags]) + struct.pack(">I", self.count) + extra

    def _client(self, kind, challenge, origin=None):
        return json.dumps({"type": kind, "challenge": b64url(challenge),
                           "origin": origin or self.origin, "crossOrigin": False}).encode()

    def create(self, challenge, flags=FLAG_UP | FLAG_UV):
        n = self.key.public_key().public_numbers()
        cose = {1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")}
        cred = bytes(16) + struct.pack(">H", len(self.credential_id)) + self.credential_id + cbor(cose)
        auth = self._auth(flags | FLAG_AT, cred)
        att = cbor({"fmt": "none", "attStmt": {}, "authData": auth})
        return self._client("webauthn.create", challenge), att

    def sign(self, challenge, flags=FLAG_UP | FLAG_UV, origin=None):
        auth = self._auth(flags)
        client = self._client("webauthn.get", challenge, origin)
        sig = self.key.sign(auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
        return auth, client, sig
