# Plan V14 — Stabilizacja i Zatwierdzanie Decyzji (`DecisionLock`), Naprawa Historii Rozdań + Zwycięzca Stołu oraz Osobne Paczki `.zip` dla Każdej Gry z Lekkim Zapisem Zdjęć (`poker_assistant`)

Dokument jest kompletną specyfikacją wdrożeniową dla V14 na bazie analizy realnej sesji live (`session_20261121_200325.md`) oraz audytu pętli decyzyjnej (`main.py`, `engine/monte_carlo.py`, `state/tracker.py`, `state/hand_history.py`).

> **Zasada "Zero działania na ślepo" (`QUESTIONS_V14.md`)**: Jeśli w trakcie wdrożenia trafisz na cokolwiek niejednoznacznego, konflikt z istniejącym kodem albo decyzję produktową/strategiczną, której ten plan nie rozstrzyga — **NIE zgaduj**. Zrealizuj wszystkie pewne części, a otwarte pytania (kontekst + konkretne opcje A/B) zapisz w pliku **`QUESTIONS_V14.md`** w katalogu głównym repozytorium i wypchnij go razem z commitem. Jeśli wszystko było jasne, nie twórz tego pliku.

## 0. Kluczowe Decyzje Architektoniczne (Już Podjęte)

| Obszar | Podjęta decyzja (obowiązująca) | Powód |
| ----- | ----- | ----- |
| **Eliminacja wahania decyzji (Monte Carlo)** | W `engine/monte_carlo.py` dodaj opcjonalny parametr `seed: int \| None = None` i używaj lokalnego `rng = random.Random(seed)` zamiast globalnego `random`. Seed wyliczaj deterministycznie z `(sorted(hero_cards), tuple(board_cards), num_opponents)`. | Usuwa losowy szum ±2% equity między klatkami — dla tej samej ręki i boardu wynik jest w 100% powtarzalny. |
| **Zatwierdzanie decyzji (`DecisionLock`)** | Nowa klasa `DecisionLock(confirm_frames=2)` w `strategy/decision_lock.py`. Dla tego samego `fingerprintu` sytuacji na stole liczy decyzję **tylko raz** (z precyzyjniejszym budżetem `time_budget_ms=80.0`) po 2 kolejnych zgodnych `VALID` klatkach (w `offline`/testach `confirm_frames=1`), **zatwierdza ją** i zwraca z cache'u aż do realnej zmiany stanu stołu. | Koniec z mruganiem HUD między dwiema akcjami 10–20 razy/s i spadek zużycia CPU (`< 5 ms` na zablokowanej decyzji). |
| **Naprawa przecinania rozdań (`NEW_HAND`)** | W `state/tracker.py` zmień `hero_cards_changed` na **`bool(prev_known_hero) and bool(state.hero_cards) and state.hero_cards != prev_known_hero`**. | Naprawia błąd z sesji live, gdzie pojawienie się kart Hero po `WAITING_FOR_TURN` wywoływało fałszywe `NEW_HAND` i ucinało rozdanie po 2 sekundach. |
| **Blindy vs `BET/RAISE` i `OUT` vs `FOLD`** | W `WAITING_FOR_TURN` oraz przed pierwszym rozdaniem kart Hero pojawienie się zakładu równego `small_blind` lub `big_blind` to **`BLIND`** (`decision_sec=None`), a nie `BET`/`RAISE`. Gracz z `stack is None` i `not is_active` otrzymuje status **`OUT`** (`eliminated=True`), nie `FOLD`. | Koniec z błędnymi wpisami `BET 10 (0.5s)` / `RAISE 20 (0.9s)` za blindy oraz `BLIND 610` na Riverze. |
| **Zwycięzca rozdania i całego stołu** | Zwycięzca rozdania wyliczany przy zamknięciu rozdania `N` z delty stacków między startem `N` a startem `N+1` (skorygowanej o blindy startowe `N+1`). Zwycięzca stołu wykrywany, gdy 1 gracz ma `stack >= 880` (lub pozostali dwaj mają `stack in (0, None)` / status `OUT`). | Pozwala od razu zobaczyć w `history.md` i `history.jsonl`, kto wygrał każde rozdanie i kto wygrał cały turniej. |
| **Osobna paczka `.zip` dla każdej gry + lekkie zrzuty** | Każda gra (turniej 3-max) zbiera dane w osobnym katalogu roboczym i po zakończeniu gry (koniec stołu, zmiana przeciwników/nowa gra, usunięcie stołu lub zamknięcie aplikacji) jest **automatycznie pakowana do osobnego pliku `.zip`**: `hand_histories/game_YYYYMMDD_HHMMSS_<table_id>_prize<X>.zip` zawierającego `history.md`, `history.jsonl` oraz (gdy włączone) podfolder `snapshots/` z lekkimi JPEG `640 px` (quality=65, ~25–35 KB/szt.). Katalog roboczy jest sprzątany po spakowaniu. | Jedna gra = jedna gotowa, mała paczka `.zip` (~0.5–2 MB), którą można od razu wysłać do analizy razem z historią JSONL, raportem MD i kluczowymi zrzutami. |

