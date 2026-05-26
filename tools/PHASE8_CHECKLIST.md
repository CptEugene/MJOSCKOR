# Phase 8 Checklist

## Before Cutover

- [x] Python client starts
- [x] Python server starts
- [x] settings file is created
- [x] fleet tree file is created
- [x] assets are copied into runtime
- [x] client package scaffold is generated
- [x] server package scaffold is generated

## Local Verification

- [x] localhost connection succeeds
- [x] hello / heartbeat works
- [x] join node works
- [x] tree snapshot works
- [x] presence snapshot works
- [x] microphone frame send works
- [x] playback queue works
- [x] role permissions are enforced
- [ ] overlay only appears on speaking

## Network Verification

- [ ] LAN client can connect
- [ ] atc routing works
- [ ] general routing works
- [ ] squad routing works across squads in same wing

## Release Gate

- [ ] no critical crash on join
- [ ] no endless reconnect loop
- [ ] no tree duplication issue
- [x] no broken config serialization
- [x] packaging notes updated
