# MAYDAY Python Implementation Audit

Date: 2026-03-20

## Overlay Position

- Current overlay position is `left-middle`.
- Source: [client/overlay/overlay_widget.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/client/overlay/overlay_widget.py)
- Logic:
  - `x = screen.left + 28`
  - `y = screen.top + max(80, screen.height/2 - overlay.height/2)`

## What Has Been Built

### 1. Client Application

- Main window with:
  - channel cards
  - local status
  - fleet tree
  - settings button
  - notice dialog
  - admin dialog
- Source:
  - [client/ui/main_window.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/client/ui/main_window.py)
  - [client/ui/channel_card.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/client/ui/channel_card.py)
  - [client/ui/settings_dialog.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/client/ui/settings_dialog.py)
  - [client/ui/admin_dialog.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/client/ui/admin_dialog.py)
  - [client/ui/fleet_tree_widget.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/client/ui/fleet_tree_widget.py)

### 2. Audio Path

- Microphone capture
- Speaker playback
- UDP voice transport
- TX/RX WAV effect playback
- Radio EQ / telephone-style DSP chain
- Source:
  - [client/audio/microphone_capture.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/client/audio/microphone_capture.py)
  - [client/audio/speaker_playback.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/client/audio/speaker_playback.py)
  - [client/audio/effects.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/client/audio/effects.py)
  - [client/audio/radio_eq.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/client/audio/radio_eq.py)
  - [client/services/audio_runtime.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/client/services/audio_runtime.py)
  - [client/network/voice_transport.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/client/network/voice_transport.py)

### 3. Input System

- Keyboard bindings
- Mouse side-button bindings
- Joystick button bindings
- Binding capture dialog
- Source:
  - [client/input/bindings.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/client/input/bindings.py)
  - [client/input/input_monitor.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/client/input/input_monitor.py)
  - [client/ui/binding_capture_dialog.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/client/ui/binding_capture_dialog.py)

### 4. Server Application

- TCP control server
- UDP voice relay
- password check
- tree persistence
- presence snapshot broadcast
- slot occupancy validation
- frequency-aware relay routing
- Source:
  - [server/app/server_core.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/server/app/server_core.py)
  - [server/network/session_store.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/server/network/session_store.py)
  - [server/auth/password_store.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/server/auth/password_store.py)
  - [server/fleet/tree_store.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/server/fleet/tree_store.py)

### 5. Fleet Tree / Role / Permissions

- `Fleet -> Wing -> Squad -> Role Slot`
- role permissions:
  - Commander
  - Officer
  - Sergeant
  - Soldier
- slot occupancy and speaking state
- Source:
  - [shared/models/fleet_tree.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/shared/models/fleet_tree.py)
  - [shared/models/fleet_tree_codec.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/shared/models/fleet_tree_codec.py)
  - [client/services/fleet_tree_binding.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/client/services/fleet_tree_binding.py)

### 6. Settings / Persistence

- saves:
  - nickname
  - server address
  - server password
  - microphone device
  - speaker device
  - microphone level
  - speaker level
  - per-channel frequency
  - per-channel receive volume
  - per-channel pan
  - per-channel PTT binding
- Source:
  - [client/services/settings_store.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/client/services/settings_store.py)
  - [shared/models/app_settings.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/shared/models/app_settings.py)

### 7. Overlay / Game Detection

- Star Citizen process monitor
- overlay for active talkers only
- left-middle positioning
- Source:
  - [client/input/process_detection.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/client/input/process_detection.py)
  - [client/overlay/overlay_widget.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/client/overlay/overlay_widget.py)

### 8. Packaging / Build

- PyInstaller client build
- PyInstaller server build
- packaged `data/fonts`, `data/sound`
- Source:
  - [tools/pyinstaller_client.spec](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/tools/pyinstaller_client.spec)
  - [tools/pyinstaller_server.spec](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/tools/pyinstaller_server.spec)
  - [tools/build_client_package.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/tools/build_client_package.py)
  - [tools/build_server_package.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/tools/build_server_package.py)

## Current Important Behavior

- Voice relay is now based on:
  - same channel tag
  - same tuned frequency
- Tree membership does not decide relay anymore.
- Slot occupancy is server-authoritative.
- Client no longer should pre-fill a slot locally before server confirmation.

## Issues Found During Audit

### Confirmed

1. README encoding is broken.
   - File: [README.md](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/README.md)
   - Symptom:
     - Korean text is garbled.
   - Impact:
     - does not break runtime
     - does make documentation unreliable

2. Voice receive audibility can still depend heavily on saved settings.
   - Files:
     - [client/services/settings_store.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/client/services/settings_store.py)
     - [client/services/audio_runtime.py](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/client/services/audio_runtime.py)
   - Recent fix:
     - bad TOML now falls back safely
     - broken config gets backed up
   - Residual risk:
     - users with previously bad settings may need to save once again

3. Frequency routing only updates on:
   - connect
   - explicit save while connected
   - If a user edits frequency but does not save, server will still use the old tuned value.

### Watch List

1. `speaker_playback.py`
   - playback loop batches up to 4 queue items
   - this helps smooth playback, but may soften attack timing slightly

2. `process_detection.py`
   - still uses `tasklist`
   - it now runs in a background thread at a slow interval, so it should be much cheaper than before
   - but it is still worth monitoring on weaker PCs

3. `audio_runtime.py`
   - current voice processing is centralized on transmit
   - receive side mainly applies gain and pan, not full DSP
   - this is intentional, but should be remembered when tuning “what the other user hears”

## What Was Changed Recently

- Safe TOML save/load added
- broken config fallback added
- server-side frequency-based relay added
- client now sends channel frequencies to server
- overlay restored
- Star Citizen detection restored
- slot occupancy kept server-authoritative

## Validation Status

- lint: passing
- tests: passing
- latest automated result:
  - `16 passed`

## Recommendation

Before wider distribution, manually verify:

1. save and restart on a clean client
2. same frequency / different tree still communicates
3. different frequency / same channel does not communicate
4. occupied slot cannot be taken by another user
5. overlay appears only when Star Citizen is detected and someone is speaking
