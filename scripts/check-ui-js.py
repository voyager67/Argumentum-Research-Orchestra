"""Extract and syntax-check the JavaScript shipped in the researcher UI."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML_FILE = ROOT / "src" / "argumentum" / "server" / "static" / "index.html"


def main() -> int:
    node = shutil.which("node")
    if node is None:
        print("Node.js was not found; install Node.js 22 to check the shipped UI script.", file=sys.stderr)
        return 2
    source = HTML_FILE.read_text(encoding="utf-8")
    scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", source, flags=re.DOTALL | re.IGNORECASE)
    if not scripts:
        print(f"No inline JavaScript found in {HTML_FILE}", file=sys.stderr)
        return 1
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write("\n\n".join(scripts))
        script_path = Path(handle.name)
    try:
        result = subprocess.run([node, "--check", str(script_path)], check=False)
        if result.returncode == 0:
            print("Researcher UI JavaScript syntax: OK")
        return result.returncode
    finally:
        script_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
