"""Shared test fixtures: one synthetic Olist-schema database per test run (random data, tests only)."""
import atexit
import shutil
import tempfile
from pathlib import Path

from scripts.make_synthetic_db import make

_TMP = tempfile.mkdtemp(prefix="t2s_tests_")
atexit.register(shutil.rmtree, _TMP, ignore_errors=True)
DB_PATH = make(str(Path(_TMP) / "synthetic_olist.db"), seed=0)


def tmp_dir() -> str:
    return tempfile.mkdtemp(prefix="t2s_out_", dir=_TMP)
