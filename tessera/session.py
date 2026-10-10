"""Unlocking this desktop session.

Lock screens (Cinnamon, GNOME, KDE, and others built on logind) listen for
logind's Unlock signal. `loginctl unlock-session` sends it, and a user may
do that for their own session without a password: the same permission a
screen locker uses.
"""

import os
import subprocess


def graphical_session():
    """The id of this user's graphical session."""
    sid = os.environ.get("XDG_SESSION_ID")
    if sid:
        return sid
    out = subprocess.run(["loginctl", "list-sessions", "--no-legend"], capture_output=True, text=True).stdout
    me = str(os.getuid())
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1] == me and parts[3].startswith("seat"):
            return parts[0]
    return None


def unlock():
    sid = graphical_session()
    if sid is None:
        raise RuntimeError("couldn't find the desktop session")
    subprocess.run(["loginctl", "unlock-session", sid], check=True, capture_output=True, timeout=10)


def laptop_name():
    """What the phone calls this laptop."""
    try:
        with open("/sys/class/dmi/id/product_name") as f:
            product = f.read().strip()
    except OSError:
        product = ""
    if product and product.lower() not in ("", "to be filled by o.e.m.", "system product name"):
        return product
    return os.uname().nodename


def address():
    """How the phone reaches this laptop on the local network: its .local name."""
    return os.uname().nodename.lower() + ".local"
