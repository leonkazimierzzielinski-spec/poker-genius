# Plan V17 — Aktywacja Bazy GTOpen w `main.py`, Stanowy `RangeEngine`, Relatywny `StrategySimplifier` i Naprawa `DecisionMaker` (`poker_assistant`)

Dokument jest kompletną, jednoznaczną specyfikacją wdrożeniową V17 dla agentów w Antigravity. Cel: usunąć 4 krytyczne, ciche błędy w warstwie strategii i podpięcia silnika postflop, tak aby przeliczona baza 188 flopów GTOpen realnie uruchamiała się w grze, silnik zakresów pamiętał historię akcji rywala od preflopu do rivera (z zachowaniem wag!), a filtr EV nie odrzucał zyskownych zagrań.

> **Zasada „Zero działania na ślepo” (`QUESTIONS_V17.md`):** Jeśli podczas wdrożenia trafisz na niejasność, konflikt z istniejącym kodem lub decyzję, której ten plan nie rozstrzyga — **NIE zgaduj**. Zrealizuj wszystkie pewne elementy, a otwarte pytania (kontekst + konkretne opcje A/B) zapisz w pliku **`QUESTIONS_V17.md`** w katalogu głównym repozytorium i wypchnij go razem z commitem. Jeśli wszystko było jasne, nie twórz tego pliku.

---

## 0. Tabela Podjętych Decyzji Architektonicznych (Obowiązujące)

| Obszar | Podjęta decyzja (zamknięta) | Uzasadnienie i ochrona przed regresją |
| :--- | :--- | :--- |
| **Podpięcie `flop_db` w `main.py`** | Dodać deterministyczną funkcję `determine_postflop_spot(state, hand_summary)` zwracającą dokładnie jeden z 4 kluczy bazy GTOpen (`BTN_vs_BB_SRP`, `SB_vs_BB_LIMPED`, `HU_SB_vs_BB_SRP`, `HU_SB_vs_BB_LIMPED`). Odpytywać `flop_db.lookup_nearest_flop(...)` **wyłącznie na Flopie i tylko gdy `not facing_bet`**. | W V16.1 `main.py` przekazywało `spot = "FLOP"`, przez co `gtopen_db.get("FLOP")` zawsze zwracało `None`. Ograniczenie do `not facing_bet` chroni przed użyciem EV z root node OOP, gdy rywal już zabetował. |
| **Stanowy `range_engine` (pamięć rozdania + wagi)** | Dodać w `engine/range_engine.py` funkcję `build_villain_range_from_history(hand_summary, state, villain_seat, effective_bb)` budującą zakres rywala kumulatywnie: akcja Preflop → zawężenie Flop → zawężenie Turn → zawężenie River. Dla `num_opps == 1` liczyć equity przez `compute_range_vs_hand_equity` na **Flopie, Turnie i Riverze** (a nie tylko na Riverze). | Usuwa dwa ukryte błędy `main.py`: (1) sztywne `opp_pos = "BTN"` i brak pamięci poprzednich ulic oraz (2) utratę wszystkich wag zakresu przy konwersji `list(v_range.keys())` na Flopie i Turnie. |
| **Relatywny próg EV w `StrategySimplifier`** | Zmienić warunek w `StrategySimplifier.select_pure_action` z bezwzględnego `best_ev < threshold` na **relatywny zysk nad bezpieczną bazą**: `ev_gain = best_ev - baseline_ev < eff_thresh` (gdzie `baseline_ev` to EV dla `CHECK` lub `FOLD`). Dodać opcjonalny parametr `threshold_override: float \| None = None`. | Naprawia błąd na realnych EV z GTOpen (np. `CHECK = -0.42 BB`, `BET_30 = +0.03 BB` → realny zysk `+0.45 BB`, który wcześniej był odrzucany!). Zachowuje 100% kompatybilności z istniejącymi testami `StrategySimplifier(ev_loss_threshold_bb=0.08)`. |
| **Progi `DecisionMaker` (Preflop vs Postflop)** | W `DecisionMaker.__init__`: ustawić domyślny `ev_loss_threshold_bb: float = 0.03` (postflop) oraz `preflop_ev_loss_threshold_bb: float = 0.0` (preflop). W `decide()` przekazywać odpowiedni `threshold_override` do `simplifier.select_pure_action(...)`. | W 3-max Hyper-Turbo (winrate ~0.05–0.08 BB/rozdanie) próg `0.08 BB` odrzuca zbyt wiele zyskownych spotów. `0.00 BB` preflop (czyste tabele Nasha) + `0.03 BB` postflop filtruje szum bez oddawania EV. |
| **Naprawa `p.bet` → `p.current_bet` w `DecisionMaker`** | W `strategy/decision_maker.py` odczytywać zakłady przez `getattr(p, "current_bet", getattr(p, "bet", 0)) or 0`. | W `core/contracts.py:PlayerState` pole nazywa się `current_bet`, a nie `bet`. Fallback na `bet` zachowuje zgodność z prostymi mockami testowymi. |
| **Kompatybilność sygnatur** | Wszystkie nowe parametry (`hand_summary=None` w `evaluate_candidates`, `threshold_override=None` w `select_pure_action`, `preflop_ev_loss_threshold_bb=0.0` w `DecisionMaker`) muszą mieć wartości domyślne. | Gwarantuje, że wszystkie 137 dotychczasowych testów `pytest` przejdzie bez łamania istniejących wywołań. |

