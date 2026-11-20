"""Multiplier profile adapter for poker_assistant."""

from dataclasses import dataclass


@dataclass
class ProfileModifiers:
    profile_name: str
    bluff_factor: float = 1.0
    steal_boost_bb: float = 0.0
    value_shove_boost_bb: float = 0.0
    prefer_high_variance_borderline: bool = False
    use_icm: bool = False


class MultiplierAdapter:
    """Adapts aggression profiles based on prize pool multiplier."""

    def get_modifiers(
        self,
        prize_pool: float | int,
        buy_in: float | int = 2.0,
        paid_places: int = 1,
    ) -> ProfileModifiers:
        """Return profile modifiers matching the prize pool and buy-in."""
        multiplier = prize_pool / max(0.001, buy_in)

        if multiplier <= 2.5:
            return ProfileModifiers(
                profile_name="LOOSE_CALLERS",
                bluff_factor=0.70,
                steal_boost_bb=0.0,
                value_shove_boost_bb=0.10,
                prefer_high_variance_borderline=True,
                use_icm=False,
            )
        elif multiplier < 5.0:
            return ProfileModifiers(
                profile_name="STANDARD_EXPLOIT",
                bluff_factor=1.0,
                steal_boost_bb=0.0,
                value_shove_boost_bb=0.0,
                prefer_high_variance_borderline=False,
                use_icm=False,
            )
        else:
            return ProfileModifiers(
                profile_name="HIGH_STEAL",
                bluff_factor=1.10,
                steal_boost_bb=0.15,
                value_shove_boost_bb=0.0,
                prefer_high_variance_borderline=False,
                use_icm=(paid_places > 1 or multiplier >= 5.0),
            )
