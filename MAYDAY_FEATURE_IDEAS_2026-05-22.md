# Mayday Feature Ideas - 2026-05-22

## Product Direction

Mayday should stay focused on fleet voice, command, organization, and live operation support.
Rather than becoming a broad Star Citizen helper app, its strongest identity is a command console for organized group play.

## Recommended Priority

1. Operation presets
   - Save server address, password, nickname, fleet tree, slots, channels, volumes, PTT, and other operation settings as reusable presets.
   - Example presets: mining escort, salvage operation, JumpTown, fleet battle, training.
   - This reduces repeated setup before every operation.

2. Fleet check-in system
   - Show each participant's state: ready, away, reconnecting, microphone issue, ship boarded, etc.
   - Commanders can immediately see who is not ready.
   - This fits naturally with the existing fleet tree and slots.

3. Emergency Mayday button
   - A dedicated hotkey/button that reaches the commander or assigned rescue/command group regardless of the current channel.
   - Show the sender, squad, slot, and emergency state clearly.
   - This strongly matches the app name and gives Mayday a signature feature.

## Additional Strong Candidates

4. Commander broadcast panel
   - Quick commands for all, squad, or specific slots.
   - Useful buttons could include hold, advance, regroup, silence, channel cleanup, etc.

5. Role-based audio profiles
   - Different RX sound/volume/priority behavior for Pilot, Commander, Officer, Soldier, and other roles.
   - Current direction:
     - Pilot keeps TAC-COM HA.
     - Non-pilot RX uses HOMEWORLD_FLEET_COMMS.

6. Operation timeline / event log
   - Track joins, leaves, slot changes, emergency calls, command broadcasts, and connection issues.
   - Keep it lightweight for command review and training feedback.

7. Star Citizen launch detection and automatic mode
   - Detect when Star Citizen starts.
   - Auto-connect or auto-apply the selected operation preset.
   - Return to standby when Star Citizen closes.

## Best First Bundle

The strongest first bundle is:

- Operation presets
- Fleet check-in system
- Emergency Mayday button

This gives users a clear reason to open Mayday before every fleet session and connects naturally with CloudView Center, fleet tree, PTT, and voice effects.
