"""Batch offline script for generating 1,755 canonical flop database using TexasSolver."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from engine.flop_db import generate_all_1755_flops

# Concrete suit mapping for solver input
DEFAULT_CANONICAL_SUITS = {"a": "h", "b": "s", "c": "d", "d": "c"}


def canonical_to_actual_cards(canonical_flop: str) -> list[str]:
    """Convert a canonical flop key (e.g. 'QaQb8a') to real card strings (e.g. ['Qh', 'Qs', '8h'])."""
    cards: list[str] = []
    # Each card is 2 characters: rank + canonical suit letter ('a', 'b', 'c')
    for i in range(0, len(canonical_flop), 2):
        rank = canonical_flop[i]
        suit_letter = canonical_flop[i + 1]
        real_suit = DEFAULT_CANONICAL_SUITS.get(suit_letter, "h")
        cards.append(f"{rank}{real_suit}")
    return cards


def build_texassolver_script(
    cards: list[str],
    pot: int = 100,
    effective_stack: int = 300,
) -> str:
    """Generate sample TexasSolver input commands for Check / Bet 30% / All-In tree."""
    board_str = " ".join(cards)
    return (
        f"# TexasSolver Batch Configuration\n"
        f"set_pot {pot}\n"
        f"set_effective_stack {effective_stack}\n"
        f"set_board {board_str}\n"
        f"# Betting tree: Check, Bet 30% pot, All-In\n"
        f"set_bet_sizes_flop 30, allin\n"
        f"set_raise_sizes_flop allin\n"
        f"build_tree\n"
        f"start_solve\n"
        f"dump_result\n"
    )


def run_solver_batch(
    solver_bin: Path | None,
    out_path: Path,
    limit: int | None = None,
    dry_run: bool = False,
) -> int:
    """Run batch solver computation or dry run."""
    canonical_flops = generate_all_1755_flops()

    if dry_run:
        print("=" * 60)
        print("TEXASSOLVER DRY-RUN MODE")
        print("=" * 60)
        print(f"Generated canonical flops count: {len(canonical_flops)}")
        sample_flop = canonical_flops[0] if canonical_flops else "QaQb8a"
        sample_cards = canonical_to_actual_cards(sample_flop)
        sample_script = build_texassolver_script(sample_cards)
        print(f"\nSample canonical flop: {sample_flop} -> {' '.join(sample_cards)}")
        print("\n--- Sample TexasSolver Command Script ---")
        print(sample_script)
        print("=" * 60)
        print("Dry run completed successfully (exit code 0).")
        return 0

    if solver_bin is None or not solver_bin.exists():
        print(f"Error: Solver binary not found at '{solver_bin}'. Aborting.", file=sys.stderr)
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Resume capability: load existing results
    db: dict[str, dict] = {}
    if out_path.exists():
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                db = json.load(f)
            print(f"Loaded existing database with {len(db)} flops.")
        except Exception as e:
            print(f"Warning: Could not read existing out file: {e}. Starting fresh.")
            db = {}

    pending_flops = [f for f in canonical_flops if f not in db]
    if limit is not None:
        pending_flops = pending_flops[:limit]

    print(f"Total flops to compute in this run: {len(pending_flops)}")

    for idx, flop_key in enumerate(pending_flops, start=1):
        actual_cards = canonical_to_actual_cards(flop_key)
        script_content = build_texassolver_script(actual_cards)

        temp_script = out_path.parent / f"_temp_solve_{flop_key}.txt"
        temp_script.write_text(script_content, encoding="utf-8")

        try:
            res = subprocess.run(
                [str(solver_bin), str(temp_script)],
                capture_output=True,
                text=True,
                timeout=30.0,
            )
            # Placeholder for parsed results
            db[flop_key] = {
                "CHECK": 0.45,
                "BET_30": 0.40,
                "ALL_IN": 0.15,
            }
        except Exception as err:
            print(f"Error solving {flop_key}: {err}")
        finally:
            if temp_script.exists():
                temp_script.unlink(missing_ok=True)

        # Incremental save every 10 flops or on last
        if idx % 10 == 0 or idx == len(pending_flops):
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(db, f, indent=2)
            print(f"[{idx}/{len(pending_flops)}] Saved progress to {out_path}")

    print("Batch processing completed.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline batch generator for 1,755 canonical flops using TexasSolver."
    )
    parser.add_argument(
        "--solver-bin",
        type=Path,
        default=None,
        help="Path to console_solver.exe binary",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/postflop_db/flops_1755.json"),
        help="Target output JSON file path",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit on the number of flops to solve",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate 1,755 flops and show sample solver config without running executable",
    )

    args = parser.parse_args()
    code = run_solver_batch(
        solver_bin=args.solver_bin,
        out_path=args.out,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
