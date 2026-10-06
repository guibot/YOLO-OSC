# YOLO Tracking → TouchDesigner

Real-time object/person detection, tracking and counting from a webcam ([YOLOv8](https://github.com/ultralytics/ultralytics) + ByteTrack). Sends data over OSC, e.g. to TouchDesigner.

## Features

- Webcam and class selection panels on startup
- Tracking with persistent IDs (ByteTrack)
- Per-target state: moving / stopped
- Marker showing class, ID and state (`person ID 3 move`)
- Counting line with entries, exits and total inside
- Data output over OSC

## Requirements

- Python 3.10+
- macOS (tested) with camera permission granted to your terminal app

## Installation

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

The `yolov8n.pt` model is downloaded automatically by Ultralytics on first run.

## Usage

```bash
python main.py
```

On macOS you can also double-click `run.command`.

### Shortcuts

| Key | Action |
|-----|--------|
| `q` | Quit |
| `c` | Reopen class selection panel |
| `l` | Show / hide the counting line |

## Configuration

`config.json` (written when you confirm the panels):

```json
{
  "camera": 0,
  "classes": [0],
  "show_on_start": true
}
```

- `camera`: webcam index
- `classes`: COCO class IDs (0 = person)
- `show_on_start`: show the panels on startup

Constants at the top of `main.py`: `CONF_THRESHOLD`, `LINE_Y_RATIO`, `MOVEMENT_THRESHOLD_PX`, `OSC_HOST`, `OSC_PORT`.

## OSC

Default destination: `127.0.0.1:9000`.

| Address | Value |
|---------|-------|
| `/target/<id>/class` | class name (string) |
| `/target/<id>/x`, `/y` | center, normalized 0..1 |
| `/target/<id>/w`, `/h` | size, normalized 0..1 |
| `/target/<id>/state` | 1 = moving, 0 = stopped |
| `/lost` | ID of a target that disappeared |
| `/count/entries` | total entries (crossing the line top to bottom) |
| `/count/exits` | total exits (bottom to top) |
| `/count/inside` | entries − exits |

## Troubleshooting

**"Nenhuma webcam encontrada" (no webcam found)**: System Settings → Privacy & Security → Camera → enable your terminal app. If needed: `tccutil reset Camera com.apple.Terminal`.

## Credits

This integration was orchestrated by Guilherme Martins and built with [Claude Code](https://claude.com/claude-code).

Detection powered by [Ultralytics YOLO](https://github.com/ultralytics/ultralytics).
