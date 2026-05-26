# Packaging Notes

## Current State

The Python rebuild now has package scaffold scripts for both client and server.

Current package output includes:

- runtime configuration files
- copied font assets
- copied sound assets
- copied fleet tree data
- simple package manifest files

## Scripts

- [build_client_package.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/tools/build_client_package.py)
- [build_server_package.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/tools/build_server_package.py)
- [build_update_release.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/tools/build_update_release.py)
- [set_app_version.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/tools/set_app_version.py)
- [pyinstaller_update_host.spec](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/tools/pyinstaller_update_host.spec)

## Next Packaging Step

Attach PyInstaller so the scaffold becomes a real redistributable build:

- client executable
- server executable
- bundled data/assets

After `dist/client/Mayday.exe` exists, create the update release with:

```powershell
python tools\build_update_release.py --package-url-base https://your-update-host.example/mayday --manifest-url https://your-update-host.example/mayday/mayday_manifest.json
```

Upload both generated files from `dist/release`:

- `MAYDAY-client-<version>.zip`
- `mayday_manifest.json`

Run `CloudviewUpdateHost.exe` on the server computer and select the folder containing those two files.

To bump the MAYDAY version before building:

```powershell
python tools\set_app_version.py 1.0.2
```

## Validation Rule

After each packaging change, confirm:

- package folder is created
- expected config/data files exist
- manifest is generated
- runtime asset folders are present
