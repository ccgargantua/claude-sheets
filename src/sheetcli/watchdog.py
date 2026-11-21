import fcntl
import os
import signal
import sys
import time


def process_alive(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (FileNotFoundError, ProcessLookupError):
        return False


def kill_group(pid, grace=10.0):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            return
        deadline = time.time() + grace
        while time.time() < deadline:
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass
            if not process_alive(pid):
                return
            time.sleep(0.1)


def idle_for(state_dir):
    try:
        return time.time() - os.stat(os.path.join(state_dir, "last_used")).st_mtime
    except FileNotFoundError:
        return float("inf")


def watch(state_dir, pid, timeout):
    interval = min(30.0, max(0.5, timeout / 4))
    lock_fd = os.open(os.path.join(state_dir, "lock"), os.O_CREAT | os.O_RDWR)
    while process_alive(pid):
        time.sleep(interval)
        if idle_for(state_dir) < timeout:
            continue
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            continue
        if idle_for(state_dir) >= timeout:
            kill_group(pid)
            pid_file = os.path.join(state_dir, "pid")
            if os.path.exists(pid_file) and open(pid_file).read().strip() == str(pid):
                os.remove(pid_file)
            return
        fcntl.flock(lock_fd, fcntl.LOCK_UN)


if __name__ == "__main__":
    watch(sys.argv[1], int(sys.argv[2]), float(sys.argv[3]))
