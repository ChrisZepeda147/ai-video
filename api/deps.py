"""FastAPI dependencies."""

from __future__ import annotations

import sys
from collections.abc import Generator
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from discovery.config import default_db_path, load_env  # noqa: E402
from discovery.store import DiscoveryStore  # noqa: E402

load_env()

try:
    from toolchain_env import apply_to_os_environ

    apply_to_os_environ()
except ImportError:
    pass


def get_store() -> Generator[DiscoveryStore, None, None]:
    store = DiscoveryStore(default_db_path())
    try:
        yield store
    finally:
        store.close()
