"""Calibration tool for poker_assistant.

Allows selecting ROIs (Regions of Interest) and extracting templates
for cards, digits, and table anchors using OpenCV.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np


def abs_to_rel(
    abs_rect: tuple[int, int, int, int] | list[int],
    table_rect: tuple[int, int, int, int] | list[int],
) -> list[float]:
    """Convert absolute pixel coordinates (x, y, w, h) to relative coordinates

    [x_rel, y_rel, w_rel, h_rel] in range 0.0 - 1.0 rounded to 4 decimals.
    """
    table_x, table_y, table_w, table_h = table_rect
    if table_w <= 0 or table_h <= 0:
        raise ValueError("Table width and height must be strictly positive (> 0).")

    x, y, w, h = abs_rect
    x_rel = round((x - table_x) / table_w, 4)
    y_rel = round((y - table_y) / table_h, 4)
    w_rel = round(w / table_w, 4)
    h_rel = round(h / table_h, 4)
    return [x_rel, y_rel, w_rel, h_rel]


def rel_to_abs(
    rel_rect: Sequence[float],
    table_rect: tuple[int, int, int, int] | list[int],
) -> tuple[int, int, int, int]:
    """Convert relative coordinates [x_rel, y_rel, w_rel, h_rel] back to

    absolute pixel coordinates (x, y, w, h) rounded to int.
    """
    table_x, table_y, table_w, table_h = table_rect
    if table_w <= 0 or table_h <= 0:
        raise ValueError("Table width and height must be strictly positive (> 0).")

    x_rel, y_rel, w_rel, h_rel = rel_rect[:4]
    x = int(round(table_x + x_rel * table_w))
    y = int(round(table_y + y_rel * table_h))
    w = int(round(w_rel * table_w))
    h = int(round(h_rel * table_h))
    return (x, y, w, h)


def load_config(config_path: str | Path = "config.json") -> dict:
    """Load configuration dictionary from JSON file."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config: dict, config_path: str | Path = "config.json") -> None:
    """Save configuration dictionary to JSON file."""
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def load_frame(source_path: str | Path, frame_idx: int = 0) -> np.ndarray:
    """Load a frame from an image file or video file."""
    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(f"Source file not found: {source}")

    video_extensions = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv"}
    if source.suffix.lower() in video_extensions:
        cap = cv2.VideoCapture(str(source))
        if not cap.isOpened():
            raise ValueError(f"Could not open video file: {source}")
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        cap.release()
        if not ret or frame is None:
            raise ValueError(
                f"Failed to read frame {frame_idx} from video: {source}"
            )
        return frame

    frame = cv2.imread(str(source))
    if frame is None:
        raise ValueError(f"Could not decode image file: {source}")
    return frame