## 1. Krok 1: Deterministyczne Monte Carlo i Zatwierdzanie Decyzji (`engine/monte_carlo.py`, `strategy/decision_lock.py`, `main.py`)

### 1.1. Deterministyczny `rng` w `engine/monte_carlo.py`
1. W `MonteCarloCalculator.estimate_equity(...)` dodaj opcjonalny parametr `seed: int | None = None`:
   * Jeśli `seed is None`, oblicz stabilny deterministyczny seed z wejścia:
     ```python
     key_str = f"{sorted(hero_cards)}|{list(board_cards)}|{num_opponents}|{len(villain_range) if villain_range else 0}"
     seed = zlib.crc32(key_str.encode("utf-8")) & 0xFFFFFFFF
     ```
   * Utwórz lokalny generator `rng = random.Random(seed)` i zamień wszystkie wywołania `random.choice(...)` oraz `random.sample(...)` wewnątrz `estimate_equity` na `rng.choice(...)` / `rng.sample(...)`.
   * Zachowaj pełną kompatybilność wsteczną sygnatury.

### 1.2. Klasa `DecisionLock` (`strategy/decision_lock.py`)
Stwórz moduł `strategy/decision_lock.py`:

```python
def compute_decision_fingerprint(state: TableState, is_preview: bool = False) -> tuple:
    """Zwraca niezmienną krotkę opisującą konkretną sytuację decyzyjną na stole."""
    players = getattr(state, "players", {}) or {}
    players_sig = tuple(
        (
            sid,
            getattr(players[sid], "current_bet", 0) if sid in players else 0,
            getattr(players[sid], "stack", None) if sid in players else None,
            bool(getattr(players[sid], "is_active", True)) if sid in players else False,
            bool(getattr(players[sid], "is_dealer", False)) if sid in players else False,
        )
        for sid in (0, 1, 2)
    )
    return (
        tuple(sorted(getattr(state, "hero_cards", []) or [])),
        tuple(getattr(state, "board_cards", []) or []),
        getattr(state, "street", ""),
        bool(getattr(state, "is_hero_turn", False)),
        bool(is_preview),
        tuple(sorted(getattr(state, "available_actions", []) or [])),
        int(getattr(state, "pot", 0) or 0),
        int(getattr(state, "big_blind", 20) or 20),
        players_sig,
    )
```

Klasa `DecisionLock`:
* Atrybuty: `confirm_frames: int = 2`, `_pending_fp: tuple | None = None`, `_pending_count: int = 0`, `_locked_fp: tuple | None = None`, `_locked_decision: Decision | None = None`.
* Metody:
  1. `get_locked(fp: tuple) -> Decision | None`: jeśli `fp == self._locked_fp`, zwraca zatwierdzoną decyzję bez ponownego przeliczania.
  2. `observe_and_should_compute(fp: tuple) -> bool`: zwraca `False`, jeśli `fp == self._locked_fp`; dla nowego `fp` zeruje licznik na `1`, dla powtórzonego zwiększa `_pending_count += 1` i zwraca `True`, gdy `_pending_count >= self.confirm_frames`.
  3. `lock(fp: tuple, decision: Decision) -> None`: zatwierdza decyzję dla `fp`.
  4. `reset() -> None`: czyści blokadę (przy `NEW_HAND` lub usunięciu stołu).

