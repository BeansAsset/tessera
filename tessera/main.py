"""Tessera: unlock this laptop with Face ID on your iPhone.

    tessera-app                 open the window (pair an iPhone, see paired ones)
    tessera-app --background    just run the service (used at login)

Only one Tessera runs. The service listens on the local network for the
two shortcuts on the phone; every answer is checked in gate.py and
webauthn.py before anything is unlocked. Your password keeps working as
always: Tessera only adds a second way in.
"""

import base64
import os
import sys
import time

from .bridge import DEBUG, WebWindow  # sets up GTK and WebKit versions

from gi.repository import Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, APP_NAME, PAGE, PORT, gate, server, session  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ICON = os.path.join(os.path.dirname(HERE), "data", APP_ID + ".svg")
CONFIG = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "tessera")


def log(*parts):
    print("tessera:", *parts, flush=True)


def qr_data_uri(text):
    """A QR code as an SVG data address, for the window to show."""
    import qrcode
    import qrcode.image.svg
    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathFillImage, border=2)
    svg = img.to_string()
    return "data:image/svg+xml;base64," + base64.b64encode(svg).decode()


class Window(WebWindow):
    page = "window.html"

    def __init__(self, app):
        super().__init__(app, background=(0.063, 0.063, 0.071, 1), title=APP_NAME)
        self.set_default_size(560, 720)
        if os.path.exists(ICON):
            self.set_icon_from_file(ICON)
        self.connect("destroy", lambda *_: app.window_closed())

    def cmd_ready(self, _id):
        self.page_ready = True
        return self.app.state()

    def cmd_pair(self, _id):
        self.app.gate.start_pairing()
        self.app.changed()
        return True

    def cmd_cancel(self, _id):
        self.app.gate.stop_pairing()
        self.app.pair_code = None
        self.app.changed()
        return True

    def cmd_confirm(self, _id, code):
        ok = self.app.gate.confirm(code)
        self.app.pair_code = None
        self.app.changed()
        return ok

    def cmd_remove(self, _id, device_id):
        self.app.gate.remove(device_id)
        self.app.changed()
        return True


class Application(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.window = None
        self.gate = None
        self.server = None
        self.error = None
        self.pair_code = None
        self.address = session.address()
        self.name = session.laptop_name()

    def do_startup(self):
        Gtk.Application.do_startup(self)
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
        self.hold()   # keep listening with no window open
        self.gate = gate.Gate(os.path.join(CONFIG, "devices.json"),
                              on_unlock=lambda d: GLib.idle_add(self._unlocked, d),
                              on_pair_request=lambda code: GLib.idle_add(self._pair_request, code))
        try:
            self.server = server.Server(self.gate, PORT, self.name, log=log if DEBUG else (lambda *_: None))
            self.server.start()
        except OSError as e:
            self.error = f"Couldn't listen on port {PORT}: {e.strerror or e}."
            log(self.error)
        GLib.timeout_add_seconds(1, self._tick)

    def do_command_line(self, command_line):
        if "--background" not in command_line.get_arguments()[1:]:
            self.open_window()
        return 0

    def open_window(self):
        if self.window is None:
            self.window = Window(self)
            self.window.show_all()
        self.window.present()

    def window_closed(self):
        self.window = None

    # -- state for the window ------------------------------------------------------------

    def state(self):
        remaining = max(0, int(self.gate.pairing_until - time.monotonic())) if self.gate.pairing else 0
        return {
            "name": self.name,
            "address": f"{self.address}:{PORT}",
            "devices": self.gate.device_list(),
            "pairing": remaining,
            "code": self.pair_code,
            "error": self.error,
            "setup_qr": qr_data_uri(f"{PAGE}#setup={self.address}:{PORT}"),
        }

    def changed(self):
        if self.window is not None:
            self.window.emit("state", self.state())

    def _tick(self):
        # Keep the pairing countdown moving, and notice when it runs out.
        if self.window is not None and (self.gate.pairing or self.pair_code):
            if not self.gate.pairing:
                self.pair_code = None
            self.changed()
        return True

    # -- from the phone ------------------------------------------------------------------

    def _unlocked(self, device):
        try:
            session.unlock()
        except (RuntimeError, OSError) as e:
            self.notify("Tessera couldn't unlock", str(e))
            return False
        self.notify("Unlocked with Face ID", f"From {device.get('name') or 'your iPhone'} at {time.strftime('%H:%M')}.")
        self.changed()
        return False

    def _pair_request(self, code):
        self.pair_code = code
        self.open_window()
        self.changed()
        return False

    def notify(self, title, body):
        note = Gio.Notification.new(title)
        if os.path.exists(ICON):
            note.set_icon(Gio.FileIcon.new(Gio.File.new_for_path(ICON)))
        note.set_body(body)
        self.send_notification(None, note)


def main():
    return Application().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
