# Voice Effect Follow-up Memo - 2026-05-20

## Latest Real-Use Test Result

- Real-use audio does not match the generated sample preview.
- Commander / Officer / Soldier effect is currently too muffled in real use.
- Commander / Officer / Soldier effect does not make the vocal doubler feel audible in real use.
- Pilot effect is too loud and clips/breaks up.

## Current Routing Reminder

- Commander / Officer / Soldier use `HOMEWORLD_FLEET_COMMS` through `HomeworldFleetCommsEffect`.
- Pilot uses TAC-COM original `HAChain` through `TacComOriginalProfileEffect(new HAChain())`.
- Do not tune Pilot by changing `HomeworldFleetCommsEffect`.
- Do not tune Commander / Officer / Soldier by changing Pilot HA unless explicitly requested.

## Likely Cause: Commander / Officer / Soldier

- The sample preview was generated from a WAV file and does not perfectly match the actual receive/playback path.
- Real receive path processes mono voice frames, then applies output gain and channel volume in `AudioEngineHost`.
- The old fan-style profile was removed. Current tuning lives in `HOMEWORLD_FLEET_COMMS`.
- The doubler may be masked because delayed voices are low-passed and mixed before the realtime playback gain/pan path.

## Next Fix Direction: Commander / Officer / Soldier

- Make the voice clearer first before adding more effect.
- Raise `HighCut` back toward `5600-6200`.
- Raise presence/clarity around `2800-3800Hz`, but avoid harsh crackle.
- Reduce mid tunnel boost slightly if it is too muffled.
- Make doubler audible through timing/mix, not extra distortion:
  - Try `DoublerMix` around `0.62-0.68`.
  - Try delays around `10ms` and `18ms` instead of `8ms` and `14ms`.
  - Keep `DoublerDepthSamples` low enough to avoid side crackle, around `2.0-3.0`.
  - Consider removing or raising the delayed-voice low-pass if it hides the doubler too much.
- Keep saturation off or near off until the crackle issue is fully gone.

## Likely Cause: Pilot

- Pilot uses TAC-COM HA original chain and is not using `HOMEWORLD_FLEET_COMMS`.
- Pilot clipping likely comes from `TacComOriginalProfileEffect` output level being too hot after HA processing or from receiver/channel gain after the HA chain.

## Next Fix Direction: Pilot

- Add a pilot-only output attenuation after `TacComOriginalProfileEffect(new HAChain())`.
- Start with Pilot HA wet output around `-6dB` or `-9dB`.
- If HA still clips internally before output, attenuate input into HA as well.
- Do not replace HA profile unless requested; keep TAC-COM HA chain, just control gain/limiting.

## Build/Test Reminder

- After changes, build with `python tools\build_client_package.py`.
- Then build `Mayday.exe` with PyInstaller.
- Real-use testing is more important than WAV preview for this issue.