---

## 1. Krok 1: Relatywny `StrategySimplifier` i Naprawa `DecisionMaker` (`strategy/simplifier.py`, `strategy/decision_maker.py`)

### 1.1. `strategy/simplifier.py`
Zaktualizuj metodę `StrategySimplifier.select_pure_action`:

1. Rozszerz sygnaturę o opcjonalny parametr:
   ```python
   def select_pure_action(
       self,
       evs: dict[str, float],
       modifiers: ProfileModifiers,
       available_actions: list[str] | None = None,
       threshold_override: float | None = None,
   ) -> tuple[str, float, str | None]:
   ```
2. W sekcji `# 3. Minimum profit threshold` (obecnie linie ~136–161):
   - Wyznacz efektywny próg:
     ```python
     eff_thresh = self.ev_loss_threshold_bb if threshold_override is None else max(0.0, float(threshold_override))
     ```
   - Wyznacz dostępność `CHECK` i wartość bazową `baseline_ev`:
     ```python
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
     ```
   - Zastąp warunek `if best_action not in ("FOLD", "CHECK") and best_ev < self.ev_loss_threshold_bb:` warunkiem relatywnym:
     ```python
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
     ```
   - **Weryfikacja kompatybilności wstecznej:**
     - Dla `StrategySimplifier(ev_loss_threshold_bb=0.08)` i `{"FOLD": 0.0, "CALL": 0.04}`: `baseline_ev = 0.0`, `ev_gain = 0.04 < 0.08` → zwraca `("FOLD", 0.0, "Filtered marginal play < +0.08 BB")`. Istniejący test `test_simplifier_ev_loss_threshold` przechodzi bez zmian!
     - Dla `{"CHECK": -0.42, "BET_30": 0.03}` przy `eff_thresh = 0.03`: `baseline_ev = -0.42`, `ev_gain = 0.45 >= 0.03` → zwraca `("BET_30", 0.03, None)`.

### 1.2. `strategy/decision_maker.py`
1. W `DecisionMaker.__init__`:
   ```python
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
   ```
   *(Uwaga: jeśli któryś istniejący test w `tests/test_strategy.py` lub `tests/test_ui_and_main.py` oczekuje na `DecisionMaker()` progu `0.08` — sprawdź `pytest` przed modyfikacją testu; jeśli test jawnie podaje `DecisionMaker(ev_loss_threshold_bb=0.08)`, nadal zadziała! Jeśli test sprawdza domyślne zachowanie preflop/postflop, zweryfikuj spójność z nową decyzją.)*
