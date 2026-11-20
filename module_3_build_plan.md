# Plan Budowy — Moduł 3: Maszyna Stanów, Walidacja i Logger (`state/`)

**Rola tego dokumentu:** Instrukcja krok po kroku dla osobnego agenta realizującego **Część 3** projektu `poker_assistant` równolegle z innymi agentami.

---

## 0. Zasady Pracy Równoległej (Przeczytaj przed startem!)

1. **Przeczytaj `CONSTITUTION.md`** w głównym katalogu projektu.
2. **Zasada braku konfliktów:** Ponieważ inni agenci równolegle budują pozostałe moduły, **TWORZYSZ I EDYTUJESZ WYŁĄCZNIE PONIŻSZE PLIKI**:
   * `state/__init__.py`
   * `state/validator.py`
   * `state/tracker.py`
   * `state/logger.py`
   * `tests/test_state.py`
3. **Czego NIE dotykasz:** NIE twórz ani nie edytuj `core/`, `config.json`, `requirements.txt`, `vision/`, `engine/`, `strategy/`, `ui/` ani `tools/`.
4. **Bezpieczny import `core`:** W plikach `state/` importuj `TableState`, `PlayerState`, `Decision` z `core.contracts` oraz `TOTAL_CHIPS` z `core.constants`. Jeśli w trakcie Twojej pracy `core/` jeszcze nie istnieje, w `tests/test_state.py` użyj `pytest.importorskip("core.contracts")` lub prostych klas zastępczych (`dataclasses`) w samym pliku testowym, aby testy działały niezależnie.

---

## Krok 1: `state/validator.py` (Sanity Checks)

Zaimplementuj klasę `StateValidator`, która weryfikuje spójność każdej klatki przed przekazaniem jej do silnika matematycznego.

### Wymagane metody i reguły
* **`__init__(self, total_chips: int = 900)`**
  * Przechowuje `self.total_chips = total_chips` (domyślnie `900`).
  * Przechowuje `self._last_blinds: dict[str, tuple[int, int]] = {}` (ostatnie poprawne blindy dla każdego `table_id`).
* **`reset_table(self, table_id: str) -> None`**
  * Usuwa historię blindów dla danego stołu (wywoływane po zakończeniu gry / starcie nowego turnieju).
* **`validate(self, state: TableState) -> tuple[bool, list[str]]`**
  * Zwraca `(True, [])`, jeśli wszystkie 3 reguły poniżej są spełnione, lub `(False, lista_błędów)`:
  1. **Zasada zachowania żetonów (`== 900`):**
     * Sprawdź, czy w `state.players` jest dokładnie 3 graczy (`len(state.players) == 3`).
     * Sprawdź, czy żaden gracz nie ma `stack is None` ani wartości ujemnych (`stack < 0`, `current_bet < 0`, `state.pot < 0`). Jeśli brakuje odczytu `stack`, dodaj błąd `"Missing stack reading"`.
     * Oblicz `chip_sum = state.pot + sum(p.stack + p.current_bet for p in state.players.values())`.
     * Jeśli `chip_sum != self.total_chips`, dodaj błąd `f"Chip conservation failed: {chip_sum} != {self.total_chips}"`.
  2. **Unikalność i poprawność kart:**
     * Zbierz `all_cards = list(state.hero_cards) + list(state.board_cards)`.
     * Jeśli `len(all_cards) != len(set(all_cards))`, dodaj błąd `"Duplicate cards detected"`.
     * Sprawdź dozwoloną liczbę kart: `len(state.hero_cards) in (0, 2)` oraz `len(state.board_cards) in (0, 3, 4, 5)`. W przeciwnym razie dodaj błąd `"Invalid card count"`.
  3. **Monotoniczność blindów:**
     * Sprawdź, czy `state.small_blind > 0` i `state.big_blind > state.small_blind`. Jeśli nie, dodaj błąd `"Invalid blinds"`.
     * Jeśli `state.table_id` jest już w `self._last_blinds`:
       * Niech `(prev_sb, prev_bb) = self._last_blinds[state.table_id]`.
       * Jeśli `state.small_blind < prev_sb` lub `state.big_blind < prev_bb`, dodaj błąd `f"Blinds decreased from {(prev_sb, prev_bb)} to {(state.small_blind, state.big_blind)}"`.
  * Jeśli brak błędów, zapisz `self._last_blinds[state.table_id] = (state.small_blind, state.big_blind)`.
* **`validate_and_mark(self, state: TableState) -> TableState`**
  * Wywołuje `validate(state)`, ustawia `state.is_valid = is_valid` i zwraca `state`.

---

## Krok 2: `state/tracker.py` (Maszyna Stanów i Timing Tells)

Zaimplementuj śledzenie historii stołu między kolejnymi poprawnymi klatkami.

1. **`GameEvent` (`@dataclass`):**
   * `event_type: str` (wartości: `"NEW_HAND"`, `"STREET_CHANGE"`, `"VILLAIN_ACTION"`, `"HERO_TURN"`)
   * `table_id: str`
   * `timestamp_ms: int`
   * `details: dict`
