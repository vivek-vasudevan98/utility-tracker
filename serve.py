"""
Starts Utility Tracker on this computer and opens it in the browser.
If it is already running, just opens the browser.

    python serve.py          start (or open)
    python serve.py --stop   stop the running copy

Uses the Waitress web server and listens on 127.0.0.1 only, so the app is
reachable from this computer and no other.
"""
import os
import sys
import threading
import time
import urllib.request
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get('UTILITY_TRACKER_PORT', '8765'))
URL = f'http://127.0.0.1:{PORT}/'


def data_dir():
    """The Windows install keeps data in ..\\data next to the program; a checkout uses instance/."""
    if os.environ.get('UTILITY_TRACKER_DATA'):
        return os.environ['UTILITY_TRACKER_DATA']
    parent = os.path.dirname(HERE)
    if os.path.isdir(os.path.join(parent, 'python')):
        return os.path.join(parent, 'data')
    return os.path.join(HERE, 'instance')


DATA = data_dir()
PID_FILE = os.path.join(DATA, 'server.pid')
LOG_FILE = os.path.join(DATA, 'server.log')


def notify(message: str):
    """A message the user can see even without a console window (pythonw)."""
    print(message)
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, 'Utility Tracker', 0x40)
        except Exception:
            pass


def already_running() -> bool:
    # Bypass any system proxy: this is a request to this computer
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(URL + 'healthz', timeout=2) as response:
            return response.read().decode().strip() == 'utility-tracker'
    except Exception:
        return False


def stop():
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        print('Utility Tracker is not running.')
        return
    try:
        import signal
        os.kill(pid, signal.SIGTERM)
        print('Utility Tracker stopped.')
    except OSError:
        print('Utility Tracker was not running.')
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


def start():
    if already_running():
        webbrowser.open(URL)
        return

    os.makedirs(DATA, exist_ok=True)
    os.environ['UTILITY_TRACKER_DATA'] = DATA
    # Without a console window (pythonw) there is nowhere to print: keep a log
    if sys.stdout is None or os.path.basename(sys.executable).lower() == 'pythonw.exe':
        log = open(LOG_FILE, 'a', buffering=1, encoding='utf-8')
        sys.stdout = sys.stderr = log
    print(f"\n{time.strftime('%Y-%m-%d %H:%M:%S')} starting Utility Tracker on {URL}")

    try:
        from waitress import create_server
        from utility_app import create_app
        server = create_server(create_app(), host='127.0.0.1', port=PORT, threads=4)
    except OSError as e:
        notify(f"Utility Tracker couldn't start: port {PORT} is in use by another program.\n\n{e}")
        return
    except Exception as e:
        notify(f"Utility Tracker couldn't start:\n\n{e}\n\nDetails are in {LOG_FILE}")
        raise

    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))
    threading.Timer(0.5, webbrowser.open, args=(URL,)).start()
    try:
        server.run()
    finally:
        try:
            os.remove(PID_FILE)
        except OSError:
            pass


if __name__ == '__main__':
    stop() if '--stop' in sys.argv[1:] else start()
