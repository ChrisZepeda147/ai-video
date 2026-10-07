"""Process-tree termination for B-roll source workers (Windows-safe)."""

from __future__ import annotations

import subprocess
import sys


def kill_process_tree(pid: int) -> None:
    if pid <= 0:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            check=False,
        )
        return
    try:
        import os
        import signal

        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, OSError, AttributeError):
        try:
            import os
            import signal

            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
