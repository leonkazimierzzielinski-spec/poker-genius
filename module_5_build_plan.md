# Plan Budowy — Moduł 5: Warstwa Eksploatacyjna i Upraszczania (`strategy/`)

**Rola tego dokumentu:** Instrukcja krok po kroku dla osobnego agenta realizującego **Część 5** projektu `poker_assistant` równolegle z innymi agentami.

---

## 0. Zasady Pracy Równoległej (Przeczytaj przed startem!)

1. **Przeczytaj `CONSTITUTION.md`** w głównym katalogu projektu.
2. **Zasada braku konfliktów:** Ponieważ inni agenci równolegle budują pozostałe moduły, **TWORZYSZ I EDYTUJESZ WYŁĄCZNIE PONIŻSZE PLIKI**:
   * `strategy/__init__.py`
   * `strategy/multiplier_adapter.py`
   * `strategy/exploit.py`
   * `strategy/simplifier.py`
   * `strategy/decision_maker.py`
   * `tests/test_strategy.py`
3. **Czego NIE dotykasz:** NIE twórz ani nie edytuj `core/`, `config.json`, `requirements.txt`, `vision/`, `state/`, `engine/`, `ui/` ani `tools/`.
4. **Bezpieczny import `core`:** Importuj `TableState`, `Decision` z `core.contracts` oraz `EV_LOSS_THRESHOLD_BB` z `core.constants`. W `tests/test_strategy.py` dla testów samej logiki `MultiplierAdapter`, `ExploitEngine` i `StrategySimplifier` używaj czystych typów lub prostych obiektów testowych (`SimpleNamespace`), a testy wymagające `core.contracts` oznacz `pytest.importorskip("core.contracts")`.

---

## Krok 1: `strategy/multiplier_adapter.py` (`MultiplierAdapter`)

Zaimplementuj dopasowanie profilu agresji do wysokości wylosowanej puli nagrody:

1. **Klasa `ProfileModifiers` (`@dataclass`):**
   * `profile_name: str` (`"LOOSE_CALLERS"`, `"STANDARD_EXPLOIT"`, `"HIGH_STEAL"`)
   * `bluff_factor: float` (mnożnik opłacalności blefów postflop, np. `0.70` w `LOOSE_CALLERS`, `1.0` w `STANDARD_EXPLOIT`, `1.10` w `HIGH_STEAL`)
   * `steal_boost_bb: float` (dodatkowe EV dla agresywnych kradzieży blindów, np. `0.0` lub `0.15`)
   * `value_shove_boost_bb: float` (premia EV dla All-inów for value, np. `0.10` w `LOOSE_CALLERS`)
   * `prefer_high_variance_borderline: bool` (`True` w `LOOSE_CALLERS`, `False` w pozostałych)
   * `use_icm: bool` (`True` dla mnożników `>= 5x`, gdy wypłacane jest więcej niż 1 miejsce)
2. **Klasa `MultiplierAdapter`:**
   * `get_modifiers(self, prize_pool: int, buy_in: int = 2, paid_places: int = 1) -> ProfileModifiers`:
     * Oblicza `multiplier = prize_pool / max(1, buy_in)`.
     * Jeśli `multiplier <= 2.5` (np. pula `4` przy wpisowym `2`): zwraca `LOOSE_CALLERS` (`bluff_factor=0.70`, `value_shove_boost_bb=0.10`, `prefer_high_variance_borderline=True`, `use_icm=False`).
     * Jeśli `2.5 < multiplier < 5.0` (np. pule `6`, `8`): zwraca `STANDARD_EXPLOIT` (`bluff_factor=1.0`, `steal_boost_bb=0.0`, `value_shove_boost_bb=0.0`, `prefer_high_variance_borderline=False`, `use_icm=False`).
     * Jeśli `multiplier >= 5.0` (np. pule `10`, `12`, `20+`): zwraca `HIGH_STEAL` (`bluff_factor=1.10`, `steal_boost_bb=0.15`, `prefer_high_variance_borderline=False`, `use_icm=(paid_places > 1 or multiplier >= 5.0)`).

---

## Krok 2: `strategy/exploit.py` (MDA, Timing Tells, Sizing Tells)

Zaimplementuj modyfikatory eksploatacyjne nakładane na bazowe wartości EV kandydatów akcji (`dict[str, float]`, np. `{"FOLD": 0.0, "CHECK": 0.05, "BET_30": 0.12, "ALL_IN": 0.08}`):

* **Klasa `ExploitEngine`:**
  * `apply_exploits(self, candidate_evs: dict[str, float], state: TableState, modifiers: ProfileModifiers, spot: str = "POSTFLOP") -> tuple[dict[str, float], list[str]]`:
    * Kopiuje `candidate_evs`, inicjuje `reasons: list[str] = []`.
    * **1. Modyfikator profilu (`MultiplierAdapter`):**
      * Jeśli w `candidate_evs` jest `"ALL_IN"` i `modifiers.value_shove_boost_bb > 0`: zwiększ `evs["ALL_IN"] += modifiers.value_shove_boost_bb`.
      * Jeśli `spot in ("BTN_OPEN", "SB_OPEN", "BB_ISO_VS_LIMP")` i `modifiers.steal_boost_bb > 0`: zwiększ `evs["ALL_IN"]` (lub `"MIN_RAISE"`) o `modifiers.steal_boost_bb` i dopisz `"High Steal vs scared money"`.
      * Jeśli `spot == "BB_ISO_VS_LIMP"` i jest `"ALL_IN"`: dodaj `+0.10` BB do `"ALL_IN"` i dopisz `"MDA Iso-Shove vs limp"`.
    * **2. Timing Tells (szybki check rywala `< 500 ms`):**
      * Sprawdź aktywnych rywali (`seat_id in (1, 2)`). Jeśli któryś ma `last_reaction_ms is not None and last_reaction_ms < 500`:
        * Jeśli `"BET_30"` jest w `evs`: przeskaluj premię blefu przez `modifiers.bluff_factor` — np. `bonus = 0.12 * modifiers.bluff_factor`, dodaj `evs["BET_30"] += bonus` i dopisz `"Timing Tell: fast check <500ms"`.
    * **3. Sizing Tells (dziwny mały zakład `1 BB` na flopie/turnie):**
      * Jeśli `state.street in ("FLOP", "TURN")` i którykolwiek aktywny rywal ma `current_bet == state.big_blind`:
        * Jeśli `"ALL_IN"` jest w `evs`: dodaj `+0.15` BB do `"ALL_IN"` i dopisz `"Sizing Tell: 1BB weak bet -> raise/shove"`.
    * Zwraca `(evs, reasons)`.

