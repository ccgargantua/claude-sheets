import fcntl
import hashlib
import os
import shutil
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .common import SheetError
from .watchdog import idle_for, kill_group, process_alive

REPO_STATE = Path(__file__).resolve().parents[2] / ".sheetcli"
WATCHDOG = Path(__file__).resolve().with_name("watchdog.py")
SOFFICE_FALLBACK = "/usr/lib/libreoffice/program/soffice"


def _env_float(name, default):
    return float(os.environ.get(name, default))


def state_dir():
    path = Path(os.environ.get("SHEETCLI_STATE_DIR") or REPO_STATE)
    path.mkdir(parents=True, exist_ok=True)
    return path


def pipe_name():
    name = f"sheetcli-{os.getuid()}"
    override = os.environ.get("SHEETCLI_STATE_DIR")
    if override:
        name += "-" + hashlib.sha1(str(Path(override).resolve()).encode()).hexdigest()[:8]
    return name


def _read_pid(state):
    try:
        return int((state / "pid").read_text())
    except (FileNotFoundError, ValueError):
        return None


def _touch(state):
    (state / "last_used").touch()


@contextmanager
def _serialized(state):
    deadline = time.time() + _env_float("SHEETCLI_LOCK_TIMEOUT", 600)
    fd = os.open(state / "lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() > deadline:
                    raise SheetError("another sheet call holds the daemon lock (timed out)")
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)


def _try_connect():
    try:
        import uno
        from com.sun.star.connection import NoConnectException
    except ImportError:
        raise SheetError("python uno module not available; run with system python3")
    ctx = uno.getComponentContext()
    resolver = ctx.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", ctx)
    try:
        remote = resolver.resolve(f"uno:pipe,name={pipe_name()};urp;StarOffice.ComponentContext")
    except NoConnectException:
        return None
    return remote.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", remote)


def _clear_stale(state):
    pid = _read_pid(state)
    if pid and process_alive(pid):
        kill_group(pid)
    (state / "pid").unlink(missing_ok=True)
    (state / "profile" / ".lock").unlink(missing_ok=True)


def _start(state):
    soffice = shutil.which("soffice") or SOFFICE_FALLBACK
    if not os.path.exists(soffice):
        raise SheetError("soffice not found (install LibreOffice)")
    proc = subprocess.Popen(
        [soffice, "--headless", "--invisible", "--nologo", "--norestore", "--nodefault",
         f"--accept=pipe,name={pipe_name()};urp;",
         f"-env:UserInstallation={(state / 'profile').as_uri()}"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    (state / "pid").write_text(str(proc.pid))
    timeout = _env_float("SHEETCLI_CONNECT_TIMEOUT", 30)
    deadline = time.time() + timeout
    while time.time() < deadline:
        desktop = _try_connect()
        if desktop:
            return proc.pid, desktop
        if proc.poll() is not None:
            _clear_stale(state)
            raise SheetError(f"soffice exited during startup (code {proc.returncode})")
        time.sleep(0.1)
    _clear_stale(state)
    raise SheetError(f"soffice did not accept connections within {timeout:g}s")


def _spawn_watchdog(state, pid):
    subprocess.Popen(
        [sys.executable, "-I", str(WATCHDOG), str(state), str(pid),
         str(_env_float("SHEETCLI_IDLE_SECONDS", 600))],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)


def _ensure_daemon(state):
    desktop = _try_connect()
    if desktop:
        return desktop
    _clear_stale(state)
    pid, desktop = _start(state)
    _spawn_watchdog(state, pid)
    return desktop


@contextmanager
def connection():
    """Serialized access to the daemon's Desktop; starts the daemon if needed.
    A timer kills the daemon if the call outlives SHEETCLI_CALL_TIMEOUT so it can never hang."""
    state = state_dir()
    with _serialized(state):
        desktop = _ensure_daemon(state)
        _touch(state)
        limit = _env_float("SHEETCLI_CALL_TIMEOUT", 300)
        fired = threading.Event()

        def expire():
            fired.set()
            _clear_stale(state)

        timer = threading.Timer(limit, expire)
        timer.daemon = True
        timer.start()
        try:
            yield desktop
        except Exception as e:
            if fired.is_set():
                raise SheetError(f"operation timed out after {limit:g}s; daemon killed") from e
            raise
        finally:
            timer.cancel()
            _touch(state)


def status():
    state = state_dir()
    pid = _read_pid(state)
    running = bool(pid and process_alive(pid))
    out = {"running": running, "pid": pid if running else None, "idle_seconds": None}
    if running:
        out["idle_seconds"] = round(idle_for(state), 1)
    return out


def stop():
    state = state_dir()
    with _serialized(state):
        pid = _read_pid(state)
        was_running = bool(pid and process_alive(pid))
        _clear_stale(state)
    return {"stopped": was_running}