### 1.3. Integracja `DecisionLock` w `main.py`
1. W `processing_loop(...)` utrzymuj `decision_locks: dict[str, DecisionLock] = {}` (`confirm_frames = 2 if is_live else 1`).
2. Gdy `state.is_valid` i mamy 2 karty Hero (dla tury Hero lub trybu `[PLAN]`):
   * Oblicz `fp = compute_decision_fingerprint(sim_state_or_state, is_preview=is_preview_candidate)`.
   * Jeśli `lock.get_locked(fp)` zwróci decyzję → użyj jej bezpośrednio bez ponownego wywoływania `evaluate_candidates` / `decision_maker.decide`.
   * Jeśli `lock.observe_and_should_compute(fp)` zwróci `True` → przelicz decyzję z `time_budget_ms=80.0`, skwantyzuj sizing BB/ALL-IN, wywołaj `lock.lock(fp, decision)` i ustaw `just_locked_decision = True`.
   * Jeśli `False` (1. klatka zmiany stanu) → zachowaj poprzednią decyzję (lub `WAIT` z `"Skanowanie sytuacji..."`) bez migotania.
3. Przy `NEW_HAND` wywołaj `decision_locks[resolved_tid].reset()`.

## 2. Krok 2: Naprawa 5 Błędów Historii Rozdań + Zwycięzca Rozdania i Stołu (`state/tracker.py`, `main.py`)

1. **Naprawa fałszywego `NEW_HAND` (`state/tracker.py`, linia ~155):**
   ```python
   prev_known_hero = self.prev_state.hero_cards or self.current_hand.get("hero_cards") or []
   hero_cards_changed = (
       bool(prev_known_hero)
       and bool(state.hero_cards)
       and state.hero_cards != prev_known_hero
   )
   ```
2. **Status `OUT` zamiast `FOLD` dla wyeliminowanych graczy:**
   * Jeśli `p.stack is None` i `not p.is_active`, ustaw `"eliminated": True`, `"folded": False`, `"status": "OUT"`, `"last_action": "OUT"` (nie dopisuj `FOLD` do `action_log`).
3. **Naprawa `BLIND 610` na Riverze i `BET 10 / RAISE 20` w `WAITING_FOR_TURN`:**
   * W `_init_current_hand(state)` zapisz `starting_stacks` i `starting_bets`. Jeśli `len(state.board_cards) > 0` lub `cur_bet > state.big_blind`, nie wpisuj `PREFLOP | BLIND`, tylko `"BET"` na aktualnej ulicy (`state.street`) + `"mid_hand_join": True`.
   * Podczas `update(state)` przy wzroście `curr_p.current_bet > street_bet`: jeśli ulica to `"WAITING_FOR_TURN"` lub `"PREFLOP"`, brak jeszcze kart Hero (`not self.current_hand.get("hero_cards")`), a `curr_p.current_bet in (state.small_blind, state.big_blind)` i gracz nie miał jeszcze `BLIND` → zapisz akcję jako **`"BLIND"`** z `decision_sec = None`.
   * Rejestruj również **faktyczne akcje Hero (`seat_id == 0`)**: `CALL`, `BET`, `RAISE`, `ALL-IN`, `FOLD` oraz `CHECK` (gdy `prev_state.is_hero_turn` było `True`, `to_call == 0`, tura się skończyła i `hero_bet` nie wzrósł).
4. **Wyliczanie Zwycięzcy Rozdania i Całego Stołu:**
   * Przy zamknięciu rozdania `N` (start `N+1`): porównaj `start_total = starting_stacks[sid] + starting_bets[sid]` z `end_total = (next_state.players[sid].stack or 0) + (next_state.players[sid].current_bet or 0)`. Zapisz `last_completed_hand["result"] = {"winner_seat": sid, "winner_name": name, "net_delta": delta, "deltas": net_delta}`.
   * **Zwycięzca całego stołu (`tournament_result`)**: gdy w `state` dokładnie 1 gracz ma `stack >= 880` (lub pozostali dwaj mają `stack in (0, None)` / `OUT`), zapisz `current_hand["tournament_result"] = {"winner_seat": sid, "winner_name": name, "prize_pool": state.prize_pool, "final_stack": stack}`.

