"""Print the pinned requirements of installed Home Assistant components."""

import json
from pathlib import Path
import sys

import homeassistant.components

root = Path(homeassistant.components.__path__[0])
for component in sys.argv[1:]:
    manifest = json.loads((root / component / "manifest.json").read_text())
    print(*manifest.get("requirements", []))
