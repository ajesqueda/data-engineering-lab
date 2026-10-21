"""Make each topic folder importable from its own tests."""

import sys
from pathlib import Path

ROOT = Path(__file__).parent
for tests_dir in ROOT.glob("*/tests"):
    sys.path.insert(0, str(tests_dir.parent))
