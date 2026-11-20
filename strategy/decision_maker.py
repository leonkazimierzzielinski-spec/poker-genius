"""Decision maker facade combining profile adaptation, exploits, and simplification."""

from typing import Any

try:
    from core.constants import EV_LOSS_THRESHOLD_BB
    from core.contracts import Decision, TableState
except ImportError:
    EV_LOSS_THRESHOLD_BB = 0.08
    Decision = Any  # type: ignore
    TableState = Any  # type: ignore

from strategy.exploit import ExploitEngine
from strategy.multiplier_adapter import MultiplierAdapter
from strategy.simplifier import StrategySimplifier


class DecisionMaker:
    """Main facade for strategy decisions."""

    def __init__(
        self,
        buy_in: float | int = 2.0,
        ev_loss_threshold_bb: float = EV_LOSS_THRESHOLD_BB,
    ):
        self.buy_in = buy_in
        self.ev_loss_threshold_bb = ev_loss_threshold_bb
        self.adapter = MultiplierAdapter()
        self.exploit_engine = ExploitEngine()
        self.simplifier = StrategySimplifier(ev_loss_threshold_bb=ev_loss_threshold_bb)

    def decide(
        self,
        state: Any,
        candidate_evs: dict[str, float],
        spot: str = "POSTFLOP",
        confidence: float = 0.95,
        paid_places: int = 1,
        allow_preview: bool = False,
    ) -> Any:
        """
        Produce a pure deterministic decision with exploitative modifications.
        """
        table_id = getattr(state, "table_id", "default")
        is_valid = getattr(state, "is_valid", False)
        is_hero_turn = getattr(state, "is_hero_turn", False)
        street = getattr(state, "street", "")

        hero_cards = getattr(state, "hero_cards", [])
        if not is_valid or len(hero_cards) != 2:
            reason = "Waiting for Hero turn"
            if len(hero_cards) != 2:
                reason = "Incomplete hero cards (need 2)"
            return Decision(
                table_id=table_id,
                action="WAIT",
                ev_bb=None,
                confidence=1.0,
                profile_used="STANDARD_EXPLOIT",
                reason=reason,
            )

        is_preview = bool(allow_preview)
        if not is_hero_turn or street == "WAITING_FOR_TURN":
            if not allow_preview:
                return Decision(
                    table_id=table_id,
                    action="WAIT",
                    ev_bb=None,
                    confidence=1.0,
                    profile_used="STANDARD_EXPLOIT",
                    reason="Waiting for Hero turn",
                )

        prize_pool = getattr(state, "prize_pool", 4)
        modifiers = self.adapter.get_modifiers(
            prize_pool=prize_pool,
            buy_in=self.buy_in,
            paid_places=paid_places,
        )

        exploited_evs, reasons = self.exploit_engine.apply_exploits(
            candidate_evs=candidate_evs,
            state=state,
            modifiers=modifiers,
            spot=spot,
        )

        available_actions = getattr(state, "available_actions", None)
        action, ev_bb, filter_note = self.simplifier.select_pure_action(
            evs=exploited_evs,
            modifiers=modifiers,
            available_actions=available_actions,
        )

        if filter_note:
            reasons.append(filter_note)

        prefix = "[PLAN] " if is_preview else ""
        if reasons:
            reason_str = prefix + "; ".join(reasons)
            if len(reason_str) > 80:
                reason_str = reason_str[:77] + "..."
        else:
            reason_str = f"{prefix}Profile {modifiers.profile_name}"

        return Decision(
            table_id=table_id,
            action=action,
            ev_bb=round(ev_bb, 4) if ev_bb is not None else None,
            confidence=confidence,
            profile_used=modifiers.profile_name,
            reason=reason_str,
        )
