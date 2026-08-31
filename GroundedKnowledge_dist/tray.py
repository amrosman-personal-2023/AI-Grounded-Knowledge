"""GND tray icon — starts/stops the uvicorn server and opens the UI."""
import os
import subprocess
import sys
import time
import threading
import webbrowser

import rumps

HERE = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable
PORT = 8787
URL = f"http://localhost:{PORT}"

ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
GND_MODEL = os.environ.get("SEISMIC_CHAT_MODEL", "claude-sonnet-4-5")


def _server_env():
    env = os.environ.copy()
    env["ANTHROPIC_BASE_URL"] = ANTHROPIC_BASE_URL
    env["SEISMIC_CHAT_MODEL"] = GND_MODEL
    return env


def _is_running():
    import urllib.request, urllib.error
    try:
        urllib.request.urlopen(URL, timeout=2)
        return True
    except Exception:
        return False


class GNDApp(rumps.App):
    def __init__(self):
        super().__init__("GND", quit_button=None)
        self._proc = None
        self._update_icon(running=False)

        self.open_item = rumps.MenuItem("Open GND", callback=self.open_browser)
        self.toggle_item = rumps.MenuItem("Start server", callback=self.toggle_server)
        self.quit_item = rumps.MenuItem("Quit", callback=self.quit_app)

        self.menu = [self.open_item, self.toggle_item, None, self.quit_item]

        # Auto-start server on launch
        threading.Thread(target=self._start_server, daemon=True).start()

    # ------------------------------------------------------------------ helpers

    def _update_icon(self, running):
        self.title = "● GND" if running else "○ GND"

    def _start_server(self):
        if _is_running():
            self._update_icon(running=True)
            self.toggle_item.title = "Stop server"
            return

        self._proc = subprocess.Popen(
            [PYTHON, "-m", "uvicorn", "app:app",
             "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "info"],
            cwd=HERE,
            env=_server_env(),
            stdout=open(os.path.join(HERE, "server.log"), "a"),
            stderr=subprocess.STDOUT,
        )

        # Wait up to 10 s for the server to become reachable
        for _ in range(20):
            time.sleep(0.5)
            if _is_running():
                break

        running = _is_running()
        self._update_icon(running=running)
        self.toggle_item.title = "Stop server" if running else "Start server (failed — check server.log)"

    def _stop_server(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
        self._update_icon(running=False)
        self.toggle_item.title = "Start server"

    # ------------------------------------------------------------------ menu callbacks

    def open_browser(self, _):
        webbrowser.open(URL)

    def toggle_server(self, _):
        if _is_running():
            threading.Thread(target=self._stop_server, daemon=True).start()
        else:
            self.toggle_item.title = "Starting…"
            threading.Thread(target=self._start_server, daemon=True).start()

    def quit_app(self, _):
        self._stop_server()
        rumps.quit_application()


if __name__ == "__main__":
    GNDApp().run()
