"""Checking what the phone's passkey sends back.

Pairing: the phone creates a passkey and sends its public key. Unlocking:
the laptop hands out a one-time challenge, the phone signs it after Face ID,
and the signature is checked here against the public key from pairing.

Only ES256 (P-256) keys, which is what iPhones and every other passkey
provider use. Every check that matters is here, so this is the file to read
to judge whether Tessera is safe:

  * the signed data must be for this site (rpIdHash) and this page (origin)
  * it must answer a challenge this laptop handed out and hasn't seen back
  * the passkey must report that Face ID (user verification) was done
  * the signature must verify with the paired public key
"""

import base64
import hashlib
import json
import struct

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from . import cbor

FLAG_UP = 0x01   # user present: someone confirmed
FLAG_UV = 0x04   # user verified: Face ID (or the phone's passcode) passed
FLAG_AT = 0x40   # attested credential data follows (only when creating)


class Refused(Exception):
    """The answer is not acceptable. The message says why, for the log."""


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64url(text):
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError):
        raise Refused("not base64") from None


def parse_auth_data(data):
    if len(data) < 37:
        raise Refused("authenticator data too short")
    out = {"rp_id_hash": data[:32], "flags": data[32], "sign_count": struct.unpack(">I", data[33:37])[0]}
    if out["flags"] & FLAG_AT:
        if len(data) < 55:
            raise Refused("credential data too short")
        id_len = struct.unpack(">H", data[53:55])[0]
        cred_id = data[55:55 + id_len]
        if len(cred_id) != id_len:
            raise Refused("credential id truncated")
        try:
            key, _used = cbor.decode(data[55 + id_len:])
        except cbor.CBORError as e:
            raise Refused(f"public key unreadable: {e}") from None
        out["credential_id"] = cred_id
        out["cose_key"] = key
    return out


def cose_to_pem(key):
    """A COSE EC2 P-256 key (from the passkey) as PEM text."""
    if not isinstance(key, dict) or key.get(1) != 2 or key.get(3) != -7 or key.get(-1) != 1:
        raise Refused("only P-256 / ES256 passkeys are supported")
    x, y = key.get(-2), key.get(-3)
    if not (isinstance(x, bytes) and isinstance(y, bytes) and len(x) == 32 and len(y) == 32):
        raise Refused("bad public key")
    try:
        public = ec.EllipticCurvePublicNumbers(int.from_bytes(x, "big"), int.from_bytes(y, "big"),
                                               ec.SECP256R1()).public_key()
    except ValueError:
        raise Refused("public key isn't on the curve") from None
    return public.public_bytes(serialization.Encoding.PEM,
                               serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def _client_data(raw, kind, challenge, origin):
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise Refused("client data isn't JSON") from None
    if data.get("type") != kind:
        raise Refused(f"wrong type {data.get('type')!r}")
    if data.get("origin") != origin:
        raise Refused(f"wrong origin {data.get('origin')!r}")
    if data.get("crossOrigin"):
        raise Refused("cross-origin request")
    if unb64url(data.get("challenge", "")) != challenge:
        raise Refused("challenge doesn't match")
    return data


def _check_flags(auth, rp_id):
    if auth["rp_id_hash"] != hashlib.sha256(rp_id.encode()).digest():
        raise Refused("signed for a different site")
    if not auth["flags"] & FLAG_UP:
        raise Refused("nobody confirmed")
    if not auth["flags"] & FLAG_UV:
        raise Refused("Face ID wasn't used")


def verify_registration(client_data_json, attestation_object, challenge, rp_id, origin):
    """Check a new passkey. Returns (credential id, public key PEM, sign count)."""
    _client_data(client_data_json, "webauthn.create", challenge, origin)
    try:
        att = cbor.loads(attestation_object)
    except cbor.CBORError as e:
        raise Refused(f"attestation unreadable: {e}") from None
    if not isinstance(att, dict) or not isinstance(att.get("authData"), bytes):
        raise Refused("attestation has no authenticator data")
    auth = parse_auth_data(att["authData"])
    _check_flags(auth, rp_id)
    if "credential_id" not in auth:
        raise Refused("no new credential in the answer")
    # Attestation (who made the authenticator) isn't checked: iPhones send
    # "none", and what matters here is the key, which we pin from now on.
    return auth["credential_id"], cose_to_pem(auth["cose_key"]), auth["sign_count"]


def verify_assertion(public_pem, stored_count, auth_data, client_data_json, signature, challenge, rp_id, origin):
    """Check a Face ID signature. Returns the new sign count."""
    _client_data(client_data_json, "webauthn.get", challenge, origin)
    auth = parse_auth_data(auth_data)
    _check_flags(auth, rp_id)
    public = serialization.load_pem_public_key(public_pem.encode())
    signed = auth_data + hashlib.sha256(client_data_json).digest()
    try:
        public.verify(signature, signed, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        raise Refused("signature doesn't verify") from None
    # Synced passkeys (iCloud Keychain) always report 0. Any other counter
    # must go up, or this may be a copied key.
    count = auth["sign_count"]
    if (count or stored_count) and count <= stored_count:
        raise Refused("signature counter went backwards")
    return count


def pairing_code(challenge, credential_id):
    """Four digits both screens show while pairing, so you can tell your
    phone's passkey from one someone else sent at the same moment."""
    digest = hashlib.sha256(challenge + credential_id).digest()
    return f"{int.from_bytes(digest[:4], 'big') % 10000:04d}"