2. Napraw odczyt zakładów (obecnie linie ~85–91):
   ```python
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
   ```
3. Wyznacz `eff_thresh` dla `simplifier.select_pure_action(...)`:
   ```python
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
   eff_thresh = self.preflop_ev_loss_threshold_bb if is_preflop_decision else self.ev_loss_threshold_bb

   action, ev_bb, filter_note = self.simplifier.select_pure_action(
       evs=exploited_evs,
       modifiers=modifiers,
       available_actions=available_actions,
       threshold_override=eff_thresh,
   )
   ```

---

## 2. Krok 2: Stanowe Zawężanie Zakresu Rywala z Historii Rozdania (`engine/range_engine.py`)

W `engine/range_engine.py` dodaj dwie czyste funkcje pomocnicze (nie zmieniając istniejących sygnatur `get_preflop_villain_range`, `narrow_range_by_postflop_action`, `compute_range_vs_hand_equity`, `classify_combo`):

### 2.1. `infer_villain_position(state, hand_summary, villain_seat) -> str`
- Ustala pozycję rywala (`"BTN"`, `"SB"`, `"BB"`):
  - Sprawdza `is_dealer` w `hand_summary["players"]` (jeśli dostępny) lub w `state.players`.
  - Jeśli `villain_seat == dealer_seat`: zwraca `"BTN"`.
  - W przeciwnym razie sprawdza liczbę aktywnych na starcie graczy (nie-`OUT`):
    - Jeśli 2 graczy (Heads-Up) i `villain_seat != dealer_seat`: zwraca `"BB"`.
    - Jeśli 3 graczy: gracz zaraz po dealerze `(dealer_seat + 1) % 3` to `"SB"`, a trzeci to `"BB"`.
  - Bezpieczny fallback przy braku dealera: `"BTN"`.

### 2.2. `build_villain_range_from_history(hand_summary: dict[str, Any] | None, state: Any, villain_seat: int, effective_bb: float) -> dict[tuple[str, str], float]`
1. Pobierz `hero_cards = list(getattr(state, "hero_cards", []) or [])`, `board_cards = list(getattr(state, "board_cards", []) or [])`, `bb_val = max(1, int(getattr(state, "big_blind", 20) or 20))`, `pot_val = max(bb_val, int(getattr(state, "pot", 40) or 40))`.
2. Wyznacz `v_pos = infer_villain_position(state, hand_summary, villain_seat)`.
3. Zbierz z `hand_summary["action_log"]` (jeśli `hand_summary` nie jest `None`) chronologiczną listę akcji dla `seat_id == villain_seat`, podzieloną na:
   - `preflop_acts = [a for a in log if a.get("seat_id") == villain_seat and a.get("street") == "PREFLOP" and a.get("action") not in ("BLIND", "FOLD")]`
   - `postflop_acts = [a for a in log if a.get("seat_id") == villain_seat and a.get("street") in ("FLOP", "TURN", "RIVER") and a.get("action") not in ("BLIND", "FOLD")]`
4. **Wyznacz akcję preflop (`preflop_act`):**
   - Jeśli wśród `preflop_acts` jest `"ALL-IN"` lub co najmniej dwa `"RAISE"` → `"3BET_OR_SHOVE"`.
   - Jeśli wśród `preflop_acts` jest `"RAISE"` (lub `"BET"` z `amount > bb_val`) → `"OPEN_RAISE"`.
   - Jeśli wśród `preflop_acts` jest `"CALL"`:
     - sprawdź, czy którykolwiek inny gracz miał `"RAISE"` preflop w `action_log` (lub `pot_val >= 3.5 * bb_val`) → jeśli tak, to `"CALL_OPEN"`, w przeciwnym razie `"LIMP"`.
   - Jeśli brak `preflop_acts`:
     - jeśli `pot_val >= 3.5 * bb_val` → `"OPEN_RAISE"` (gdy `v_pos in ("BTN", "SB")`) lub `"CALL_OPEN"` (gdy `v_pos == "BB"`),
     - w przeciwnym razie → `"LIMP"`.
