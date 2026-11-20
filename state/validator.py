"""Table state validation and sanity checks for poker_assistant."""

from core.constants import TOTAL_CHIPS
from core.contracts import TableState


class StateValidator:
    """Validates TableState frames for chip conservation, card uniqueness, and blinds monotonicity."""

    def __init__(self, total_chips: int = TOTAL_CHIPS) -> None:
        self.total_chips = total_chips
        self._last_blinds: dict[str, tuple[int, int]] = {}

    def reset_table(self, table_id: str) -> None:
        """Removes blinds history for a table (e.g. after tournament ends)."""
        self._last_blinds.pop(table_id, None)

    def validate(self, state: TableState) -> tuple[bool, list[str]]:
        """Validate state against 3 golden rules:

        1. Chip conservation: exactly 3 players, no None stack, no negative values, sum == total_chips.
        2. Card uniqueness and count: 0 or 2 hero cards, 0/3/4/5 board cards, no duplicates.
        3. Blinds monotonicity: small_blind > 0, big_blind > small_blind, not decreasing.
        """
        errors: list[str] = []

        # Rule 1: Chip conservation (== total_chips, default 900)
        # Supports 3-max (3 active players) and Heads-Up (2 active players, 1 eliminated)
        if len(state.players) != 3:
            errors.append(f"Expected 3 players, got {len(state.players)}")

        has_negative_chips = False
        if state.pot < 0:
            has_negative_chips = True

        for p in state.players.values():
            if p.stack is not None and p.stack < 0:
                has_negative_chips = True
            if p.current_bet < 0:
                has_negative_chips = True

        if has_negative_chips:
            errors.append("Negative chip value detected")

        valid_players = [p for p in state.players.values() if p.stack is not None]
        none_stack_players = [p for p in state.players.values() if p.stack is None]

        # Case A: 3-max (all 3 players have stacks)
        if len(valid_players) == 3:
            if not has_negative_chips:
                chip_sum = state.pot + sum(p.stack + p.current_bet for p in valid_players)
                chip_sum_pot_stacks = state.pot + sum(p.stack for p in valid_players)
                if chip_sum != self.total_chips and chip_sum_pot_stacks != self.total_chips:
                    errors.append(f"Chip conservation failed: {chip_sum} != {self.total_chips}")

        # Case B: at least 1 player has stack is None (All-In player or Heads-Up eliminated player)
        elif len(none_stack_players) >= 1:
            present_players = sum(1 for p in state.players.values() if (p.stack is not None or p.current_bet > 0))
            sum_with_bets = state.pot + sum((p.stack or 0) + p.current_bet for p in state.players.values())
            sum_pot_stacks = state.pot + sum((p.stack or 0) for p in state.players.values())

            # Rule of acceptance:
            # - Heads-Up: exactly 1 eliminated player (stack is None, bet == 0) and remaining 2 players sum to total_chips
            # - All-In: player with stack is None has bet > 0 (or pot == total_chips), present_players >= 2, and sum is valid
            is_valid_conservation = (sum_with_bets == self.total_chips or sum_pot_stacks == self.total_chips)

            if is_valid_conservation and (
                (len(none_stack_players) == 1 and none_stack_players[0].current_bet == 0 and len(valid_players) == 2)
                or (present_players >= 2 and any(p.current_bet > 0 for p in none_stack_players))
                or (len(valid_players) >= 1 and state.pot == self.total_chips)
            ):
                if not has_negative_chips:
                    pass
            else:
                errors.append("Missing stack reading")

        else:
            errors.append("Missing stack reading")

        # Rule 2: Card uniqueness and validity
        all_cards = list(state.hero_cards) + list(state.board_cards)
        if len(all_cards) != len(set(all_cards)):
            errors.append("Duplicate cards detected")

        if len(state.hero_cards) not in (0, 2) or len(state.board_cards) not in (0, 3, 4, 5):
            errors.append("Invalid card count")

        # Rule 2b: Postflop pot sanity check (unrecognized board protection)
        all_bets_zero = all(p.current_bet == 0 for p in state.players.values())
        max_preflop_limp_pot = max(state.small_blind + state.big_blind * 2, state.big_blind * 3)
        if (
            len(state.board_cards) == 0
            and state.pot > max_preflop_limp_pot
            and all_bets_zero
            and state.pot < self.total_chips
        ):
            errors.append("Missing board cards on postflop pot")

        # Rule 3: Blinds monotonicity
        if not (state.small_blind > 0 and state.big_blind > state.small_blind):
            errors.append("Invalid blinds")
        elif state.table_id in self._last_blinds:
            prev_sb, prev_bb = self._last_blinds[state.table_id]
            if state.small_blind < prev_sb or state.big_blind < prev_bb:
                errors.append(
                    f"Blinds decreased from {(prev_sb, prev_bb)} to {(state.small_blind, state.big_blind)}"
                )

        is_valid = len(errors) == 0
        if is_valid:
            self._last_blinds[state.table_id] = (state.small_blind, state.big_blind)

        return is_valid, errors

    def validate_and_mark(self, state: TableState) -> TableState:
        """Validates state, sets state.is_valid, and returns state."""
        is_valid, _ = self.validate(state)
        state.is_valid = is_valid
        return state
