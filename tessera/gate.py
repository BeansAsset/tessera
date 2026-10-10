"""The paired devices, the one-time challenges, and the decision to unlock.

Thread-safe: the web server calls in from its own threads.
"""

import json
import os
import secrets
import threading
import time
import urllib.parse

from . import ORIGIN, PAGE, RP_ID, webauthn
from .webauthn import Refused, b64url, unb64url

CHALLENGE_LIFE = 120     # seconds to finish Face ID after starting
MAX_OPEN = 8             # outstanding challenges kept at once
PAIRING_LIFE = 180       # seconds pairing stays open after pressing Pair


class Gate:
    def __init__(self, path, on_unlock, on_pair_request, now=time.monotonic):
        self.path = path
        self.on_unlock = on_unlock                 # on_unlock(device)
        self.on_pair_request = on_pair_request     # on_pair_request(code)
        self.now = now
        self.lock = threading.Lock()
        self.devices = self._load()
        self.open = {}               # challenge bytes -> (kind, expiry)
        self.pairing_until = 0.0
        self.pending = None          # a new passkey waiting for the code to be confirmed

    # -- devices ------------------------------------------------------------------------

    def _load(self):
        try:
            with open(self.path) as f:
                data = json.load(f)
            return data.get("devices", []) if isinstance(data, dict) else []
        except (OSError, ValueError):
            return []

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"devices": self.devices}, f, indent=2)
        os.replace(tmp, self.path)

    def device_list(self):
        with self.lock:
            return [{k: d.get(k) for k in ("id", "name", "added", "last_used")} for d in self.devices]

    def remove(self, device_id):
        with self.lock:
            self.devices = [d for d in self.devices if d["id"] != device_id]
            self._save()

    # -- challenges ----------------------------------------------------------------------

    def _issue(self, kind):
        now = self.now()
        self.open = {c: v for c, v in self.open.items() if v[1] > now}
        if len(self.open) >= MAX_OPEN:          # someone is asking a lot: drop the oldest
            oldest = min(self.open, key=lambda c: self.open[c][1])
            del self.open[oldest]
        challenge = secrets.token_bytes(32)
        self.open[challenge] = (kind, now + CHALLENGE_LIFE)
        return challenge

    def _take(self, challenge, kind):
        """Use up a challenge: each one is good for exactly one answer."""
        entry = self.open.pop(challenge, None)
        if entry is None or entry[1] <= self.now():
            raise Refused("unknown or expired challenge")
        if entry[0] != kind:
            raise Refused("challenge was for something else")

    # -- the two requests from the phone ------------------------------------------------

    def start_pairing(self):
        with self.lock:
            self.pairing_until = self.now() + PAIRING_LIFE
            self.pending = None

    def stop_pairing(self):
        with self.lock:
            self.pairing_until = 0.0
            self.pending = None

    @property
    def pairing(self):
        return self.now() < self.pairing_until

    def start(self, laptop_name):
        """What the phone's shortcut opens: the page, with a fresh challenge.
        A new query each time makes Safari load the page afresh instead of
        reusing a tab that has the page open already."""
        with self.lock:
            page = f"{PAGE}?{secrets.token_hex(4)}"
            name = urllib.parse.quote(laptop_name)
            if self.pairing:
                c = self._issue("pair")
                return f"{page}#pair={b64url(c)}&laptop={name}"
            if not self.devices:
                return f"{page}#error=" + urllib.parse.quote(
                    "This iPhone isn't paired yet. Open Tessera on your laptop and press Pair.")
            c = self._issue("unlock")
            keys = ",".join(d["id"] for d in self.devices)
            return f"{page}#c={b64url(c)}&k={keys}&laptop={name}"

    def answer(self, text):
        """The phone's reply. Returns a short message for the phone."""
        parts = text.strip().split(".")
        if len(parts) == 5 and parts[0] == "u":
            return self._unlock(*(unb64url(p) for p in parts[1:]))
        if len(parts) == 4 and parts[0] == "p":
            return self._pair(*(unb64url(p) for p in parts[1:]))
        raise Refused("unrecognised answer")

    def _challenge_in(self, client_data_json):
        try:
            return unb64url(json.loads(client_data_json)["challenge"])
        except (ValueError, KeyError, TypeError):
            raise Refused("no challenge in the answer") from None

    def _unlock(self, cred_id, auth_data, client_data_json, signature):
        with self.lock:
            challenge = self._challenge_in(client_data_json)
            self._take(challenge, "unlock")
            device = next((d for d in self.devices if d["id"] == b64url(cred_id)), None)
            if device is None:
                raise Refused("that passkey isn't paired with this laptop")
            count = webauthn.verify_assertion(device["public_key"], device.get("count", 0), auth_data,
                                              client_data_json, signature, challenge, RP_ID, ORIGIN)
            device["count"] = count
            device["last_used"] = int(time.time())
            self._save()
            found = dict(device)
        self.on_unlock(found)
        return "Unlocked"

    def _pair(self, cred_id, client_data_json, attestation):
        with self.lock:
            if not self.pairing:
                raise Refused("pairing isn't open on the laptop")
            challenge = self._challenge_in(client_data_json)
            self._take(challenge, "pair")
            got_id, pem, count = webauthn.verify_registration(client_data_json, attestation, challenge,
                                                              RP_ID, ORIGIN)
            if got_id != cred_id:
                raise Refused("credential id doesn't match")
            code = webauthn.pairing_code(challenge, got_id)
            self.pending = {"id": b64url(got_id), "public_key": pem, "count": count, "code": code}
        self.on_pair_request(code)
        return "Almost done: confirm the code on your laptop."

    def confirm(self, code, name="iPhone"):
        """The person checked the code on both screens. Returns True if paired."""
        with self.lock:
            p = self.pending
            if not p or p["code"] != code or not self.pairing:
                return False
            self.devices = [d for d in self.devices if d["id"] != p["id"]]
            self.devices.append({"id": p["id"], "name": name, "public_key": p["public_key"],
                                 "count": p["count"], "added": int(time.time()), "last_used": None})
            self._save()
            self.pending = None
            self.pairing_until = 0.0
            return True
