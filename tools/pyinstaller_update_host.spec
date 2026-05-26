# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_root = Path(SPECPATH).parent
data_root = project_root / "assets"
icon_file = data_root / "cloudview" / "icons" / "ccicon.ico"

a = Analysis(
    [str(project_root / "update_host" / "app" / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(data_root / "cloudview" / "icons" / "ccicon.ico"), "assets/cloudview/icons"),
        (str(data_root / "fonts"), "assets/fonts"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="CloudviewUpdateHost",
    icon=str(icon_file),
    console=False,
)
