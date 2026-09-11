"""Exercise lifecycle management without starting application services."""

from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "dev.py"


class DevelopmentSessionTests(unittest.TestCase):
    def test_start_duplicate_stop_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / "runtime"
            setup = (
                "import importlib.util; from pathlib import Path; "
                f"spec=importlib.util.spec_from_file_location('dev', {str(SCRIPT)!r}); "
                "dev=importlib.util.module_from_spec(spec); spec.loader.exec_module(dev); "
                f"dev.RUNTIME=Path({str(runtime)!r}); "
                f"dev.commands=lambda: [([{sys.executable!r}, '-c', "
                "'import time; time.sleep(60)'], dev.ROOT)] * 2; "
            )
            for _ in range(2):
                process = subprocess.Popen(
                    [sys.executable, "-c", setup + "raise SystemExit(dev.run())"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                )
                try:
                    deadline = time.monotonic() + 5
                    while not (runtime / "control.sock").exists():
                        if process.poll() is not None:
                            self.fail(process.communicate()[0])
                        if time.monotonic() > deadline:
                            self.fail("Development supervisor did not start")
                        time.sleep(0.05)
                    duplicate = subprocess.run(
                        [sys.executable, "-c", setup + "raise SystemExit(dev.run())"],
                        capture_output=True, text=True, timeout=5,
                    )
                    self.assertEqual(duplicate.returncode, 1)
                    stopped = subprocess.run(
                        [sys.executable, "-c", setup + "raise SystemExit(dev.stop())"],
                        capture_output=True, text=True, timeout=10,
                    )
                    self.assertEqual(stopped.returncode, 0, stopped.stderr)
                    output, _ = process.communicate(timeout=10)
                    self.assertEqual(process.returncode, 0, output)
                    self.assertFalse((runtime / "control.sock").exists())
                finally:
                    if process.poll() is None:
                        process.terminate()
                    process.communicate(timeout=10)


if __name__ == "__main__":
    unittest.main()
