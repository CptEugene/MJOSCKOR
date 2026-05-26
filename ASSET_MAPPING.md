# MAYDAY Python Asset Mapping

## Font

- `assets/fonts/Mabinogi_Classic_TTF.ttf`
  - main UI font
  - dialogs
  - overlay text

## Radio Sound Mapping

- `CH1_start.wav` / `CH1_end.wav`
  - channel 1
  - `SQUAD`

- `CH23_start.wav` / `CH23_end.wav`
  - shared by channel 2 and channel 3
  - `HQ`
  - `ATC`

- `CH4_start.wav` / `CH4_end.wav`
  - channel 4
  - `GENERAL`

## Runtime Use

- TX start -> channel-specific `*_start.wav`
- TX end -> channel-specific `*_end.wav`
- RX start -> same channel `*_start.wav`
- RX end -> same channel `*_end.wav`
