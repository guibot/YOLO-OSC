"""Deteção, contagem e tracking de pessoas em tempo real via webcam."""

import json
import time
import tkinter as tk
from pathlib import Path

import cv2
from pythonosc.udp_client import SimpleUDPClient
from ultralytics import YOLO

# ---------------- CONFIG ----------------
MAX_CAMERAS = 5  # índices 0..N-1 testados na escolha da webcam
MODEL_PATH = "yolov8n.pt"
CONF_THRESHOLD = 0.4

OSC_HOST = "127.0.0.1"
OSC_PORT = 9000

CONFIG_PATH = Path(__file__).with_name("config.json")
DEFAULT_CONFIG = {"camera": 0, "classes": [0], "show_on_start": True}  # 0 = person
PANEL_COLUMNS = 3
PANEL_SIZE = (900, 700)  # largura, altura da lista

LINE_Y_RATIO = 0.5          # posição da linha horizontal (0..1 da altura do frame)
MOVEMENT_THRESHOLD_PX = 4.0  # deslocamento do centróide (px/frame) acima do qual conta como "em movimento"

COLOR_MOVING = (0, 255, 0)
COLOR_STOPPED = (0, 0, 255)
COLOR_LINE = (255, 255, 0)
COLOR_TEXT = (255, 255, 255)
# -----------------------------------------


def load_config():
    try:
        data = json.loads(CONFIG_PATH.read_text())
    except (OSError, ValueError):
        return dict(DEFAULT_CONFIG)
    config = {**DEFAULT_CONFIG, **data}
    if not config["classes"]:
        config["classes"] = list(DEFAULT_CONFIG["classes"])
    return config


def save_config(config):
    CONFIG_PATH.write_text(json.dumps(config, indent=2))


def list_cameras():
    found = []
    for i in range(MAX_CAMERAS):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            found.append(i)
        cap.release()
    return found


def show_camera_panel(config):
    """Painel de escolha da webcam. Devolve o índice, ou None se fechado sem Next."""
    cameras = list_cameras()
    if not cameras:
        raise RuntimeError("Nenhuma webcam encontrada. Verifica permissões de câmara no macOS.")

    root = tk.Tk()
    root.title("Webcam")
    default = config["camera"] if config["camera"] in cameras else cameras[0]
    choice = tk.IntVar(master=root, value=default)
    result = {}

    def on_next():
        result["camera"] = choice.get()
        root.destroy()

    for i in cameras:
        label = f"Camera {i}"
        tk.Radiobutton(root, text=label, variable=choice, value=i).pack(anchor="w", padx=16, pady=2)
    tk.Button(root, text="Next", command=on_next).pack(side="right", padx=8, pady=8)

    root.mainloop()
    return result.get("camera")


