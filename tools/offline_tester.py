"""Offline replay tester for poker_assistant CV/OCR tuning."""

from __future__ import annotations

import argparse
from pathlib import Path
import time

import cv2

from vision.capture import OfflineReplayCapture
from vision.pipeline import VisionPipeline


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline replay tester for poker_assistant CV/OCR tuning."
    )
    parser.add_argument(
        "--source",
        type=str,
        help="Path to image folder, video file (.mp4, .mkv, .avi) or image file.",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.json",
        help="Path to config.json (default: config.json).",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Maximum number of frames to process.",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Loop replay indefinitely.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Delay in seconds between frames.",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Display OpenCV preview window.",
    )

    args = parser.parse_args()

    if not args.source:
        parser.print_help()
        print("\nError: --source argument is required.")
        return

    source_path = Path(args.source)
    if not source_path.exists():
        print(f"Error: Source path not found: {source_path}")
        return

    print(f"Loading capture from: {source_path}")
    print(f"Using config: {args.config}")

    capture = OfflineReplayCapture(source_path, loop=args.loop)
    pipeline = VisionPipeline(config_path=args.config)

    frame_idx = 0
    latencies: list[float] = []

    try:
        while True:
            if args.max_frames is not None and frame_idx >= args.max_frames:
                break

            frame = capture.grab()
            if frame is None:
                break

            frame_idx += 1
            t0 = time.perf_counter()
            state = pipeline.process_frame(
                frame,
                table_id="offline_table",
                timestamp_ms=int(time.time() * 1000),
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            latencies.append(elapsed_ms)

            stacks = ", ".join(
                f"S{s}:{p.stack}(bet:{p.current_bet})"
                for s, p in sorted(state.players.items())
            )
            print(
                f"[Frame {frame_idx:04d}] {elapsed_ms:5.1f}ms | "
                f"Street: {state.street:<16s} | Hero: {state.hero_cards} | "
                f"Board: {state.board_cards} | Pot: {state.pot} | "
                f"Turn: {state.is_hero_turn} | Actions: {state.available_actions} | {stacks}"
            )

            if args.show:
                cv2.imshow("Offline Tester Preview", frame)
                wait_time = max(1, int(args.delay * 1000)) if args.delay > 0 else 1
                key = cv2.waitKey(wait_time) & 0xFF
                if key in (27, ord("q")):
                    break
            elif args.delay > 0:
                time.sleep(args.delay)

    finally:
        capture.release()
        if args.show:
            cv2.destroyAllWindows()

    if latencies:
        avg_ms = sum(latencies) / len(latencies)
        min_ms = min(latencies)
        max_ms = max(latencies)
        print("\n--- Summary ---")
        print(
            f"Processed: {frame_idx} frames | "
            f"Avg: {avg_ms:.2f}ms | Min: {min_ms:.2f}ms | Max: {max_ms:.2f}ms"
        )
    else:
        print("\nNo frames processed.")


if __name__ == "__main__":
    main()
