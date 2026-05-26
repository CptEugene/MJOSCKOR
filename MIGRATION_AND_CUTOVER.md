# MAYDAY Python Migration And Cutover

## Objective

Move the active MAYDAY implementation from the legacy C++ line to the new Python line without losing core voice, fleet tree, role, and packaging workflows.

## Current Status

- `Phase 1`: complete
- `Phase 2`: complete
- `Phase 3`: complete
- `Phase 4`: complete
- `Phase 5`: complete
- `Phase 6`: complete
- `Phase 7`: in progress
- `Phase 8`: in progress

## Migration Strategy

1. Keep the Python server as the reference control server.
2. Keep the Python client as the reference UI/runtime for new work.
3. Close packaging and cutover gaps before broad external testing.
4. Validate localhost first, then LAN, then wider tester rollout.
5. Only retire the C++ line after the Python line clears the release gate.

## Verification Checklist

- server starts cleanly
- client starts cleanly
- settings persist correctly
- fleet tree loads and saves correctly
- role slot occupancy updates correctly
- role-based channel permissions are enforced
- microphone capture and speaker playback work
- TX/RX tones work
- overlay appears only while speaking in game
- package output is reproducible

## Test Stages

### Stage A

- localhost
- 1 server + 1 or 2 clients

### Stage B

- same LAN
- 1 server + 2 or 3 clients

### Stage C

- external testers
- 5+ clients

## Cutover Conditions

Cut over the main development line only when all of the following are true:

- Python server is the active control server
- Python client covers the required MAYDAY feature set
- localhost and LAN tests pass without critical issues
- packaging output works on a clean machine
- remaining known issues are minor and documented

## Packaging Paths

- client package: [dist/client](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/dist/client)
- server package: [dist/server](/C:/Users/sornr/Desktop/MAYDAY/New/python-mayday/dist/server)

## Immediate Next Step

1. Validate package output
2. Add PyInstaller specs
3. Run real GUI/audio manual test
4. Run LAN multi-client test
5. Review remaining C++ parity gaps
