# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_root = Path(SPECPATH).parent
if project_root.name == "tools":
    project_root = project_root.parent
data_root = project_root / "assets"
icon_file = data_root / "icon.ico"

a = Analysis(
    [str(project_root / "client" / "app" / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(data_root / "icon.png"), "assets"),
        (str(data_root / "backgrounds"), "assets/backgrounds"),
        (str(data_root / "visual_stage"), "assets/visual_stage"),
        (str(data_root / "bin"), "assets/bin"),
        (str(data_root / "fonts"), "assets/fonts"),
        (str(data_root / "sound"), "assets/sound"),
    ],
    hiddenimports=["pynput.keyboard._win32", "pynput.mouse._win32", "pygame", "PySide6.QtMultimedia"],
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
    name="Mayday",
    icon=str(icon_file),
    console=False,
)
