# MAYDAY Python Phase Follow-Up Checklist

This file tracks the implementation status after the original Phase 1-8 planning docs.

Legend:
- `[x]` complete
- `[-]` in progress
- `[ ]` not started

---

## Phase 1 Follow-Up

Goal: project structure and basic development workflow

- [x] `client`, `server`, `shared` structure
- [x] `pyproject.toml` dependencies and metadata
- [x] dev/run scripts
- [x] test execution confirmed
- [x] `README` run guide
- [x] lint / format scripts
- [x] `.gitignore`

---

## Phase 2 Follow-Up

Goal: Python control server completeness

- [x] `hello / heartbeat / join_node / ptt_state / tree_request / tree_update`
- [x] `presence_snapshot / tree_snapshot` broadcast
- [x] server password load/save
- [x] server shell commands
- [x] `--headless` mode
- [x] error code system
- [x] log level separation
- [x] session / route inspection commands

---

## Phase 3 Follow-Up

Goal: UI shell completed as a usable MAYDAY client screen

- [x] main window shell
- [x] settings / notice / admin dialogs
- [x] local status section
- [x] channel card state updates
- [x] fleet tree area binding
- [x] admin dialog connected to real tree editing
- [x] layout/style refinement

---

## Phase 4 Follow-Up

Goal: audio path completed into a usable first-pass radio runtime

- [x] audio device discovery
- [x] microphone capture service
- [x] speaker playback service
- [x] UDP voice transport
- [x] `1~4` PTT test path
- [x] TX/RX effect sounds
- [x] radio EQ / coloring
- [x] jitter smoothing / paced playout
- [x] receive gain tuning tied to channel settings

---

## Phase 5 Follow-Up

Goal: fleet tree and permission model completed

- [x] `Fleet -> Wing -> Squad -> RoleSlot` model
- [x] role permission model
- [x] server fleet tree JSON storage
- [x] tree widget bound to real model
- [x] presence application
- [x] double-click slot activation -> `join_slot`
- [x] role-based `tx/rx` restrictions in live Python audio/control path
- [x] admin tree editing validation / save workflow polish

---

## Phase 6 Follow-Up

Goal: input and overlay completed for real use

- [x] Star Citizen detection
- [x] overlay widget
- [x] speaking presence -> overlay bridge
- [x] test-only keyboard PTT bridge
- [x] real binding capture UI
- [x] mouse / joystick input
- [x] overlay visual polish

---

## Phase 7 Follow-Up

Goal: settings persistence and packaging readiness

- [x] settings dialog <-> `SettingsStore`
- [x] server address / password / nickname persistence
- [x] device selection / volume persistence
- [x] settings reload on startup
- [x] runtime asset copy structure
- [x] package script output validation
- [x] PyInstaller spec

---

## Phase 8 Follow-Up

Goal: migration and cutover verification

- [x] migration / cutover docs
- [x] localhost headless verification
- [x] offscreen GUI smoke verification
- [ ] real GUI manual verification
- [ ] real microphone / speaker audio test
- [ ] LAN 2-client test
- [x] known issues document
- [x] C++ gap list

---

## Immediate Next

1. Run real GUI manual verification
2. Run real microphone / speaker verification
3. Run LAN 2-client test
4. Build PyInstaller executables on a clean machine
