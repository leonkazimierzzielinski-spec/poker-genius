"""Independent Chip Model (ICM) and Bubble Factor calculations for 3-max tournaments."""

from __future__ import annotations


def calculate_icm_equities(stacks: list[int], payouts: list[float]) -> list[float]:
    """Calculate tournament equity for each player using the Malmuth-Harville model.

    Supports up to 3 players. Handles zero stacks (eliminated players) gracefully.
    """
    n = len(stacks)
    if n == 0:
        return []
    if n == 1:
        w1 = payouts[0] if payouts else 0.0
        return [float(w1)]

    tot = sum(max(0, s) for s in stacks)
    if tot <= 0:
        return [0.0] * n

    # Pad or truncate payouts to match number of players
    w = list(payouts) + [0.0] * max(0, n - len(payouts))

    if n == 2:
        s0 = max(0, stacks[0])
        s1 = max(0, stacks[1])
        p1_0 = s0 / tot
        p1_1 = s1 / tot
        eq0 = p1_0 * w[0] + (1.0 - p1_0) * w[1]
        eq1 = p1_1 * w[0] + (1.0 - p1_1) * w[1]
        return [round(eq0, 6), round(eq1, 6)]

    # 3-max Malmuth-Harville
    s = [max(0, stk) for stk in stacks[:3]]
    active_indices = [i for i, stk in enumerate(s) if stk > 0]

    if len(active_indices) <= 1:
        res = [0.0] * n
        if active_indices:
            res[active_indices[0]] = float(w[0])
        return res

    if len(active_indices) == 2:
        i0, i1 = active_indices
        sub_eq = calculate_icm_equities([s[i0], s[i1]], w[:2])
        res = [0.0] * n
        res[i0] = sub_eq[0]
        res[i1] = sub_eq[1]
        return res

    equities = [0.0, 0.0, 0.0]
    for i in range(3):
        p1_i = s[i] / tot
        p2_i = 0.0
        for j in range(3):
            if j == i:
                continue
            rem = tot - s[j]
            if rem > 0:
                p2_i += (s[j] / tot) * (s[i] / rem)
        p3_i = max(0.0, 1.0 - p1_i - p2_i)
        equities[i] = p1_i * w[0] + p2_i * w[1] + p3_i * w[2]

    # Return full array if n > 3 padded with 0.0
    if n > 3:
        equities.extend([0.0] * (n - 3))
    return [round(e, 6) for e in equities]


def compute_bubble_factor(
    hero_stack: int,
    opp_stack: int,
    third_stack: int,
    payouts: list[float],
) -> float:
    """Compute the Bubble Factor for Hero in an all-in confrontation against Opponent.

    BF = Delta_EQ_loss / Delta_EQ_win.
    In winner-take-all (e.g. [1.0, 0, 0]), BF == 1.0.
    When 2nd place pays (e.g. 5x+ prize pool with [0.75, 0.25, 0]), BF > 1.0.
    """
    if hero_stack <= 0 or opp_stack <= 0:
        return 1.0

    cur_eq = calculate_icm_equities([hero_stack, opp_stack, third_stack], payouts)[0]

    pot_risk = min(hero_stack, opp_stack)

    # Win branch: Hero wins pot_risk from Opponent
    win_hero = hero_stack + pot_risk
    win_opp = opp_stack - pot_risk
    win_eq = calculate_icm_equities([win_hero, win_opp, third_stack], payouts)[0]
    delta_win = max(1e-9, win_eq - cur_eq)

    # Lose branch: Hero loses pot_risk to Opponent
    lose_hero = hero_stack - pot_risk
    lose_opp = opp_stack + pot_risk
    lose_eq = calculate_icm_equities([lose_hero, lose_opp, third_stack], payouts)[0]
    delta_lose = max(0.0, cur_eq - lose_eq)

    if delta_win <= 0:
        return 1.0

    return round(delta_lose / delta_win, 4)


def is_icm_active(num_alive: int, prize_pool: float | int, buy_in: float | int) -> bool:
    """Check if ICM model is active for the current tournament situation (50x+)."""
    if num_alive != 3:
        return False
    bi = float(buy_in) if buy_in and buy_in > 0 else 2.0
    return float(prize_pool) >= 50.0 * bi


def get_payout_splits(prize_pool: float | int, buy_in: float | int) -> list[float]:
    """Return payout shares [1st, 2nd, 3rd] based on prize multiplier."""
    if is_icm_active(3, prize_pool, buy_in):
        return [0.80, 0.10, 0.10]
    return [1.0, 0.0, 0.0]
