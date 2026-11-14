"""The README quickstart is examples/quickstart.py: run it, so the README can't drift from the package."""

import subprocess
import sys
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "quickstart.py"


def test_quickstart_allows_then_blocks():
    result = subprocess.run([sys.executable, str(EXAMPLE)], capture_output=True, text=True, check=True)
    assert result.stdout.splitlines() == [
        "refunded $120 on A100",
        "blocked: Invariant 'refund-cap' violated",
    ]
