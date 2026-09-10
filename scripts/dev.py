"""Run and stop this project's local services on macOS/Linux."""

import argparse
import fcntl
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".dev"


def shutdown(children):
    # Each service owns a process group, including its reload workers.
    for child in children:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if all(child.poll() is not None for child in children):
            break
        time.sleep(0.1)
    for child in children:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()


def commands():
    python = ROOT / "backend/.venv/bin/python"
    npm = shutil.which("npm")
    if not python.exists() or not npm or not (ROOT / "frontend/node_modules").is_dir():
        raise RuntimeError("Install Python/Node.js and run make install first.")
    for port in (8000, 3000):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as exc:
                raise RuntimeError(
                    f"Port {port} is busy. Stop the existing server in its original terminal first."
                ) from exc
    return [
        ([str(python), "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"], ROOT / "backend"),
        ([npm, "run", "dev", "--", "--port", "3000"], ROOT / "frontend"),
    ]


def run():
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    # Relative Unix socket paths avoid macOS's short socket path limit.
    os.chdir(RUNTIME)
    with open("lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Development services are already running. Use make stop first.", flush=True)
            return 1
        plan = commands()
        Path("control.sock").unlink(missing_ok=True)
        stopping = False

        def request_stop(*_):
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)
        children = []
        with socket.socket(socket.AF_UNIX) as server:
            server.bind("control.sock")
            server.listen(1)
            server.settimeout(0.2)
            try:
                for command, cwd in plan:
                    children.append(subprocess.Popen(command, cwd=cwd, start_new_session=True))
                print("Starting backend :8000 and frontend :3000. Ctrl+C or make stop shuts down both.", flush=True)
                while not stopping:
                    if any(child.poll() is not None for child in children):
                        print("A service exited; stopping the development session.", flush=True)
                        return 1
                    try:
                        connection, _ = server.accept()
                    except socket.timeout:
                        continue
                    with connection:
                        stopping = True
            finally:
                shutdown(children)
                Path("control.sock").unlink(missing_ok=True)
                print("Development services stopped.", flush=True)
    return 0


def stop():
    if not RUNTIME.is_dir():
        print("No managed development session is running.")
        return 0
    os.chdir(RUNTIME)
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(2)
        try:
            client.connect("control.sock")
        except (FileNotFoundError, ConnectionRefusedError):
            print("No managed development session is running.")
            return 0
    # Wait for cleanup before telling the caller it is safe to restart.
    with open("lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
    print("Development services stopped. You can now run make run.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "stop"))
    args = parser.parse_args()
    try:
        raise SystemExit(run() if args.action == "run" else stop())
    except (OSError, RuntimeError) as exc:
        parser.exit(1, f"{exc}\n")
