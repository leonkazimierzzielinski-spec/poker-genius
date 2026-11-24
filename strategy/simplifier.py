"""Deterministic strategy simplification and RTA-profile protection."""

from strategy.multiplier_adapter import ProfileModifiers

ALLOWED_ACTIONS: set[str] = {
    "FOLD",
    "CHECK",
    "CALL",
    "MIN_RAISE",
    "BET_30",
    "BET_SMALL",
    "BET_MED",
    "ALL_IN",
}

VARIANCE_RANKS_HIGH: dict[str, int] = {
    "ALL_IN": 8,
    "MIN_RAISE": 7,
    "BET_MED": 6,
    "BET_30": 5,
    "BET_SMALL": 4,
    "CALL": 3,
    "CHECK": 2,
    "FOLD": 1,
}

VARIANCE_RANKS_STANDARD: dict[str, int] = {
    "CHECK": 8,
    "FOLD": 7,
    "CALL": 6,
    "BET_SMALL": 5,
    "BET_30": 4,
    "BET_MED": 3,
    "MIN_RAISE": 2,
    "ALL_IN": 1,
}


def is_action_available(act: str, available_actions: list[str]) -> bool:
    """Check if candidate action matches the available table actions."""
    avail_set = set(available_actions)
    if act in avail_set:
        return True
    if act in ("BET_30", "BET_SMALL", "BET_MED") and ("BET" in avail_set or "RAISE" in avail_set):
        return True
    if act == "MIN_RAISE" and ("RAISE" in avail_set or "BET" in avail_set):
        return True
    if act == "ALL_IN" and ("ALL_IN" in avail_set or "RAISE" in avail_set or "BET" in avail_set):
        return True
    return False


def quantize_sizing_to_bb(
    target_chips: float,
    big_blind: int,
    hero_stack: int,
    effective_stack: int,
    min_bb_mult: int = 1,
    all_in_threshold_ratio: float = 0.65,
) -> tuple[str, int | None, int]:
    """Zwraca (mode, bb_mult, chips), gdzie mode to 'ALL_IN' albo 'BB_MULT'."""
    bb = max(1, int(big_blind))
    hero_stk = max(0, int(hero_stack))
    eff_stk = max(0, int(effective_stack))
    if hero_stk == 0:
        return ("ALL_IN", None, 0)

    bb_mult = max(min_bb_mult, int(round(target_chips / bb)))
    chips = bb_mult * bb

    # Reguła przejścia w ALL_IN: >= 65% efektywnego stacka, >= stacka Hero lub <= 3 BB przy agresji
    if (
        chips >= hero_stk
        or (eff_stk > 0 and chips >= int(round(all_in_threshold_ratio * eff_stk)))
        or (eff_stk > 0 and eff_stk <= 3 * bb and bb_mult >= 2)
    ):
        return ("ALL_IN", None, hero_stk)

    return ("BB_MULT", bb_mult, chips)


class StrategySimplifier:
    """Simplifies solver strategies to deterministic pure actions with EV-loss filtering."""

    def __init__(self, ev_loss_threshold_bb: float = 0.08):
        self.ev_loss_threshold_bb = ev_loss_threshold_bb

    def select_pure_action(
        self,
        evs: dict[str, float],
        modifiers: ProfileModifiers,
        available_actions: list[str] | None = None,
        threshold_override: float | None = None,
    ) -> tuple[str, float, str | None]:
        """
        Select a deterministic pure action respecting allowed actions and EV-loss threshold.

        Returns:
            Tuple of (chosen_action, chosen_ev, filter_note).
        """
        # 1. Reduction of sizings and filtering allowed actions
        candidates = {k: v for k, v in evs.items() if k in ALLOWED_ACTIONS}
        if not candidates:
            if evs:
                candidates = dict(evs)
            else:
                return "CHECK", 0.0, None

        if available_actions is not None and len(available_actions) > 0:
            avail_candidates = {
                k: v for k, v in candidates.items()
                if is_action_available(k, available_actions)
            }
            if avail_candidates:
                candidates = avail_candidates

            # Never fold when free check is available
            if "CHECK" in available_actions and "CALL" not in available_actions:
                candidates.pop("FOLD", None)

        # 2. Pure strategy: deterministic highest-EV selection
        if modifiers.prefer_high_variance_borderline:
            sorted_candidates = sorted(
                candidates.items(),
                key=lambda item: (round(item[1], 4), VARIANCE_RANKS_HIGH.get(item[0], 0)),
                reverse=True,
            )
        else:
            sorted_candidates = sorted(
                candidates.items(),
                key=lambda item: (round(item[1], 4), VARIANCE_RANKS_STANDARD.get(item[0], 0)),
                reverse=True,
            )

        best_action, best_ev = sorted_candidates[0]

        # 3. Minimum profit threshold (relative EV gain over baseline)
        eff_thresh = (
            self.ev_loss_threshold_bb
            if threshold_override is None
            else max(0.0, float(threshold_override))
        )

        if available_actions is not None and len(available_actions) > 0:
            check_available = is_action_available("CHECK", available_actions)
        else:
            check_available = "CHECK" in candidates

        if check_available:
            baseline_action = "CHECK"
            baseline_ev = float(candidates.get("CHECK", 0.0))
        else:
            baseline_action = "FOLD"
            baseline_ev = float(candidates.get("FOLD", 0.0))

        ev_gain = float(best_ev) - baseline_ev

        chosen_action = best_action
        chosen_ev = best_ev
        filter_note: str | None = None

        if best_action not in ("FOLD", "CHECK") and ev_gain < eff_thresh:
            if (
                modifiers.prefer_high_variance_borderline
                and ev_gain >= 0.0
                and best_action in ("ALL_IN", "CALL")
            ):
                filter_note = "Borderline 0EV high-variance call/shove"
            else:
                chosen_action = baseline_action
                chosen_ev = baseline_ev
                filter_note = f"Filtered marginal play < +{eff_thresh:.2f} BB"

        return chosen_action, chosen_ev, filter_note
