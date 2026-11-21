"""Tool to aggregate all standalone game Markdown reports into a single comprehensive report.

Usage:
    python tools/export_games_md.py [--dir hand_histories] [--out hand_histories/ALL_GAMES_REPORT.md]
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
from typing import Any


def parse_game_summary(md_text: str, filename: str) -> dict[str, Any]:
    """Extract metadata and key stats from a single game markdown report."""
    hands_match = re.search(r"-\s+\*\*Liczba rozdań\*\*:\s*(\d+)", md_text)
    hands_count = int(hands_match.group(1)) if hands_match else len(re.findall(r"^# Rozdanie #", md_text, re.MULTILINE))

    prize_match = re.search(r"-\s+\*\*Pula nagród\*\*:\s*\$?([\d.]+)", md_text)
    if not prize_match:
        fn_match = re.search(r"_prize([\d.]+)", filename)
        prize = float(fn_match.group(1)) if fn_match else None
    else:
        prize = float(prize_match.group(1))

    winner_match = re.search(r"-\s+\*\*Zwycięzca turnieju\*\*:\s*([^\n\r]+)", md_text)
    winner = winner_match.group(1).strip() if winner_match else "—"

    decs_match = re.search(r"-\s+\*\*Decyzje HUD \(Hero\)\*\*:\s*(\d+)", md_text)
    decs_count = int(decs_match.group(1)) if decs_match else 0

    return {
        "filename": filename,
        "hands_count": hands_count,
        "prize_pool": prize,
        "winner": winner,
        "hero_decisions": decs_count,
    }


def export_all_games_md(
    input_dir: str | Path = "hand_histories",
    output_file: str | Path | None = None,
) -> Path:
    """Read all game markdown files and write an aggregated summary report."""
    in_path = Path(input_dir)
    if output_file is None:
        out_path = in_path / "ALL_GAMES_REPORT.md"
    else:
        out_path = Path(output_file)

    if not in_path.exists():
        in_path.mkdir(parents=True, exist_ok=True)

    # Collect markdown files excluding the report itself
    md_files = sorted(
        [
            f
            for f in in_path.glob("*.md")
            if f.name != out_path.name and not f.name.startswith("_")
        ],
        key=lambda p: p.stat().st_mtime,
    )

    summaries = []
    contents = []

    for f in md_files:
        try:
            text = f.read_text(encoding="utf-8")
            s = parse_game_summary(text, f.name)
            summaries.append(s)
            contents.append((f.name, text))
        except Exception:
            pass

    total_games = len(summaries)
    total_hands = sum(s["hands_count"] for s in summaries)
    total_decs = sum(s["hero_decisions"] for s in summaries)

    prize_dist: dict[str, int] = {}
    for s in summaries:
        p = s["prize_pool"]
        key = f"${p:g}" if p is not None else "Nieznana"
        prize_dist[key] = prize_dist.get(key, 0) + 1

    prize_str = ", ".join(f"{k}: {v}" for k, v in sorted(prize_dist.items())) or "—"

    lines = [
        "# 🏆 Zbiorczy Raport Wszystkich Gier (Poker Genius)",
        "",
        "## 📊 Tabela Zbiorcza Sesji",
        f"- **Liczba rozegranych gier**: {total_games}",
        f"- **Łączna liczba rozdań**: {total_hands}",
        f"- **Łączna liczba decyzji HUD (Hero)**: {total_decs}",
        f"- **Rozkład pul nagród**: {prize_str}",
        "",
        "| Plik gry | Rozdania | Pula nagród | Zwycięzca | Decyzje Hero |",
        "|---|:---:|:---:|:---:|:---:|",
    ]

    for s in summaries:
        p_str = f"${s['prize_pool']:g}" if s["prize_pool"] is not None else "--"
        lines.append(
            f"| `{s['filename']}` | {s['hands_count']} | {p_str} | {s['winner']} | {s['hero_decisions']} |"
        )

    lines.extend(["", "---", "", "## 📜 Szczegóły Rozegranych Gier", ""])

    for fname, text in contents:
        lines.append(f"### 🎮 Gra: `{fname}`")
        lines.append("")
        lines.append(text.strip())
        lines.append("")
        lines.append("---")
        lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Export all game markdown reports into one file.")
    parser.add_argument(
        "--dir", default="hand_histories", help="Directory containing game markdown files."
    )
    parser.add_argument(
        "--out", default=None, help="Output markdown report path."
    )
    args = parser.parse_args()

    out_p = export_all_games_md(input_dir=args.dir, output_file=args.out)
    print(f"Exported all games report successfully to: {out_p}")


if __name__ == "__main__":
    main()
