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
        ev_loss_threshold_bb: float = 0.03,
        preflop_ev_loss_threshold_bb: float = 0.0,
    ):
        self.buy_in = buy_in
        self.ev_loss_threshold_bb = ev_loss_threshold_bb
        self.preflop_ev_loss_threshold_bb = preflop_ev_loss_threshold_bb
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

        # Determine if check is free (to_call == 0)
        players = getattr(state, "players", {}) or {}
        hero_p = players.get(0) if isinstance(players, dict) else (players[0] if len(players) > 0 else None)

        def _get_player_bet(p: Any) -> int:
            if p is None:
                return 0
            val = getattr(p, "current_bet", None)
            if val is None:
                val = getattr(p, "bet", 0)
            return int(val or 0)

        hero_bet = _get_player_bet(hero_p)
        opp_bets = [
            _get_player_bet(p)
            for s_id, p in (players.items() if isinstance(players, dict) else enumerate(players))
            if s_id != 0 and p is not None and getattr(p, "is_active", True)
        ]
        max_opp_bet = max(opp_bets) if opp_bets else 0
        to_call = max(0, max_opp_bet - hero_bet)

        available_actions = getattr(state, "available_actions", None)
        has_check = bool(available_actions and "CHECK" in available_actions)
        facing_bet = (to_call > 0) or (available_actions is not None and "CALL" in available_actions)

        # Hard safety rule: Never fold when free check is available
        clean_evs = dict(candidate_evs)
        if not facing_bet or (has_check and to_call == 0):
            clean_evs = {k: v for k, v in clean_evs.items() if k != "FOLD"}
            if "CHECK" not in clean_evs and (available_actions is None or "CHECK" in available_actions):
                clean_evs["CHECK"] = 0.0

        exploited_evs, reasons = self.exploit_engine.apply_exploits(
            candidate_evs=clean_evs,
            state=state,
            modifiers=modifiers,
            spot=spot,
        )

        if not facing_bet or (has_check and to_call == 0):
            exploited_evs = {k: v for k, v in exploited_evs.items() if k != "FOLD"}

        is_preflop_decision = (
            street == "PREFLOP"
            or spot in (
                "BTN_OPEN", "SB_OPEN", "SB_BVB", "HU_SB",
                "BB_VS_LIMP", "BB_ISO_VS_LIMP", "BB_VS_MR",
                "BB_VS_BTN_RAISE", "BB_VS_SB_RAISE", "SB_VS_BTN_RAISE",
                "BB_VS_BTN_SHOVE", "BB_VS_SB_SHOVE", "SB_VS_BTN_SHOVE",
                "BB_VS_SHOVE", "SB_VS_BTN",
            )
        )
        eff_thresh = (
            self.preflop_ev_loss_threshold_bb
            if is_preflop_decision
            else self.ev_loss_threshold_bb
        )

        action, ev_bb, filter_note = self.simplifier.select_pure_action(
            evs=exploited_evs,
            modifiers=modifiers,
            available_actions=available_actions,
            threshold_override=eff_thresh,
        )

        if filter_note:
            reasons.append(filter_note)

        # Alt action computation: if 2nd best legal action is within 0.05 BB
        alt_action: str | None = None
        alt_ev_bb: float | None = None
        if ev_bb is not None:
            from strategy.simplifier import is_action_available
            legal_evs = {
                k: v for k, v in exploited_evs.items()
                if (available_actions is None or is_action_available(k, available_actions))
                and k != action
            }
            if not facing_bet or (has_check and to_call == 0):
                legal_evs.pop("FOLD", None)

            if legal_evs:
                sorted_alt = sorted(legal_evs.items(), key=lambda it: it[1], reverse=True)
                cand_act, cand_ev = sorted_alt[0]
                if cand_ev >= ev_bb - 0.05:
                    alt_action = cand_act
                    alt_ev_bb = round(cand_ev, 4)

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
            alt_action=alt_action,
            alt_ev_bb=alt_ev_bb,
        )
