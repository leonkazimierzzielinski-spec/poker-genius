"""Hand history recorder for poker_assistant.

Saves completed hands to per-game working directories and automatically packs
each completed game into a standalone .zip archive with structural JSONL,
readable Markdown report, and optional lightweight JPEG snapshots.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import shutil
from typing import Any
import zipfile


class HandHistoryRecorder:
    """Records completed hands per active game and packages them into standalone .zip archives."""

    def __init__(
        self,
        output_dir: str | Path = "hand_histories",
        save_snapshots: bool = True,
        snapshot_width: int = 640,
        snapshot_jpeg_quality: int = 65,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.save_snapshots = bool(save_snapshots)
        self.snapshot_width = int(snapshot_width)
        self.snapshot_jpeg_quality = int(snapshot_jpeg_quality)
        self._active_games: dict[str, dict[str, Any]] = {}

    def _get_or_create_game(
        self, table_id: str, prize_pool: float | int | None = None
    ) -> dict[str, Any]:
        """Retrieve or create active game directory context for table_id."""
        if table_id not in self._active_games:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            game_dir = self.output_dir / "_active" / f"game_{ts_str}_{table_id}"
            game_dir.mkdir(parents=True, exist_ok=True)

            self._active_games[table_id] = {
                "ts_str": ts_str,
                "dir": game_dir,
                "jsonl_path": game_dir / "history.jsonl",
                "md_path": game_dir / "history.md",
                "hands_count": 0,
                "recorded_keys": set(),
                "prize_pool": prize_pool,
            }

        game = self._active_games[table_id]
        if prize_pool is not None and game.get("prize_pool") is None:
            game["prize_pool"] = prize_pool
        return game

    def record_hand(self, hand_summary: dict[str, Any]) -> None:
        """Append completed hand to the active game's JSONL and Markdown files."""
        if not hand_summary:
            return

        hero_cards = hand_summary.get("hero_cards") or []
        action_log = hand_summary.get("action_log") or []
        # Skip empty hands (no hero cards and no recorded actions)
        if not hero_cards and not action_log:
            return

        table_id = str(hand_summary.get("table_id") or "table_1")
        hand_number = int(hand_summary.get("hand_number") or 1)
        prize_pool = hand_summary.get("prize_pool")

        game = self._get_or_create_game(table_id, prize_pool)
        record_key = (table_id, hand_number)
        if record_key in game["recorded_keys"]:
            return
        game["recorded_keys"].add(record_key)
        game["hands_count"] += 1

        if prize_pool is not None:
            game["prize_pool"] = prize_pool

        # 1. JSONL write
        try:
            line = json.dumps(hand_summary, ensure_ascii=False)
            with open(game["jsonl_path"], "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

        # 2. Markdown write
        try:
            md_text = self._render_hand_markdown(hand_summary)
            with open(game["md_path"], "a", encoding="utf-8") as f:
                f.write(md_text + "\n")
        except Exception:
            pass

    def _render_hand_markdown(self, hand: dict[str, Any]) -> str:
        """Render readable markdown representation for a single hand."""
        table_id = hand.get("table_id") or "table_1"
        hand_number = hand.get("hand_number") or 1
        start_ts = hand.get("start_ts_ms") or 0
        if start_ts >= 100_000_000_000:
            time_str = datetime.fromtimestamp(start_ts / 1000.0).strftime("%H:%M:%S")
        else:
            tot_s = int(start_ts / 1000.0)
            time_str = f"{tot_s // 60:02d}:{tot_s % 60:02d}"

        sb, bb = hand.get("blinds") or (0, 0)
        prize = hand.get("prize_pool")
        prize_str = f"${prize}" if prize is not None else "--"
        pot = hand.get("pot", 0)

        hero_cards = " ".join(hand.get("hero_cards") or []) or "—"
        board_cards = " ".join(hand.get("board_cards") or []) or "—"

        lines = [
            f"# Rozdanie #{hand_number} ({time_str}) — Blinds {sb}/{bb} | Prize {prize_str}",
            "",
            f"- **Stół**: {table_id}",
            f"- **Moje karty**: {hero_cards}",
            f"- **Karty na stole**: {board_cards}",
            f"- **Pula końcowa**: {pot}",
            "",
            "### Gracze",
            "| Gracz | Pozycja | Stack | Włożył | Status | Ostatnia akcja |",
            "|---|:---:|:---:|:---:|:---:|---|",
        ]

        players = hand.get("players") or {}
        for sid in (0, 1, 2):
            p = players.get(sid) or players.get(str(sid))
            if not p:
                continue
            name = p.get("name") or (f"S{sid}")
            is_dealer = p.get("is_dealer", False)
            pos_tag = "D" if is_dealer else "—"
            stack = p.get("stack")
            stack_str = str(stack) if stack is not None else "--"
            invested = p.get("invested_total", 0)

            eliminated = p.get("eliminated") or p.get("status") == "OUT" or (stack is None and not p.get("is_active", True))
            folded = p.get("folded", False)
            if eliminated:
                status_str = "OUT"
            elif folded:
                status_str = "FOLD"
            else:
                status_str = "ACTIVE"

            last_act = p.get("last_action") or ("OUT" if eliminated else "—")
            lines.append(f"| {name} | {pos_tag} | {stack_str} | {invested} | {status_str} | {last_act} |")

        action_log = hand.get("action_log") or []
        if action_log:
            lines.extend([
                "",
                "### Przebieg zagrań",
                "| Czas | Ulica | Gracz | Akcja | Kwota | Łącznie włożył | Czas decyzji |",
                "|:---:|:---:|---|:---:|:---:|:---:|:---:|",
            ])
            for act in action_log:
                t_str = act.get("time_str", "--")
                street = act.get("street", "--")
                p_name = act.get("player_name") or f"S{act.get('seat_id', '--')}"
                a_name = act.get("action", "--")
                amount = act.get("amount", 0)
                inv = act.get("invested_total", amount)
                dec_s = act.get("decision_sec")
                dec_str = f"{dec_s}s" if dec_s is not None else "—"
                lines.append(f"| {t_str} | {street} | {p_name} | {a_name} | {amount} | {inv} | {dec_str} |")

        recs = hand.get("recommendations") or []
        if recs:
            lines.extend([
                "",
                "### Podjęte decyzje: HUD vs Hero (Rekomendacje HUD)",
                "| Ulica | Rekomendacja HUD | Sizing | EV (BB) | Akcja Hero | Czas decyzji | Uzasadnienie |",
                "|:---:|:---:|:---:|:---:|:---:|:---:|---|",
            ])
            for r in recs:
                st = r.get("street", "--")
                act = r.get("action", "--")
                s_bb = r.get("sizing_bb")
                s_ch = r.get("sizing_chips")
                if s_bb is not None:
                    sizing_str = f"{s_bb} BB"
                elif s_ch is not None:
                    sizing_str = str(s_ch)
                else:
                    sizing_str = "—"
                ev = r.get("ev_bb")
                ev_str = f"{ev:+.2f} BB" if ev is not None else "—"
                rsn = r.get("reason", "")

                # Search matching Hero action from action_log on this street
                hero_acts = [a for a in action_log if a.get("seat_id") == 0 and a.get("street") == st]
                if hero_acts:
                    last_h = hero_acts[-1]
                    h_act = last_h.get("action", "—")
                    if last_h.get("amount") and h_act not in ("CHECK", "FOLD"):
                        h_act = f"{h_act} {last_h['amount']}"
                    h_dec = last_h.get("decision_sec")
                    h_dec_str = f"{h_dec}s" if h_dec is not None else "—"
                else:
                    h_act = "—"
                    h_dec_str = "—"

                lines.append(f"| {st} | {act} | {sizing_str} | {ev_str} | {h_act} | {h_dec_str} | {rsn} |")

        # Hand result
        res = hand.get("result")
        if res:
            w_name = res.get("winner_name", "—")
            delta = res.get("net_delta", 0)
            lines.extend([
                "",
                "### Wynik rozdania",
                f"- **Zwycięzca**: {w_name} (+{delta} żetonów)",
            ])

        # Snapshots
        snaps = hand.get("snapshots") or []
        if snaps:
            lines.extend(["", "### Zrzuty ekranu"])
            for snap in snaps:
                lines.append(f"![{snap}]({snap})")

        # Tournament Result
        tr = hand.get("tournament_result")
        if tr:
            w_name = tr.get("winner_name", "—")
            w_seat = tr.get("winner_seat", 0)
            p_pool = tr.get("prize_pool")
            p_pool_str = f"${p_pool}" if p_pool is not None else "--"
            f_stack = tr.get("final_stack", 900)
            lines.extend([
                "",
                "## 🏆 KONIEC STOŁU — Zwycięzca turnieju",
                f"- **Zwycięzca**: {w_name} (S{w_seat})",
                f"- **Pula nagród**: {p_pool_str}",
                f"- **Końcowy stack**: {f_stack}",
            ])

        lines.extend(["", "---", ""])
        return "\n".join(lines)

    def save_snapshot(
        self,
        frame_bgr: Any,
        table_rect: tuple[int, int, int, int] | list[int] | None,
        table_id: str,
        hand_number: int,
        event_label: str,
    ) -> str | None:
        """Crop and save a lightweight 640px JPEG snapshot to the active game's snapshots folder."""
        if not self.save_snapshots or frame_bgr is None or table_rect is None:
            return None

        try:
            import cv2
        except ImportError:
            return None

        try:
            x, y, w, h = int(table_rect[0]), int(table_rect[1]), int(table_rect[2]), int(table_rect[3])
            fx1 = max(0, x)
            fy1 = max(0, y)
            fx2 = min(frame_bgr.shape[1], x + w)
            fy2 = min(frame_bgr.shape[0], y + h)

            if fx2 <= fx1 or fy2 <= fy1:
                return None

            crop = frame_bgr[fy1:fy2, fx1:fx2]
            target_w = self.snapshot_width
            target_h = max(1, int(round(crop.shape[0] * (float(target_w) / crop.shape[1]))))
            resized = cv2.resize(crop, (target_w, target_h), interpolation=cv2.INTER_AREA)

            game = self._get_or_create_game(table_id)
            snaps_dir = game["dir"] / "snapshots"
            snaps_dir.mkdir(parents=True, exist_ok=True)

            fname = f"h{hand_number:03d}_{event_label}.jpg"
            full_path = snaps_dir / fname
            cv2.imwrite(
                str(full_path),
                resized,
                [int(cv2.IMWRITE_JPEG_QUALITY), self.snapshot_jpeg_quality],
            )
            rel_path = f"snapshots/{fname}"
            return rel_path
        except Exception:
            return None

    def finalize_game(
        self, table_id: str, prize_pool: float | int | None = None
    ) -> Path | None:
        """Packs the active game directory for table_id into a standalone .zip and deletes the working folder."""
        game = self._active_games.get(table_id)
        if not game:
            return None

        game_dir = game["dir"]
        hands_count = game["hands_count"]

        # If no hands recorded, remove directory and discard
        if hands_count == 0:
            shutil.rmtree(game_dir, ignore_errors=True)
            self._active_games.pop(table_id, None)
            return None

        ts_str = game["ts_str"]
        prize = prize_pool if prize_pool is not None else game.get("prize_pool")
        prize_part = f"_prize{prize}" if prize is not None else ""
        zip_name = f"game_{ts_str}_{table_id}{prize_part}.zip"
        zip_path = self.output_dir / zip_name
        self.output_dir.mkdir(parents=True, exist_ok=True)

        try:
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for file_path in sorted(game_dir.rglob("*")):
                    if file_path.is_file():
                        arcname = file_path.relative_to(game_dir)
                        zf.write(file_path, arcname=str(arcname))
            shutil.rmtree(game_dir, ignore_errors=True)
        except Exception:
            return None

        self._active_games.pop(table_id, None)

        active_root = self.output_dir / "_active"
        if active_root.exists() and not any(active_root.iterdir()):
            shutil.rmtree(active_root, ignore_errors=True)

        return zip_path

    def close(self, active_trackers: dict[str, Any] | None = None) -> list[Path]:
        """Record active in-flight hands and finalize all active games into standalone .zip archives."""
        if active_trackers:
            for tid, tracker in list(active_trackers.items()):
                if hasattr(tracker, "get_hand_summary"):
                    try:
                        summary = tracker.get_hand_summary()
                        if summary and (summary.get("hero_cards") or summary.get("action_log")):
                            self.record_hand(summary)
                    except Exception:
                        pass

        created_zips: list[Path] = []
        for tid in list(self._active_games.keys()):
            z = self.finalize_game(tid)
            if z is not None:
                created_zips.append(z)

        active_root = self.output_dir / "_active"
        if active_root.exists() and not any(active_root.iterdir()):
            shutil.rmtree(active_root, ignore_errors=True)

        return created_zips