2. **`TableTracker`:**
   * **`__init__(self, table_id: str)`**
     * Przechowuje `prev_state: TableState | None = None`, `hand_number: int = 0`, `last_state_change_ms: int | None = None`.
   * **`update(self, state: TableState) -> tuple[TableState, list[GameEvent]]`**
     * Jeśli `not state.is_valid`: nie zmieniaj `prev_state`, zwróć `(state, [])`.
     * Jeśli `prev_state is None`:
       * Inkrementuj `hand_number = 1`, ustaw `last_state_change_ms = state.timestamp_ms`, zapisz `prev_state = state`, zwróć `(state, [GameEvent("NEW_HAND", ...)])`.
     * Wykrywanie **`NEW_HAND`**:
       * Gdy zmieniły się `hero_cards` (i nie są puste) LUB zmienił się gracz z `is_dealer == True` LUB `prev_state.street in ("FLOP", "TURN", "RIVER")` i `state.street == "PREFLOP"`.
       * Inkrementuj `hand_number`, zresetuj `last_state_change_ms = state.timestamp_ms`, dodaj zdarzenie `"NEW_HAND"`.
     * Wykrywanie **`STREET_CHANGE`**:
       * Jeśli nie było `NEW_HAND` i `state.street != prev_state.street` (np. `"PREFLOP"` → `"FLOP"`):
       * Zaktualizuj `last_state_change_ms = state.timestamp_ms`, dodaj zdarzenie `"STREET_CHANGE"`.
     * Wykrywanie **`VILLAIN_ACTION`** i pomiar **`last_reaction_ms` (Timing Tells)**:
       * Dla każdego rywala (`seat_id in (1, 2)`):
         * Porównaj `curr_p = state.players[seat_id]` z `prev_p = prev_state.players[seat_id]`.
         * Jeśli `curr_p.current_bet > prev_p.current_bet`:
           * Oblicz `reaction_ms = state.timestamp_ms - (self.last_state_change_ms or state.timestamp_ms)`.
           * Zapisz `curr_p.last_reaction_ms = max(0, reaction_ms)`.
           * Zaktualizuj `self.last_state_change_ms = state.timestamp_ms`.
           * Dodaj zdarzenie `"VILLAIN_ACTION"` ze szczegółami `{"seat_id": seat_id, "bet_delta": curr_p.current_bet - prev_p.current_bet, "reaction_ms": curr_p.last_reaction_ms}`.
     * Wykrywanie **`HERO_TURN`**:
       * Jeśli `state.is_hero_turn` i `not prev_state.is_hero_turn`:
         * Zaktualizuj `self.last_state_change_ms = state.timestamp_ms`.
         * Dodaj zdarzenie `"HERO_TURN"`.
     * Zapisz `self.prev_state = state` i zwróć `(state, events)`.

---

## Krok 3: `state/logger.py` (Lekki Logger `.jsonl`)

Zaimplementuj klasę `SessionLogger`:
* **`__init__(self, log_dir: str | Path = "logs")`**
  * Tworzy katalog `log_dir`, jeśli nie istnieje.
  * Otwiera plik `session_<YYYYMMDD_HHMMSS>.jsonl` w trybie dopisywania (`"a"`, `encoding="utf-8"`).
* **`log_state(self, state: TableState, events: list[GameEvent] | None = None) -> None`**
  * Zapisuje jedną linię JSON: `{"type": "state", "data": asdict(state), "events": [asdict(e) for e in (events or [])]}` i wykonuje `flush()`.
* **`log_decision(self, decision: Decision, latency_ms: float) -> None`**
  * Zapisuje jedną linię JSON: `{"type": "decision", "latency_ms": round(latency_ms, 2), "data": asdict(decision)}` i wykonuje `flush()`.
* **`close(self) -> None`**
  * Zamyka plik, jeśli jest otwarty. Obsługuje też protokół context managera (`__enter__`, `__exit__`).

---

## Krok 4: Testy Jednostkowe `tests/test_state.py`

Napisz testy w `pytest`:
1. `test_validator_valid_sum_900`: sprawdza, że poprawne rozdanie (`300 + 280 + 260 + pot 60 == 900`) przechodzi walidację (`True, []`).
2. `test_validator_invalid_sum`: sprawdza odrzucenie klatki, gdy suma żetonów wynosi np. `880`.
3. `test_validator_duplicate_cards`: sprawdza odrzucenie klatki z powtórzoną kartą (np. `Qh` u Hero i na flopie).
4. `test_validator_blinds_monotonicity`: sprawdza odrzucenie klatki, gdy blindy spadną z `(20, 40)` na `(10, 20)`.
5. `test_tracker_new_hand_street_and_timing`: symuluje sekwencję 3 poprawnych klatek w czasie (`t=1000`, `t=1350`, `t=2000`) i sprawdza wykrycie `NEW_HAND`, `VILLAIN_ACTION` z `last_reaction_ms == 350` oraz `STREET_CHANGE`.
6. `test_session_logger_jsonl`: zapisuje stan i decyzję do `tmp_path`, zamyka logger i weryfikuje poprawność parsowania każdej linii przez `json.loads()`.

### Kryterium odbioru
Uruchom w terminalu:
```bash
pytest -v tests/test_state.py
```
Polecenie musi zakończyć się kodem wyjścia `0`.
