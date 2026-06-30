"""Acceptance test (PROJECT_SPEC): no copyrighted material / data / secrets are tracked by git."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # fire-code-copilot/


def test_nothing_copyrighted_is_tracked():
    script = ROOT / "scripts" / "check_containment.sh"
    result = subprocess.run(["bash", str(script)], cwd=str(ROOT),
                            capture_output=True, text=True)
    assert result.returncode == 0, f"containment violation:\n{result.stdout}\n{result.stderr}"
