#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "pia_v05_self_test_report.txt"
APP_ID = "io.github.adventurefan.PIABazzite"

def main() -> int:
    lines: list[str] = []
    failures: list[str] = []

    def write(message: str = "") -> None:
        print(message)
        lines.append(message)

    write("PIA Bazzite 0.5.0 – self-test")
    write("This test does not contact PIA and does not change NetworkManager.")
    write()

    write("TEST 1: Python syntax")
    python_files = sorted([
        ROOT / "main.py",
        ROOT / "self_test.py",
        *(ROOT / "pia_bazzite").rglob("*.py"),
    ])
    for path in python_files:
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            failures.append(f"{path.relative_to(ROOT)}: {exc}")
    write(f"Checked {len(python_files)} Python files.")
    write("Result: " + ("OK" if not failures else "FAILED"))
    write()

    write("TEST 2: translations")
    resource_dir = ROOT / "pia_bazzite" / "resources" / "i18n"
    try:
        english = json.loads((resource_dir / "en.json").read_text(encoding="utf-8"))
        german = json.loads((resource_dir / "de.json").read_text(encoding="utf-8"))
        missing = sorted(set(english) ^ set(german))
    except (OSError, ValueError) as exc:
        failures.append(f"Translations: {exc}")
        english, german, missing = {}, {}, ["unreadable"]
    if missing:
        failures.append("Translation keys differ: " + ", ".join(missing))
    write(f"English entries: {len(english)}")
    write(f"German entries: {len(german)}")
    write("Result: " + ("OK" if not missing else "FAILED"))
    write()

    write("TEST 3: bundled PIA certificate")
    certificate = ROOT / "pia_bazzite" / "resources" / "pia-ca.rsa.4096.crt"
    certificate_ok = certificate.is_file() and "BEGIN CERTIFICATE" in certificate.read_text(
        encoding="utf-8", errors="replace"
    )
    if not certificate_ok:
        failures.append("Bundled PIA CA certificate is missing or invalid.")
    write("Result: " + ("OK" if certificate_ok else "FAILED"))
    write()

    write("TEST 4: no manual-connections dependency")
    runtime_files = sorted((ROOT / "pia_bazzite").rglob("*.py"))
    references = [
        str(path.relative_to(ROOT))
        for path in runtime_files
        if "manual-connections" in path.read_text(encoding="utf-8")
    ]
    if references:
        failures.append("Runtime references manual-connections: " + ", ".join(references))
    write("Result: " + ("OK" if not references else "FAILED"))
    write()

    write("TEST 5: Linux integration metadata")
    expected = [
        ROOT / "packaging" / f"{APP_ID}.desktop",
        ROOT / "packaging" / f"{APP_ID}.metainfo.xml",
        ROOT / "packaging" / "icons" / "scalable" / "apps" / f"{APP_ID}.svg",
        ROOT / "packaging" / "icons" / "512x512" / "apps" / f"{APP_ID}.png",
    ]
    missing_files = [str(path.relative_to(ROOT)) for path in expected if not path.is_file()]
    try:
        ET.parse(ROOT / "packaging" / f"{APP_ID}.metainfo.xml")
    except (OSError, ET.ParseError) as exc:
        failures.append(f"Invalid AppStream XML: {exc}")
    if missing_files:
        failures.append("Missing packaging files: " + ", ".join(missing_files))
    write("Result: " + ("OK" if not missing_files else "FAILED"))
    write()

    write("TEST 6: v0.5.0 release behavior")
    gui_source = (ROOT / "pia_bazzite" / "gui.py").read_text(encoding="utf-8")
    icon_source = (ROOT / "pia_bazzite" / "icons.py").read_text(encoding="utf-8")
    main_source = (ROOT / "main.py").read_text(encoding="utf-8")
    checks = {
        "PIA shield text": 'AlignCenter, "PIA"' in icon_source,
        "green application icon": '"application": QColor("#2e7d32")' in icon_source,
        "native tray context menu": "self.tray.setContextMenu(menu)" in gui_source,
        "no Wayland popup workaround": "menu.popup(" not in gui_source,
        "left click shows window": "ActivationReason.Trigger" in gui_source
            and "self.show_window()" in gui_source,
        "window icon does not follow VPN state":
            'self.setWindowIcon(status_icon("connected"))' not in gui_source
            and 'self.setWindowIcon(status_icon("disconnected"))' not in gui_source,
        "version command": '"--version" in sys.argv' in main_source,
        "tray status disabled": "status_action.setEnabled(False)" in gui_source,
        "system check symbols": "system_status_icon" in gui_source,
    }
    failed_checks = [name for name, ok in checks.items() if not ok]
    if failed_checks:
        failures.extend(f"Release check failed: {name}" for name in failed_checks)
    write("Result: " + ("OK" if not failed_checks else "FAILED"))
    for name in failed_checks:
        write(f"- {name}")
    write()

    write("TEST 7: public release files")
    release_files = [
        ROOT / "LICENSE",
        ROOT / "README.md",
        ROOT / "CHANGELOG.md",
        ROOT / "SECURITY.md",
        ROOT / "CONTRIBUTING.md",
        ROOT / "RELEASE_NOTES_0.5.0.md",
        ROOT / ".github" / "workflows" / "ci.yml",
        ROOT / ".github" / "workflows" / "release.yml",
        ROOT / "packaging" / "build-appimage.sh",
            ROOT / "packaging" / "build-appimage-podman.sh",
        ROOT / "packaging" / "appimage" / "PIA-Bazzite.spec",
    ]
    missing_release = [
        str(path.relative_to(ROOT)) for path in release_files if not path.is_file()
    ]
    if missing_release:
        failures.append("Missing release files: " + ", ".join(missing_release))
    write("Result: " + ("OK" if not missing_release else "FAILED"))
    write()

    write("=" * 72)
    if failures:
        write(f"SELF-TEST FAILED: {len(failures)} problem(s)")
        for failure in failures:
            write(f"- {failure}")
        result = 1
    else:
        write("SELF-TEST PASSED")
        result = 0

    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write(f"Report: {REPORT}")
    return result

if __name__ == "__main__":
    raise SystemExit(main())