---

## Krok 3: `strategy/simplifier.py` (Ochrona przed profilem RTA)

Zaimplementuj deterministyczne upraszczanie strategii zgodnie z sekcją 6.5 `CONSTITUTION.md`:

* **Klasa `StrategySimplifier`:**
  * `__init__(self, ev_loss_threshold_bb: float = 0.08)`
  * `select_pure_action(self, evs: dict[str, float], modifiers: ProfileModifiers, available_actions: list[str] | None = None) -> tuple[str, float, str | None]`:
    1. **Redukcja sizingów:** Odfiltruj akcje spoza dozwolonego zbioru (`FOLD`, `CHECK`, `CALL`, `MIN_RAISE`, `BET_30`, `ALL_IN`). Jeśli podano `available_actions`, zachowaj tylko akcje realnie dostępne na stole (mapując np. `BET_30` / `ALL_IN` na `BET` lub `RAISE`).
    2. **Strategia czysta (zero miksowania RNG):** Wybierz akcję o najwyższym `ev_bb` (deterministycznie; w przypadku remisu preferuj prostszą/wyżej wariancyjną opcję, gdy `modifiers.prefer_high_variance_borderline` jest `True`).
    3. **Próg minimalnego zysku (`+0.08 BB`):**
       * Jeśli wybrana akcja to nie `FOLD` ani `CHECK`, a jej `best_ev < self.ev_loss_threshold_bb`:
         * Wyjątek dla `LOOSE_CALLERS`: jeśli `modifiers.prefer_high_variance_borderline` i `best_ev >= 0.0` oraz akcja to `ALL_IN` lub `CALL`, zachowaj ją (`"Borderline 0EV high-variance call/shove"`).
         * W każdym innym przypadku odrzuć marginalne zagranie i cofnij się do `"CHECK"` (jeśli dostępne) lub `"FOLD"` (`ev = 0.0`, powód `"Filtered marginal play < +0.08 BB"`).
    * Zwraca `(chosen_action, chosen_ev, filter_note)`.

---

## Krok 4: `strategy/decision_maker.py` (Fasada dla Pętli Głównej)

Połącz powyższe 3 klasy w jeden punkt wejścia dla Modułu 6:
* **Klasa `DecisionMaker`:**
  * `__init__(self, buy_in: int = 2, ev_loss_threshold_bb: float = 0.08)`
  * `decide(self, state: TableState, candidate_evs: dict[str, float], spot: str = "POSTFLOP", confidence: float = 0.95, paid_places: int = 1) -> Decision`:
    * Jeśli `not state.is_valid` lub `not state.is_hero_turn` lub `state.street == "WAITING_FOR_TURN"`:
      * Zwraca `Decision(table_id=state.table_id, action="WAIT", ev_bb=None, confidence=1.0, profile_used="STANDARD_EXPLOIT", reason="Waiting for Hero turn")`.
    * Pobiera `modifiers` z `MultiplierAdapter`.
    * Przepuszcza `candidate_evs` przez `ExploitEngine.apply_exploits(...)`.
    * Wybiera ostateczną czystą akcję przez `StrategySimplifier.select_pure_action(...)`.
    * Łączy powody w krótki czytelny string `reason` (maks. ~80 znaków) i zwraca obiekt `Decision`.

---

## Krok 5: Testy Jednostkowe `tests/test_strategy.py`

Napisz testy w `pytest`:
1. `test_multiplier_adapter_profiles`: weryfikuje profile dla pul `4` (`LOOSE_CALLERS`), `6` (`STANDARD_EXPLOIT`), `8` (`STANDARD_EXPLOIT`), `10` i `20` (`HIGH_STEAL`).
2. `test_exploit_timing_tell_fast_check`: symuluje `last_reaction_ms = 250` i sprawdza, że EV dla `BET_30` rośnie oraz pojawia się adnotacja `"Timing Tell"`.
3. `test_exploit_sizing_tell_one_bb`: symuluje rywala z `current_bet == state.big_blind` na flopie i sprawdza wzrost EV dla `ALL_IN`.
4. `test_simplifier_ev_loss_threshold`: dla `{"FOLD": 0.0, "CALL": 0.04}` w trybie `STANDARD_EXPLOIT` musi wybrać `"FOLD"` (bo `0.04 < 0.08`).
5. `test_simplifier_loose_callers_borderline`: dla `{"FOLD": 0.0, "ALL_IN": 0.01}` w trybie `LOOSE_CALLERS` akceptuje `"ALL_IN"` (wyższa wariancja w spocie `~0 EV`).

### Kryterium odbioru
Uruchom w terminalu:
```bash
pytest -v tests/test_strategy.py
```
Polecenie musi zakończyć się kodem wyjścia `0`.