5. Zbuduj bazowy zakres startowy:
   ```python
   v_range = get_preflop_villain_range(
       position=v_pos,
       preflop_action=preflop_act,
       effective_bb=effective_bb,
       hero_cards=hero_cards,
       board_cards=board_cards,
   )
   ```
6. **Kumulatywne zawężanie po każdej ulicy z `postflop_acts` (Flop → Turn → River):**
   - Utrzymuj szacunkową pulę `running_pot = max(float(bb_val * 2), float(pot_val) * 0.5)`.
   - Dla każdego wpisu `entry` w `postflop_acts`:
     - `act_street = entry.get("street", "FLOP")`
     - Wyznacz karty boardu dla tej ulicy:
       - `"FLOP"` → `board_cards[:3]` (wymaga `len(board_cards) >= 3`),
       - `"TURN"` → `board_cards[:4]` (wymaga `len(board_cards) >= 4`),
       - `"RIVER"` → `board_cards[:5]` (wymaga `len(board_cards) >= 5`).
       - Jeśli brakuje kart dla tej ulicy, pomiń wpis.
     - Zmapuj nazwę akcji:
       - `"ALL-IN"` lub `"RAISE"` → `act_type = "RAISE"`,
       - `"BET"` → `act_type = "BET"`,
       - `"CHECK"` lub `"CALL"` → `act_type = "CHECK"`.
     - Wylicz `amt = float(entry.get("amount", 0) or 0)` i `b_to_p = (amt / max(float(bb_val), running_pot)) if act_type in ("BET", "RAISE") else 0.0`.
     - Zawęź zakres:
       ```python
       narrowed = narrow_range_by_postflop_action(
           villain_range=v_range,
           board_cards=street_board,
           action_type=act_type,
           bet_to_pot=b_to_p,
           street=act_street,
       )
       if narrowed and sum(narrowed.values()) > 1e-6:
           v_range = narrowed
       if amt > 0:
           running_pot += amt
       ```
7. **Uwzględnienie bieżącego betu na aktualnej ulicy (jeśli jeszcze nie trafił do `postflop_acts`):**
   - Sprawdź `curr_p = state.players.get(villain_seat)` oraz `curr_bet = getattr(curr_p, "current_bet", 0) or 0`.
   - Jeśli `curr_bet > 0`: sprawdź, czy ostatni wpis w `postflop_acts` ma już tę samą ulicę `state.street` i zbliżoną kwotę (`abs(last_amt - curr_bet) <= 1`). Jeśli NIE — wykonaj jedno zawężenie `narrow_range_by_postflop_action(v_range, board_cards, "BET", curr_bet / max(float(bb_val), float(pot_val - curr_bet)), street=state.street)` (z tą samą ochroną `sum(narrowed.values()) > 1e-6`).
   - Jeśli `curr_bet == 0` i brak jakiejkolwiek akcji rywala w `postflop_acts` na bieżącej ulicy `state.street` i `v_pos != "BTN"` (tj. rywal OOP najprawdopodobniej zaczekał przed naszą decyzją IP): wykonaj lekkie zawężenie `narrow_range_by_postflop_action(v_range, board_cards, "CHECK", 0.0, street=state.street)`.
8. Zwróć `v_range`.

---

## 3. Krok 3: Podpięcie `flop_db` i Stanowego `range_engine` w `main.py`

### 3.1. Nowa funkcja `determine_postflop_spot(state: Any, hand_summary: dict[str, Any] | None = None) -> str`
Dodaj w `main.py` (obok `determine_preflop_spot`):

