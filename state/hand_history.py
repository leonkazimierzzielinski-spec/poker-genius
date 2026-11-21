"""Hand history recorder for poker_assistant.

Saves completed hands to session JSONL and readable Markdown files
without blocking real-time video processing.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any


class HandHistoryRecorder:
    """Records completed hands to .jsonl and .md session files."""

    def __init__(self, output_dir: str | Path = "hand_histories") -> None:
        self.output_dir = Path(output_dir)
        self._jsonl_path: Path | None = None
        self._md_path: Path | None = None
        self._jsonl_file: Any = None
        self._md_file: Any = None
        self._initialized: bool = False
        self._recorded_keys: set[tuple[str, int]] = set()

    def _ensure_init(self) -> None:
        if self._initialized:
            return
        self.output_dir.mkdir(parents=True, exist_ok=True)
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._jsonl_path = self.output_dir / f"session_{ts_str}.jsonl"
        self._md_path = self.output_dir / f"session_{ts_str}.md"
        self._jsonl_file = open(self._jsonl_path, "a", encoding="utf-8")
        self._md_file = open(self._md_path, "a", encoding="utf-8")
        self._initialized = True

    def record_hand(self, hand_summary: dict[str, Any]) -> None:
        """Append completed hand to .jsonl and .md files."""
        if not hand_summary:
            return

        hero_cards = hand_summary.get("hero_cards") or []
        action_log = hand_summary.get("action_log") or []
        # Skip empty hands (no hero cards and no recorded actions)
        if not hero_cards and not action_log:
            return

        table_id = str(hand_summary.get("table_id") or "table_1")
        hand_number = int(hand_summary.get("hand_number") or 1)
        record_key = (table_id, hand_number)
        if record_key in self._recorded_keys:
            return
        self._recorded_keys.add(record_key)

        self._ensure_init()

        # 1. JSONL write
        try:
            line = json.dumps(hand_summary, ensure_ascii=False)
            self._jsonl_file.write(line + "\n")
            self._jsonl_file.flush()
        except Exception:
            pass

        # 2. Markdown write
        try:
            self._write_markdown_hand(hand_summary)
            self._md_file.flush()
        except Exception:
            pass

    def _write_markdown_hand(self, hand: dict[str, Any]) -> None:
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
            folded = p.get("folded", False)
            status_str = "FOLD" if folded else "ACTIVE"
            last_act = p.get("last_action") or "—"
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
                "### Rekomendacje HUD",
                "| Ulica | Akcja | Sizing BB | Sizing Chips | EV (BB) | Uzasadnienie |",
                "|:---:|:---:|:---:|:---:|:---:|---|",
            ])
            for r in recs:
                st = r.get("street", "--")
                act = r.get("action", "--")
                s_bb = r.get("sizing_bb")
                s_bb_str = f"{s_bb} BB" if s_bb is not None else "—"
                s_ch = r.get("sizing_chips")
                s_ch_str = str(s_ch) if s_ch is not None else "—"
                ev = r.get("ev_bb")
                ev_str = f"{ev:+.2f} BB" if ev is not None else "—"
                rsn = r.get("reason", "")
                lines.append(f"| {st} | {act} | {s_bb_str} | {s_ch_str} | {ev_str} | {rsn} |")

        lines.extend(["", "---", ""])
        self._md_file.write("\n".join(lines) + "\n")

    def close(self, active_trackers: dict[str, Any] | None = None) -> None:
        """Close recorder files, saving any active hand in flight."""
        if active_trackers:
            for tid, tracker in active_trackers.items():
                if hasattr(tracker, "get_hand_summary"):
                    try:
                        summary = tracker.get_hand_summary()
                        if summary and (summary.get("hero_cards") or summary.get("action_log")):
                            self.record_hand(summary)
                    except Exception:
                        pass

        if self._jsonl_file is not None:
            try:
                self._jsonl_file.close()
            except Exception:
                pass
            self._jsonl_file = None

        if self._md_file is not None:
            try:
                self._md_file.close()
            except Exception:
                pass
            self._md_file = None
