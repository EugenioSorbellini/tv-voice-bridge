"""Validate repository metadata and bundled assets before release."""

import argparse
import json
from pathlib import Path
import re
import tomllib


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    component = root / "custom_components/tv_voice_bridge"
    manifest = json.loads((component / "manifest.json").read_text())
    hacs = json.loads((root / "hacs.json").read_text())
    project = tomllib.loads((root / "pyproject.toml").read_text())
    package = json.loads((root / "package.json").read_text())
    version = manifest["version"]
    assert version == project["project"]["version"] == package["version"]
    if args.tag:
        assert args.tag.removeprefix("v") == version, "Release tag must match manifest"
    for key in ("domain", "name", "codeowners", "documentation", "issue_tracker", "version"):
        assert manifest.get(key), f"Missing manifest field: {key}"
    assert hacs["homeassistant"] == "2026.10.2"
    assert "config_flow" in manifest and manifest["config_flow"]
    assert (root / "LICENSE").is_file()
    assert (root / "README.md").is_file()
    assert (component / "brand/icon.png").is_file()
    assert f'VERSION = "{version}"' in (component / "const.py").read_text()

    def keys(value, prefix=""):
        return {prefix + key for key, item in value.items() if not isinstance(item, dict)} | {
            nested
            for key, item in value.items()
            if isinstance(item, dict)
            for nested in keys(item, prefix + key + ".")
        }

    languages = [
        json.loads((component / f"translations/{language}.json").read_text())
        for language in ("en", "it")
    ]
    assert keys(languages[0]) == keys(languages[1]), "Translation keys differ"
    assert [path.name for path in (root / "custom_components").iterdir() if path.is_dir()] == [
        "tv_voice_bridge"
    ]
    for path in component.rglob("*"):
        if "__pycache__" in path.parts:
            continue
        assert path.suffix not in (".pem", ".key", ".pyc"), f"Forbidden artifact: {path}"
        if path.suffix in (".js", ".mjs"):
            source = path.read_text()
            assert "createScriptProcessor" not in source
            for target in re.findall(r"(?:from\s+|import\s*)['\"](\.[^'\"]+)['\"]", source):
                assert (path.parent / target).is_file(), f"Missing module {target}"
    print(f"Release contract passed: TV Voice Bridge {version}")


if __name__ == "__main__":
    main()