def calibrate_rois(frame: np.ndarray, config: dict, config_path: str | Path) -> None:
    """Interactively calibrate ROIs and save to config."""
    print("\n--- KROK 1: Wybierz obszar całego stołu (table_rect) ---")
    print("Zaznacz stół myszą i zatwierdź [ENTER] lub [SPACJA]. Anuluj: [ESC] lub [c].")
    table_rect = cv2.selectROI(
        "Zaznacz stół (table_rect)", frame, fromCenter=False, showCrosshair=True
    )
    cv2.destroyWindow("Zaznacz stół (table_rect)")

    if table_rect[2] <= 0 or table_rect[3] <= 0:
        print("Nie zaznaczono poprawnego obszaru stołu. Kalibracja przerwana.")
        return

    table_tuple = (
        int(table_rect[0]),
        int(table_rect[1]),
        int(table_rect[2]),
        int(table_rect[3]),
    )
    print(f"Wybrano obszar stołu: {table_tuple}")

    rois: dict[str, list[float]] = config.setdefault("rois", {})
    roi_keys = list(rois.keys())

    print("\n--- KROK 2: Kalibracja stref ROI ---")
    print("Możesz kalibrować pojedyncze klucze lub przejść przez wszystkie.")
    print("Dostępne polecenia:")
    print("  'all'  - przejście po kolei przez wszystkie strefy")
    print("  'list' - wyświetlenie listy wszystkich kluczy ROI")
    print("  <klucz> - kalibracja wybranego klucza (np. pot, prize_pool)")
    print("  'quit' lub 'q' - zakończenie")

    def calibrate_single(key: str) -> None:
        print(f"\nKalibracja: {key}")
        print(f"Zaznacz ROI dla '{key}' w oknie OpenCV i zatwierdź [ENTER/SPACJA].")
        roi = cv2.selectROI(
            f"ROI: {key}", frame, fromCenter=False, showCrosshair=True
        )
        cv2.destroyWindow(f"ROI: {key}")
        if roi[2] > 0 and roi[3] > 0:
            rel = abs_to_rel(
                (int(roi[0]), int(roi[1]), int(roi[2]), int(roi[3])), table_tuple
            )
            rois[key] = rel
            save_config(config, config_path)
            print(f"Zapisano '{key}': {rel}")
        else:
            print(f"Pominięto '{key}'.")

    while True:
        try:
            cmd = input("\nPodaj klucz ROI ('all', 'list', 'quit'): ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not cmd or cmd.lower() in {"quit", "q", "exit"}:
            break
        elif cmd.lower() == "list":
            for idx, k in enumerate(roi_keys, start=1):
                print(f" {idx:2d}. {k}: {rois.get(k)}")
        elif cmd.lower() == "all":
            for k in roi_keys:
                print(f"\n[all] Krok dla '{k}'. Wpisz 'skip' aby pominąć, 'quit' aby przerwać, lub naciśnij ENTER.")
                try:
                    choice = input(f"Kalibrować '{k}'? [ENTER/skip/quit]: ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    return
                if choice == "quit":
                    break
                if choice == "skip":
                    continue
                calibrate_single(k)
        elif cmd in rois:
            calibrate_single(cmd)
        else:
            print(f"Nieznany klucz '{cmd}'. Użyj 'list' aby wyświetlić dostępne klucze.")


def extract_templates(frame: np.ndarray) -> None:
    """Interactively extract card/digit/anchor templates."""
    print("\n--- Wycinanie wzorców (templates) ---")
    print("Zaznacz wycinek myszą i zatwierdź [ENTER] lub [SPACJA]. Anuluj: [ESC] lub [c].")
    roi = cv2.selectROI(
        "Zaznacz wzorzec", frame, fromCenter=False, showCrosshair=True
    )
    cv2.destroyWindow("Zaznacz wzorzec")

    if roi[2] <= 0 or roi[3] <= 0:
        print("Nie zaznaczono wycinka.")
        return

    x, y, w, h = int(roi[0]), int(roi[1]), int(roi[2]), int(roi[3])
    crop = frame[y : y + h, x : x + w]

    try:
        t_type = input("Podaj typ wzorca (card / digit / anchor): ").strip().lower()
        if t_type == "card":
            name = input("Podaj kod karty (np. Qh, 4h, As, Th): ").strip()
            if name.startswith("10"):
                name = "T" + name[2:]
            dest = Path("data/templates/cards") / f"{name}.png"
        elif t_type == "digit":
            name = input("Podaj cyfrę (0-9): ").strip()
            dest = Path("data/templates/digits") / f"{name}.png"
        elif t_type == "anchor":
            dest = Path("data/templates/anchor.png")
        else:
            print(f"Nieznany typ wzorca '{t_type}'.")
            return

        dest.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(dest), crop)
        print(f"Zapisano wzorzec: {dest} (wymiary: {w}x{h} px)")
    except (EOFError, KeyboardInterrupt):
        print("\nPrzerwano.")


def preview_rois(frame: np.ndarray, config: dict) -> None:
    """Preview configured ROIs overlaid on the source frame."""
    print("\n--- Podgląd stref ROI ---")
    print("Zaznacz stół (table_rect) do nałożenia stref relatywnych.")
    table_rect = cv2.selectROI(
        "Zaznacz stół do podglądu", frame, fromCenter=False, showCrosshair=True
    )
    cv2.destroyWindow("Zaznacz stół do podglądu")

    if table_rect[2] <= 0 or table_rect[3] <= 0:
        print("Użyto pełnego rozmiaru klatki jako obszaru stołu.")
        table_tuple = (0, 0, frame.shape[1], frame.shape[0])
    else:
        table_tuple = (
            int(table_rect[0]),
            int(table_rect[1]),
            int(table_rect[2]),
            int(table_rect[3]),
        )

    display = frame.copy()
    tx, ty, tw, th = table_tuple
    cv2.rectangle(display, (tx, ty), (tx + tw, ty + th), (255, 0, 0), 2)
    cv2.putText(
        display,
        "TABLE",
        (tx + 5, ty + 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 0, 0),
        2,
        cv2.LINE_AA,
    )

    rois = config.get("rois", {})
    count = 0
    for key, rel_rect in rois.items():
        if rel_rect == [0.0, 0.0, 0.0, 0.0] or rel_rect[2] <= 0 or rel_rect[3] <= 0:
            continue
        rx, ry, rw, rh = rel_to_abs(rel_rect, table_tuple)
        cv2.rectangle(display, (rx, ry), (rx + rw, ry + rh), (0, 255, 0), 2)
        cv2.putText(
            display,
            key,
            (rx, max(15, ry - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 255, 0),
            1,
            cv2.LINE_AA,
        )
        count += 1

    print(f"Wyświetlono {count} skonfigurowanych stref ROI. Naciśnij 'q' lub ESC, aby zamknąć.")
    win_title = "Podglad ROI (wcisnij 'q' lub ESC)"
    cv2.imshow(win_title, display)
    while True:
        key = cv2.waitKey(0) & 0xFF
        if key in (27, ord("q")):
            break
    cv2.destroyWindow(win_title)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Narzędzie kalibracyjne dla poker_assistant (ROI i wzorce)"
    )
    parser.add_argument(
        "--source",
        type=str,
        help="Ścieżka do pliku obrazu (.png, .jpg) lub wideo (.mp4, .mkv, .avi)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.json",
        help="Ścieżka do pliku konfiguracyjnego (domyślnie config.json)",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="rois",
        choices=["rois", "templates", "preview"],
        help="Tryb pracy: rois (domyślny), templates, preview",
    )
    parser.add_argument(
        "--frame",
        type=int,
        default=0,
        help="Numer klatki dla pliku wideo (domyślnie 0)",
    )

    args = parser.parse_args()

    if not args.source:
        parser.print_help()
        print("\nBłąd: Wymagane jest podanie argumentu --source <ścieżka>.")
        return

    frame = load_frame(args.source, args.frame)
    config = load_config(args.config)

    if args.mode == "rois":
        calibrate_rois(frame, config, args.config)
    elif args.mode == "templates":
        extract_templates(frame)
    elif args.mode == "preview":
        preview_rois(frame, config)


if __name__ == "__main__":
    main()