## 3. Krok 3: Osobne Paczki `.zip` dla Każdej Gry + Wyłączalny Tryb Lekkich Zrzutów (`config.json`, `state/hand_history.py`, `main.py`, `ui/hud.py`)

### 3.1. Struktura paczki `.zip` per gra (`HandHistoryRecorder` w `state/hand_history.py`)
Zamiast mieszać wszystkie gry sesji w jednym pliku, `HandHistoryRecorder` utrzymuje osobny kontekst **per aktywna gra na stole (`table_id`)**:
* Katalog roboczy w trakcie trwania gry: `hand_histories/_active/game_<YYYYMMDD_HHMMSS>_<table_id>/` zawierający:
  * `history.jsonl` — pełny zapis strukturalny JSONL wszystkich rozdań z tej jednej gry,
  * `history.md` — czytelny raport Markdown (gracze ze statusem `ACTIVE/FOLD/OUT`, przebieg akcji z czasem, sekcja **`Podjęte decyzje: HUD vs Hero`**, **`Wynik rozdania`**, osadzone linki do zdjęć `![...](snapshots/...)` oraz baner **`🏆 KONIEC STOŁU — Zwycięzca turnieju`**),
  * `snapshots/` — podfolder z lekkimi zdjęciami JPEG `640 px` wyłącznie z tej jednej gry (jeśli `save_snapshots=True`).
* **Automatyczne pakowanie do `.zip` (`finalize_game(table_id, prize_pool=None) -> Path | None`):**
  * Pakuje całą zawartość katalogu roboczego gry (używając standardowego modułu `zipfile.ZipFile(..., compression=zipfile.ZIP_DEFLATED)`) do jednego pliku:
    `hand_histories/game_<YYYYMMDD_HHMMSS>_<table_id>_prize<prize>.zip` (np. `game_20261121_201500_table_1_prize4.zip`).
  * Pomija tworzenie pustego `.zip`, jeśli gra nie miała żadnego zapisanego rozdania.
  * Po poprawnym zapisaniu archiwum `.zip` bezpiecznie usuwa roboczy podfolder `_active/game_.../` (`shutil.rmtree(..., ignore_errors=True)`), dzięki czemu w `hand_histories/` leżą wyłącznie czyste, gotowe paczki `.zip` — **1 plik `.zip` = 1 gra**.
* **Kiedy wywoływać `finalize_game(table_id)` w `main.py`:**
  1. Gdy wykryto **koniec stołu** (`tournament_result` w `current_hand`),
  2. Gdy na tym samym oknie wykryto **nową grę / zmianę przeciwników** (reset trackera przy zmianie `opponents_signature` lub gdy stacki wracają do `300/300/300` przy `10/20`),
  3. Przed każdym `trackers.pop(tid, None)` (najpierw `record_hand` bieżącego rozdania, potem `finalize_game(tid)`),
  4. Przy zamykaniu aplikacji w `close(active_trackers)` (zapisuje bieżące rozdania w locie i pakuje wszystkie otwarte gry do `.zip`).

### 3.2. Wyłączalny tryb lekkich zrzutów (`save_snapshots`)
1. **`config.json` — sekcja `recording`:**
   ```json
   "recording": {
     "save_snapshots": true,
     "snapshot_width": 640,
     "snapshot_jpeg_quality": 65
   }
   ```
2. **Metoda `save_snapshot(frame_bgr, table_rect, table_id, hand_number, event_label) -> str | None`:**
   * Jeśli `not self.save_snapshots` lub `frame_bgr is None` → natychmiast zwraca `None` (zero I/O, w `.zip` nie będzie wtedy folderu `snapshots/`).
   * Wycina `table_rect`, skaluje z zachowaniem proporcji do `640 px` szerokości (`cv2.INTER_AREA`) i zapisuje jako JPEG (`quality=65`, `~20–35 KB`) do `snapshots/h{hand_number:03d}_{event_label}.jpg` w katalogu aktywnej gry.