```python
def determine_postflop_spot(
    state: Any,
    hand_summary: dict[str, Any] | None = None,
) -> str:
    """Map current postflop state + hand history to one of the 4 GTOpen database spot keys."""
    players = getattr(state, "players", {}) or {}
    bb_val = max(1, int(getattr(state, "big_blind", 20) or 20))
    pot_val = int(getattr(state, "pot", 0) or 0)

    # 1. Detect Heads-Up vs 3-max
    eliminated_count = 0
    if hand_summary and isinstance(hand_summary.get("players"), dict):
        eliminated_count = sum(
            1
            for sid in (0, 1, 2)
            if hand_summary["players"].get(sid, {}).get("eliminated", False)
        )
    else:
        eliminated_count = sum(
            1
            for sid in (0, 1, 2)
            if sid in players
            and getattr(players[sid], "stack", None) is None
            and not getattr(players[sid], "is_active", True)
        )
    is_hu = eliminated_count >= 1

    # 2. Detect SRP (Single Raised Pot) vs LIMPED
    had_preflop_raise = False
    if hand_summary and isinstance(hand_summary.get("action_log"), list):
        for entry in hand_summary["action_log"]:
            if entry.get("street") == "PREFLOP" and entry.get("action") in ("RAISE", "ALL-IN"):
                had_preflop_raise = True
                break
        if not had_preflop_raise:
            # Fallback if joined mid-hand without preflop log
            if hand_summary.get("mid_hand_join") and pot_val >= int(round(3.5 * bb_val)):
                had_preflop_raise = True
    else:
        had_preflop_raise = pot_val >= int(round(3.5 * bb_val))

    if is_hu:
        return "HU_SB_vs_BB_SRP" if had_preflop_raise else "HU_SB_vs_BB_LIMPED"
    return "BTN_vs_BB_SRP" if had_preflop_raise else "SB_vs_BB_LIMPED"
```

### 3.2. Aktualizacja `evaluate_candidates` w `main.py`
1. Zaktualizuj sygnaturę z zachowaniem pełnej kompatybilności wstecznej:
   ```python
   def evaluate_candidates(
       state: Any,
       preflop_engine: Any,
       flop_db: Any,
       mc_calc: Any,
       hand_summary: dict[str, Any] | None = None,
   ) -> tuple[dict[str, float], str]:
   ```
