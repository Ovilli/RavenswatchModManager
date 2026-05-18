"""Make `src/` importable when running pytest from a source checkout
without first running `pip install -e .`."""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