3. **Kluczowe momenty zapisu zdjęcia w `main.py` (max ~3–4 zdjęcia / rozdanie):**
   * `LOCKED_DECISION` (raz przy zatwierdzeniu nowej decyzji w turze Hero),
   * `STREET_CHANGE` (raz przy przejściu na `FLOP`, `TURN`, `RIVER`),
   * `HAND_END` (raz przy końcu rozdania / showdownie).
4. **Wyłączanie trybu zrzutów:**
   * **CLI (`main.py`)**: `--save-snapshots` / `--no-snapshots`.
   * **HUD (`ui/hud.py`)**: mały przełącznik **`📷`** w panelu `Szczegóły` (widoczny dopiero po kliknięciu `🔍 Szczegóły`, obok `🎯` i `⚙`), podpięty sygnałem `HudBridge.snapshots_toggled = Signal(bool)` do `hand_recorder.save_snapshots`.

## 4. Krok 4: Testy i Weryfikacja (Obowiązkowe)

1. **Nowe testy jednostkowe:**
   * `tests/test_engine.py`: `test_monte_carlo_deterministic_seed` — identyczny wynik co do `1e-9` dla tych samych kart i boardu.
   * `tests/test_strategy.py`: `test_decision_lock_confirms_and_freezes_until_state_change` — 2-klatkowe potwierdzenie, zamrożenie przy tym samym `fingerprint` i odblokowanie po zmianie stanu.
   * `tests/test_state.py`:
     * `test_tracker_no_false_new_hand_on_waiting_to_preflop_and_blinds_not_bets` — odtwarza scenariusz z `session_20261121_200325.md` (`BLIND`, brak fałszywego `NEW_HAND`, status `OUT`).
     * `test_tracker_winner_delta_and_tournament_winner` — zwycięzca rozdania z delty stacków + `tournament_result`.
     * `test_hand_history_per_game_zip_with_and_without_snapshots` — sprawdza, że 2 oddzielne gry tworzą **2 oddzielne pliki `.zip`**, każdy zawiera `history.md` i `history.jsonl`, a przy `save_snapshots=True` również `snapshots/*.jpg` (`width == 640`, `< 60 KB`), natomiast przy `save_snapshots=False` paczka `.zip` zawiera tylko `history.md` i `history.jsonl` bez zdjęć; weryfikuje posprzątanie katalogu `_active/`.
   * `tests/test_ui_and_main.py`: `test_hud_snapshots_toggle_button_in_details` — przycisk `📷` ukryty w trybie minimalistycznym, widoczny w `Szczegółach`, emituje `snapshots_toggled`.
2. **Weryfikacja końcowa:**
   * Uruchom pełny **`pytest -v tests/`** — 100% testów na zielono.
   * Przetestuj ścieżkę na nagraniach w `nagrania testowe/` — 100% `VALID` przez `RIM`, brak regresji.

## 5. Obowiązkowa Synchronizacja na GitHub (Po Zakończeniu Prac)

1. Jeśli pojawiły się jakiekolwiek niejasności lub otwarte pytania — zapisz je w **`QUESTIONS_V14.md`** w katalogu głównym repozytorium (nie zgaduj!). Jeśli wszystko było jasne, nie twórz tego pliku.
2. Dopisz szczegółowy raport V14 (zmiany, wyniki `pytest`, weryfikacja) na samej górze **`PROGRESS_LOG.md`**.
3. Wykonaj `git add -A`, `git commit -m "V14: DecisionLock + deterministic MC, fixed hand history & winners, per-game ZIP packages with toggleable snapshots"`, `git push origin main`.
4. W odpowiedzi końcowej napisz krótkie potwierdzenie (z informacją, czy utworzono `QUESTIONS_V14.md`) i podaj **WYŁĄCZNIE** link do repozytorium:
   `https://github.com/leonkazimierzzielinski-spec/poker-genius`