2. W gałęzi `# POSTFLOP streets (FLOP, TURN, RIVER)` (obecnie linie ~400–655):
   - Wyznacz `postflop_spot = determine_postflop_spot(state, hand_summary) if street == "FLOP" else street` i ustaw `spot = postflop_spot`.
   - **Krok 1 (`flop_db`):** Odpytuj `flop_db.lookup_nearest_flop(board_cards, postflop_spot, hero_cards)` **WYŁĄCZNIE gdy `not facing_bet`** (bo baza GTOpen 47 flopów zawiera strategie dla węzła otwierającego bez betu rywala; przy `facing_bet == True` zawsze przechodzimy do stanowego `range_engine` w Kroku 2!).
     ```python
     if (
         street == "FLOP"
         and not facing_bet
         and flop_db is not None
         and len(board_cards) == 3
         and len(hero_cards) == 2
     ):
         if hasattr(flop_db, "lookup_nearest_flop"):
             try:
                 lookup_res = flop_db.lookup_nearest_flop(board_cards, postflop_spot, hero_cards)
                 if (
                     lookup_res is not None
                     and isinstance(lookup_res, dict)
                     and any(k in lookup_res for k in ("CHECK", "BET_30", "BET_MED", "ALL_IN"))
                 ):
                     candidate_evs = {k: float(v) for k, v in lookup_res.items()}
                     if "FOLD" not in candidate_evs:
                         candidate_evs["FOLD"] = 0.0
             except Exception:
                 candidate_evs = None
     ```
     *(Zostaw istniejący fallback `flop_db.lookup(...)` pod spodem wyłącznie dla `not facing_bet` i `candidate_evs is None`.)*
   - **Krok 2 (Stanowy `range_engine` z zachowaniem wag!):**
     - Wyznacz `villain_seat` (jeśli `facing_bet`, wybierz aktywnego rywala z najwyższym `current_bet`; inaczej pierwszego aktywnego rywala z `seat_id in (1, 2)`).
     - Wywołaj `v_range = build_villain_range_from_history(hand_summary=hand_summary, state=state, villain_seat=villain_seat, effective_bb=stack_bb)` (importuj `build_villain_range_from_history` z `engine.range_engine` obok pozostałych importów w `main.py`).
     - **KRYTYCZNE — zachowanie wag zakresu na Flopie i Turnie:**
       Dotychczas `main.py:494` robiło `v_combos = list(v_range.keys())`, co **wyrzucało wszystkie wagi** wyliczone przez `narrow_range_by_postflop_action`!
       Zamień blok estymacji `equity` (obecnie linie ~485–509) na:
       ```python
       if num_opps == 1 and v_range and compute_range_vs_hand_equity is not None:
           equity = compute_range_vs_hand_equity(
               hero_cards=hero_cards,
               board_cards=board_cards,
               villain_range=v_range,
               time_budget_ms=400.0,
           )
       else:
           # Multiway (2 active opponents) or fallback when range_engine unavailable
           v_combos = list(v_range.keys()) if v_range else None
           try:
               equity = mc_calc.estimate_equity(
                   hero_cards,
                   board_cards,
                   villain_range=v_combos,
                   time_budget_ms=400.0,
                   num_opponents=num_opps,
               )
           except TypeError:
               equity = mc_calc.estimate_equity(
                   hero_cards,
                   board_cards,
                   time_budget_ms=400.0,
                   num_opponents=num_opps,
               )
       ```
     - Usuń martwą gałąź `else:` (dawne linie 633–654), która liczyła `CALL` na gołym losowym `mc_calc` po `flop_db`, ponieważ przy `facing_bet == True` zawsze wykonuje się teraz gałąź stanowego `range_engine`.

### 3.3. Przekazanie `hand_summary` w `processing_loop` (`main.py`)
W `processing_loop` (okolice linii ~1428), w miejscu wywołania `evaluate_candidates`:
```python
active_tracker = trackers.get(resolved_tid)
cur_hand_summary = (
    active_tracker.get_hand_summary()
    if active_tracker is not None and hasattr(active_tracker, "get_hand_summary")
    else None
)
candidate_evs, spot = evaluate_candidates(
    eval_state, preflop_engine, flop_db, mc_calc, hand_summary=cur_hand_summary
)
```

---

## 4. Krok 4: Obowiązkowe Testy Jednostkowe i Weryfikacja Regresyjna

### 4.1. Nowe testy jednostkowe (obowiązkowe)
1. **`tests/test_strategy.py`:**
   - `test_simplifier_relative_ev_gain_allows_profitable_cbet_over_negative_check`: dla `{"CHECK": -0.42, "BET_30": 0.03}` przy `ev_loss_threshold_bb=0.03` musi wybrać **`BET_30`** (ponieważ `ev_gain = +0.45 BB >= 0.03`), a dla `{"CHECK": -0.42, "BET_30": -0.40}` musi wybrać **`CHECK`** (`ev_gain = +0.02 < 0.03`).
   - `test_decision_maker_reads_current_bet_and_uses_zero_preflop_threshold`: weryfikuje, że `DecisionMaker` poprawnie odczytuje `PlayerState.current_bet` (np. `opp.current_bet = 40`, `hero.current_bet = 20` → `facing_bet == True`, pozwala na `FOLD` mimo braku pola `.bet`), oraz że na preflopie akcja o `+0.02 BB` przechodzi (`threshold == 0.0`), podczas gdy na postflopie `+0.02 BB` względem `CHECK (0.0)` jest filtrowane (`threshold == 0.03`).
