"""Monte Carlo equity and EV calculator for poker postflop spots."""

from __future__ import annotations

import random
import time

try:
    from phevaluator import evaluate_cards
except ImportError:
    evaluate_cards = None  # Fallback will raise informative ImportError if called

FULL_DECK = [f"{r}{s}" for r in "23456789TJQKA" for s in "cdhs"]


class MonteCarloCalculator:
    """Fast Monte Carlo Equity and EV simulator (< 0.1 s)."""

    def __init__(self) -> None:
        if evaluate_cards is None:
            raise ImportError(
                "phevaluator is required for MonteCarloCalculator. "
                "Please install it with `pip install phevaluator`."
            )

    def estimate_equity(
        self,
        hero_cards: list[str],
        board_cards: list[str],
        villain_range: list[tuple[str, str]] | None = None,
        iterations: int = 2000,
        time_budget_ms: float = 80.0,
        num_opponents: int = 1,
    ) -> float:
        """Estimate Hero equity against random cards or villain range.

        Args:
            hero_cards: List of 2 cards (e.g. ["As", "Ah"]).
            board_cards: List of 0, 3, 4, or 5 cards (e.g. ["Kd", "7c", "2s"]).
            villain_range: Optional list of 2-card tuples for Villain.
            iterations: Maximum number of Monte Carlo iterations.
            time_budget_ms: Maximum time allowed in milliseconds.
            num_opponents: Number of active opponents (1 for Heads-Up, 2 for 3-Way).

        Returns:
            Equity as a float in range [0.0, 1.0].
        """
        # Normalize cards representation
        hero_norm = [f"{c[0].upper()}{c[1].lower()}" for c in hero_cards]
        board_norm = [f"{c[0].upper()}{c[1].lower()}" for c in board_cards]

        known_cards = set(hero_norm) | set(board_norm)
        deck = [c for c in FULL_DECK if c not in known_cards]
        missing_board_count = max(0, 5 - len(board_norm))

        # Filter valid villain combos if range is provided
        valid_villain: list[tuple[str, str]] = []
        if villain_range:
            for c1, c2 in villain_range:
                v1 = f"{c1[0].upper()}{c1[1].lower()}"
                v2 = f"{c2[0].upper()}{c2[1].lower()}"
                if v1 not in known_cards and v2 not in known_cards and v1 != v2:
                    valid_villain.append((v1, v2))

        start_time = time.perf_counter()
        time_limit_sec = time_budget_ms / 1000.0

        wins = 0.0
        simulations = 0

        num_opps = max(1, num_opponents)

        while simulations < iterations:
            # Check budget every 50 iterations to avoid perf_counter overhead
            if simulations % 50 == 0 and (time.perf_counter() - start_time) >= time_limit_sec:
                break

            if num_opps <= 1:
                if valid_villain:
                    v1, v2 = random.choice(valid_villain)
                    if missing_board_count > 0:
                        avail_deck = [c for c in deck if c != v1 and c != v2]
                        drawn_board = random.sample(avail_deck, missing_board_count)
                    else:
                        drawn_board = []
                else:
                    needed = missing_board_count + 2
                    sampled = random.sample(deck, needed)
                    drawn_board = sampled[:missing_board_count]
                    v1, v2 = sampled[missing_board_count], sampled[missing_board_count + 1]

                full_board = board_norm + drawn_board

                # In phevaluator, a LOWER score means a stronger hand
                hero_score = evaluate_cards(*(hero_norm + full_board))
                villain_score = evaluate_cards(v1, v2, *full_board)

                if hero_score < villain_score:
                    wins += 1.0
                elif hero_score == villain_score:
                    wins += 0.5
            else:
                # Multiway (num_opponents >= 2)
                if valid_villain:
                    v1, v2 = random.choice(valid_villain)
                    avail_deck = [c for c in deck if c != v1 and c != v2]
                    needed_other = missing_board_count + 2 * (num_opps - 1)
                    sampled = random.sample(avail_deck, needed_other)
                    drawn_board = sampled[:missing_board_count]
                    other_cards = sampled[missing_board_count:]
                    opp_hands = [(v1, v2)] + [
                        (other_cards[2 * i], other_cards[2 * i + 1])
                        for i in range(num_opps - 1)
                    ]
                else:
                    needed = missing_board_count + 2 * num_opps
                    sampled = random.sample(deck, needed)
                    drawn_board = sampled[:missing_board_count]
                    opp_cards = sampled[missing_board_count:]
                    opp_hands = [
                        (opp_cards[2 * i], opp_cards[2 * i + 1])
                        for i in range(num_opps)
                    ]

                full_board = board_norm + drawn_board
                hero_score = evaluate_cards(*(hero_norm + full_board))
                opp_scores = [evaluate_cards(c1, c2, *full_board) for c1, c2 in opp_hands]
                best_opp_score = min(opp_scores)

                if hero_score < best_opp_score:
                    wins += 1.0
                elif hero_score == best_opp_score:
                    ties_count = 1 + opp_scores.count(hero_score)
                    wins += 1.0 / ties_count

            simulations += 1

        if simulations == 0:
            return 0.5

        return round(wins / simulations, 4)

    def calculate_ev_bb(
        self,
        equity: float,
        pot_bb: float,
        call_cost_bb: float,
        fold_equity: float = 0.0,
    ) -> float:
        """Calculate Expected Value (EV) in big blinds.

        Args:
            equity: Win rate [0.0, 1.0].
            pot_bb: Current pot size in BB before Hero's action.
            call_cost_bb: Amount Hero has to put into the pot.
            fold_equity: Probability Villain folds to Hero's shove/bet [0.0, 1.0].

        Returns:
            EV in big blinds (BB).
        """
        showdown_ev = equity * (pot_bb + call_cost_bb) - (1.0 - equity) * call_cost_bb

        if fold_equity == 0.0:
            return round(showdown_ev, 3)

        total_ev = fold_equity * pot_bb + (1.0 - fold_equity) * showdown_ev
        return round(total_ev, 3)
