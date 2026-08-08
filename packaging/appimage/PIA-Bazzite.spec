# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, copy_metadata
import PySide6

root = Path.cwd().resolve()
qt_translations = Path(PySide6.__file__).resolve().parent / "Qt" / "translations"
qtbase_de = qt_translations / "qtbase_de.qm"
if not qtbase_de.is_file():
    raise FileNotFoundError(f"Required Qt German translation not found: {qtbase_de}")

hiddenimports = [
    "keyring.backends.SecretService",
    "secretstorage",
    *collect_submodules("keyring.backends"),
]

datas = [
    (str(root / "pia_bazzite" / "resources"), "pia_bazzite/resources"),
    (str(root / "THIRD_PARTY_NOTICES.md"), "pia_bazzite/resources"),
    (str(qtbase_de), "PySide6/Qt/translations"),
    *copy_metadata("keyring"),
    *copy_metadata("SecretStorage"),
    *copy_metadata("requests"),
]

analysis = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PySide6.Qt3DCore",
        "PySide6.Qt3DExtras",
        "PySide6.QtBluetooth",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtLocation",
        "PySide6.QtMultimedia",
        "PySide6.QtPdf",
        "PySide6.QtPositioning",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtRemoteObjects",
        "PySide6.QtScxml",
        "PySide6.QtSensors",
        "PySide6.QtSerialPort",
        "PySide6.QtWebChannel",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebSockets",
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="PIA-Bazzite",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PIA-Bazzite",
)