def show_panel(names, config):
    """Painel com toggles por classe. Devolve a nova config, ou None se fechado sem Start."""
    root = tk.Tk()
    root.title("Classes a detetar")

    selected = {cid: tk.BooleanVar(master=root, value=cid in config["classes"]) for cid in names}
    show_var = tk.BooleanVar(master=root, value=config["show_on_start"])
    error_var = tk.StringVar(master=root)
    result = {}

    def on_start():
        chosen = [cid for cid, var in selected.items() if var.get()]
        if not chosen:
            error_var.set("Seleciona pelo menos uma classe.")
            return
        result["config"] = {"classes": chosen, "show_on_start": show_var.get()}
        root.destroy()

    def set_all(value):
        for var in selected.values():
            var.set(value)

    bottom = tk.Frame(root)
    bottom.pack(side="bottom", fill="x", padx=8, pady=8)
    tk.Checkbutton(bottom, text="Open this window on start", variable=show_var).pack(side="left")
    tk.Button(bottom, text="Start", command=on_start).pack(side="right")
    tk.Button(bottom, text="Clear all", command=lambda: set_all(False)).pack(side="right", padx=4)
    tk.Button(bottom, text="Select all", command=lambda: set_all(True)).pack(side="right")
    tk.Label(bottom, textvariable=error_var, fg="red").pack(side="right", padx=8)

    canvas = tk.Canvas(root, width=PANEL_SIZE[0], height=PANEL_SIZE[1], highlightthickness=0)
    scrollbar = tk.Scrollbar(root, command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    inner = tk.Frame(canvas)
    canvas.create_window((0, 0), window=inner, anchor="nw")

    def on_inner_configure(_event):
        canvas.configure(scrollregion=canvas.bbox("all"))

    inner.bind("<Configure>", on_inner_configure)
    canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-e.delta, "units"))

    rows = -(-len(names) // PANEL_COLUMNS)  # ordem alfabética a descer, por coluna
    for i, (cid, name) in enumerate(sorted(names.items(), key=lambda kv: kv[1].lower())):
        tk.Checkbutton(inner, text=name, variable=selected[cid]).grid(
            row=i % rows, column=i // rows, sticky="w", padx=8)

    root.mainloop()
    return result.get("config")


def main():
    model = YOLO(MODEL_PATH)

    config = load_config()
    if config["show_on_start"]:
        camera = show_camera_panel(config)
        if camera is None:
            return
        config["camera"] = camera
        new_config = show_panel(model.names, config)
        if new_config is None:
            return
        config = {**config, **new_config}
        save_config(config)

    osc = SimpleUDPClient(OSC_HOST, OSC_PORT)

    cap = cv2.VideoCapture(config["camera"])
    if not cap.isOpened():
        raise RuntimeError("Não foi possível abrir a webcam. Verifica permissões de câmara no macOS.")

    track_history = {}  # id -> lista de centróides (x, y)
    counted_ids = set()  # ids já contados neste cruzamento (evita contagem dupla seguida)
    entries = 0
    exits = 0

    line_y = None
    show_line = True

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        if line_y is None:
            line_y = int(frame.shape[0] * LINE_Y_RATIO)

        results = model.track(
            frame,
            persist=True,
            classes=config["classes"],
            conf=CONF_THRESHOLD,
            tracker="bytetrack.yaml",
            verbose=False,
        )

        visible_count = 0

        if results[0].boxes is not None and results[0].boxes.id is not None:
            boxes = results[0].boxes.xyxy.cpu().numpy()
            ids = results[0].boxes.id.cpu().numpy().astype(int)
            class_ids = results[0].boxes.cls.cpu().numpy().astype(int)
            frame_h, frame_w = frame.shape[:2]

            visible_count = len(ids)

            for box, track_id, class_id in zip(boxes, ids, class_ids):
                x1, y1, x2, y2 = box
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2

                history = track_history.setdefault(track_id, [])
                history.append((cx, cy))
                if len(history) > 30:
                    history.pop(0)

                # velocidade aproximada (deslocamento entre os últimos 2 frames)
                speed = 0.0
                if len(history) >= 2:
                    px, py = history[-2]
                    speed = ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5

                is_moving = speed >= MOVEMENT_THRESHOLD_PX
                color = COLOR_MOVING if is_moving else COLOR_STOPPED

                base = f"/target/{int(track_id)}"
                osc.send_message(f"{base}/class", model.names[class_id])
                osc.send_message(f"{base}/x", float(cx / frame_w))
                osc.send_message(f"{base}/y", float(cy / frame_h))
                osc.send_message(f"{base}/w", float((x2 - x1) / frame_w))
                osc.send_message(f"{base}/h", float((y2 - y1) / frame_h))
                osc.send_message(f"{base}/state", int(is_moving))

                # deteção de cruzamento de linha (usa posição anterior vs atual)
                if len(history) >= 2:
                    prev_y = history[-2][1]
                    crossed_down = prev_y < line_y <= cy
                    crossed_up = prev_y > line_y >= cy

                    if crossed_down and track_id not in counted_ids:
                        entries += 1
                        counted_ids.add(track_id)
                    elif crossed_up and track_id not in counted_ids:
                        exits += 1
                        counted_ids.add(track_id)
                    elif not crossed_down and not crossed_up:
                        counted_ids.discard(track_id)

                cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
                label = f"{model.names[class_id]} ID {track_id} {'move' if is_moving else 'parado'}"
                cv2.putText(frame, label, (int(x1), int(y1) - 12),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)
                cv2.circle(frame, (int(cx), int(cy)), 3, color, -1)

        # remove históricos de ids que já não aparecem (evita crescimento infinito)
        if results[0].boxes is not None and results[0].boxes.id is not None:
            active_ids = set(ids.tolist())
        else:
            active_ids = set()
        for old_id in list(track_history.keys()):
            if old_id not in active_ids:
                track_history.pop(old_id, None)
                counted_ids.discard(old_id)
                osc.send_message("/lost", int(old_id))

        if show_line:
            cv2.line(frame, (0, line_y), (frame.shape[1], line_y), COLOR_LINE, 2)

        total = entries - exits
        osc.send_message("/count/entries", entries)
        osc.send_message("/count/exits", exits)
        osc.send_message("/count/inside", total)
        info_lines = [
            f"Entradas: {entries}  Saidas: {exits}  Dentro: {total}",
            f"Visiveis agora: {visible_count}",
        ]
        for i, text in enumerate(info_lines):
            cv2.putText(frame, text, (10, 30 + i * 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, COLOR_TEXT, 2)

        cv2.imshow("Tracking de Pessoas (YOLOv8 + ByteTrack)", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("l"):
            show_line = not show_line
        if key == ord("c"):
            cv2.destroyAllWindows()
            cv2.waitKey(1)
            new_config = show_panel(model.names, config)
            if new_config is not None:
                config = {**config, **new_config}
                save_config(config)

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