2. **`tests/test_engine.py`:**
   - `test_build_villain_range_from_history_narrows_across_streets`: symuluje `hand_summary` z `OPEN_RAISE` preflop, dużym `BET` na flopie i dużym `BET` na turnie — potwierdza, że (a) zakres rywala ma istotnie niższy udział `AIR` niż po samym preflopie, (b) equity słabej pary Hero przeciwko temu zakresowi przez `compute_range_vs_hand_equity` jest istotnie niższe niż przeciwko losowemu zakresowi / po linii `CHECK -> CHECK`.
3. **`tests/test_ui_and_main.py`:**
   - `test_determine_postflop_spot_all_four_variants`: sprawdza wszystkie 4 kombinacje (`BTN_vs_BB_SRP`, `SB_vs_BB_LIMPED`, `HU_SB_vs_BB_SRP`, `HU_SB_vs_BB_LIMPED`) na podstawie `hand_summary` (`eliminated` + `RAISE` preflop vs limp).
   - `test_evaluate_candidates_hits_gtopen_flop_db_when_not_facing_bet_and_uses_range_engine_when_facing_bet`: z prawdziwym `FlopDatabase` (z załadowanym `gtopen_47_flops.json` lub mockiem z kluczem `"BTN_vs_BB_SRP"`) weryfikuje, że:
     - przy `not facing_bet` na Flopie `evaluate_candidates` zwraca `spot == "BTN_vs_BB_SRP"` i pobiera EV z `flop_db`,
     - przy `facing_bet == True` na Flopie `evaluate_candidates` **nie** używa root-node z `flop_db`, tylko liczy `CALL`/`ALL_IN`/`FOLD` przez stanowy `range_engine`.

### 4.2. Weryfikacja końcowa
1. Uruchom pełny zestaw testów:
   ```bash
   pytest -v tests/
   ```
   **100% testów (dotychczasowe 137 + nowe = 142+ testów) musi przejść na zielono.**
2. Jeśli istnieją lokalnie nagrania w `nagrania testowe/`, uruchom szybki test regresyjny na 3 kluczowych klatkach postflop (`211257` f2604, f4757 oraz `2 gry na raz` f1383, f1627) przez pełną ścieżkę `main.py` i potwierdź w `PROGRESS_LOG.md`, że:
   - na f1383 (`not facing_bet`, Flop) `evaluate_candidates` zwraca realny klucz spotu z bazy GTOpen (`BTN_vs_BB_SRP` / `SB_vs_BB_LIMPED`),
   - na f1627 (`facing_bet`, Flop) i f2604 (Turn) działa stanowy `range_engine` bez błędów i poniżej budżetu czasowego.

---

## 5. Obowiązkowa Synchronizacja na GitHub (Po Zakończeniu Prac)

1. Jeśli pojawiły się jakiekolwiek niejasności lub konflikty z istniejącymi testami — zapisz je precyzyjnie w **`QUESTIONS_V17.md`** w katalogu głównym repozytorium (nie zgaduj!). Jeśli wszystko było jasne, nie twórz tego pliku.
2. Dopisz szczegółowy raport **V17** (wprowadzone zmiany, tabela weryfikacji klatek postflop, pełny wynik `pytest -v tests/`) na samej górze pliku **`PROGRESS_LOG.md`**.
3. Sprawdź `git status` (brak plików `.mp4` i śmieci tymczasowych).
4. Wykonaj:
   ```bash
   git add -A
   git commit -m "V17: Wire GTOpen flop_db spot mapping, stateful range_engine with weights, relative EV simplifier (0.03BB), fix DecisionMaker current_bet"
   git push origin main
   ```
5. W odpowiedzi końcowej napisz krótkie potwierdzenie (z informacją, czy powstał `QUESTIONS_V17.md`) i podaj link do repozytorium:
   `https://github.com/leonkazimierzzielinski-spec/poker-genius`
