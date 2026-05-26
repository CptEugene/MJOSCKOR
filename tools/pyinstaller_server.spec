# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_root = Path(SPECPATH).parent
if project_root.name == "tools":
    project_root = project_root.parent
data_root = project_root / "assets"
icon_file = data_root / "icon.ico"

a = Analysis(
    [str(project_root / "server" / "app" / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[],
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
    name="MaydayServer",
    icon=str(icon_file),
    console=True,
)
