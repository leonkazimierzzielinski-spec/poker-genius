# Plan V14.2 — 1 Gra = 1 Paczka `.zip` + `.md`, Czyste Śledzenie Ulic i Historii, Naprawa `KONIEC STOŁU` oraz Usunięcie Fałszywych `Timing Tell` (`poker_assistant`)

Dokument jest kompletną specyfikacją wdrożeniową przygotowaną na podstawie analizy pełnej gry live (`calagra.md`, 10 rozdań, 19 rozbitych paczek). Wszystkie decyzje architektoniczne zostały rozstrzygnięte poniżej.

> **Zasada "Zero działania na ślepo" (`QUESTIONS_V14_2.md`)**: Jeśli podczas wdrożenia trafisz na niejasność, konflikt z istniejącym kodem albo decyzję produktową/strategiczną, której plan nie rozstrzyga — **NIE zgaduj**. Zrealizuj wszystkie pewne elementy, a pytania (kontekst + opcje A/B) zapisz w pliku **`QUESTIONS_V14_2.md`** w katalogu głównym repozytorium i wypchnij go razem z commitem. Jeśli wszystko było jasne, nie twórz tego pliku.

## 0. Zestawienie Wszystkich 8 Poprawek w V14.2 (Już Rozstrzygnięte)

| Nr | Problem wykryty w `calagra.md` | Plik | Obowiązujące rozwiązanie |
|---|---|---|---|
| **1** | 1 gra rozbita na **19 paczek `.zip`** przez `opp_sig < 0.85` przy dymkach akcji | `main.py` (linie ~1076–1101) | Usuń `finalize_game`, `trackers.pop`, `decision_locks.pop` i `validator.reset_table` z bloku `compute_opponents_signature`. Zamykaj grę tylko przy pewnym końcu turnieju (3 klatki), nowym turnieju lub zamknięciu aplikacji / usunięciu stołu. |
| **2** | Brak łatwego pliku `.md` do wysłania bez rozpakowywania `.zip` | `state/hand_history.py` | W `finalize_game` oprócz `game_...zip` zapisuj obok w `hand_histories/` bezpośrednią kopię `game_...md` + sekcję `## 📊 Podsumowanie gry` na dole raportu. |
| **3** | Fałszywy `🏆 KONIEC STOŁU — Zwycięzca: Ty (S0), stack 100` przy All-Inie dwóch rywali (`21:44:49`) | `state/tracker.py`, `main.py` | `tournament_result` tylko gdy 1 gracz ma `stack >= 880` **ORAZ `pot == 0`**, LUB dwaj pozostali mają `eliminated == True` (`stack is None`, status `OUT`) — **NIGDY** gdy `stack == 0` podczas All-Ina z `pot > 0`. W `main.py` wymagaj 3 kolejnych klatek `VALID` potwierdzających `tournament_result`. |
| **4** | `WAITING_FOR_TURN <-> PREFLOP` traktowane jako `STREET_CHANGE` → podwójne/potrójne `Włożył` (`40→80→120→160`) i fałszywe `FOLD` | `state/tracker.py` | Wyznaczaj realną ulicę wyłącznie z `len(board_cards)` (`0→PREFLOP`, `3→FLOP`, `4→TURN`, `5→RIVER`). Przejście `WAITING_FOR_TURN <-> PREFLOP` przy tej samej liczbie kart na stole **nie jest** zmianą ulicy, nie zeruje `street_bet` i nie uruchamia Warunku B (`FOLD`). |
| **5** | Fałszywy `Timing Tell: fast check <500ms` odpalany po `0 ms` niemal na każdym Flopie (psujący decyzje strategii!) | `state/tracker.py`, `strategy/exploit.py` (linia ~58) | Zeruj `last_reaction_ms = None` przy każdej realnej zmianie ulicy (`STREET_CHANGE`), a w `strategy/exploit.py` wymagaj `150 <= last_reaction_ms < 500` (odrzucając artefakty `0..149 ms` z klatek przejścia). |
| **6** | Jednocyfrowe glitche animacji OCR (`BET 1`, `BET 2`, `RAISE 4`) i artefakt zgarniania puli (`BET 740` na starcie rozdania `30/60`) | `state/tracker.py` | Ignoruj nowy bet gdy `0 < curr_bet < small_blind` i `(stack or 0) > 0`. Na starcie nowego rozdania bez kart na boardzie (`len(board_cards) == 0`, brak kart Hero) ignoruj pozostałość animacji z poprzedniego rozdania (`cur_bet > 2 * big_blind`, np. `740`). |
| **7** | Rekomendacja `ALL_IN (0)` po tym, jak Hero już wrzucił ostatnie żetony (`stack == 0`) | `main.py` | Gdy `hero_stack == 0` (Hero jest już All-In), nie licz decyzji i nie emituj `ALL_IN (0)` — zwróć `WAIT` (`"Hero is All-In"`). |
| **8** | Powielone `[PLAN]` w tabeli `HUD vs Hero` i zduplikowane ścieżki zdjęć (`h002_decision_preflop.jpg` ×4) | `state/tracker.py`, `state/hand_history.py`, `main.py` | W `record_recommendation` zapisuj realną ulicę, pomijaj `[PLAN]` z tabeli `HUD vs Hero` i deduplikuj po `(real_street, action, sizing_bb, sizing_chips)`. W `snapshots` nie dodawaj duplikatów tej samej ścieżki (dla kolejnych decyzji na tej samej ulicy dodawaj licznik `_2`, `_3` tylko przy zmianie sytuacji). |

## 1. Krok 1: 1 Gra = 1 Paczka `.zip` + Kopia `.md` (`main.py`, `state/hand_history.py`)

### 1.1. Usunięcie przedwczesnego zamykania gier w `main.py`
1. W `main.py` (okolice linii 1076–1101) **usuń całkowicie** wywołania:
   * `validator.reset_table(table_id)`
   * `hand_recorder.record_hand(...)` / `hand_recorder.finalize_game(table_id)`
   * `trackers.pop(table_id, None)`, `decision_locks.pop(...)`, `last_active_decisions.pop(...)`, `last_spots.pop(...)`
   z bloku `compute_opponents_signature` (`match_score < 0.85`).
2. Wprowadź licznik potwierdzeń końca turnieju per stół: `tournament_end_confirm: dict[str, int] = {}` oraz flagę `finalized_tournament_tables: set[str] = set()`:
   * Gdy `state.is_valid` i `trackers[resolved_tid].current_hand.get("tournament_result")` jest obecne:
     * zwiększ `tournament_end_confirm[resolved_tid] += 1`.
     * Dopiero gdy `tournament_end_confirm[resolved_tid] >= 3` i `resolved_tid not in finalized_tournament_tables`:
       * zapisz bieżące rozdanie `hand_recorder.record_hand(trackers[resolved_tid].current_hand)`,
       * wywołaj `hand_recorder.finalize_game(resolved_tid, prize_pool=state.prize_pool)`,
       * dodaj `resolved_tid` do `finalized_tournament_tables`.
   * Jeśli `resolved_tid in finalized_tournament_tables`:
     * odblokuj zapis nowej gry (usuń z `finalized_tournament_tables` i zresetuj tracker) **dopiero gdy** pojawi się realna nowa gra: co najmniej 2 graczy ma `stack is not None` i `0 < stack < 880` (np. start nowego turnieju `300/300/300` przy `10/20`).
   * Jeśli `tournament_result` zniknie przed osiągnięciem 3 klatek → wyzeruj `tournament_end_confirm[resolved_tid] = 0`.
3. Wykrywanie nowego turnieju na tym samym oknie (bez opierania się na `opp_sig`):
   * Spadek blindów z wyższego poziomu na `10/20` przy początkowych stackach `200..400` u min. 2 graczy (już istnieje w `main.py` linie ~1123–1147 — zostaje i wywołuje `record_hand` + `finalize_game`), **LUB**
   * Powrót z Heads-Up (poprzednio co najmniej 1 gracz miał `eliminated == True` / `OUT`) do pełnego 3-max ze stackami `260..320` u wszystkich 3 graczy przy blindach `10/20`.
4. **Ochrona przed `ALL_IN (0)` w `main.py`:**
   * Przed blokiem liczenia decyzji sprawdź `hero_stk = getattr(getattr(state, "players", {}).get(0), "stack", None)`.
   * Jeśli `hero_stk == 0`: zwróć `Decision(table_id=resolved_tid, action="WAIT", ev_bb=None, confidence=1.0, profile_used="STANDARD_EXPLOIT", reason="Hero is All-In")` i nie emituj rekomendacji `ALL_IN (0)`.

### 1.2. Kopia `.md` obok `.zip` i podsumowanie gry (`state/hand_history.py`)
1. W `HandHistoryRecorder.finalize_game(table_id, prize_pool=None)`:
   * Przed spakowaniem dopisz na końcu `history.md` zwięzłą sekcję **`## 📊 Podsumowanie gry`**:
     * liczba zapisanych rozdań,
     * pula nagród (`$prize`),
     * zwycięzca turnieju (jeśli wykryto `tournament_result`),
     * liczba decyzji HUD w turze Hero.
   * Spakuj `history.md`, `history.jsonl` oraz (jeśli włączone) `snapshots/*.jpg` do `hand_histories/game_<ts>_<table_id>[_prize<X>].zip`.
   * **Skopiuj `history.md` bezpośrednio obok archiwum** jako `hand_histories/game_<ts>_<table_id>[_prize<X>].md` (przed usunięciem folderu `_active/game_.../`).
   * Zapewnij deduplikację listy `snapshots` w `_render_hand_markdown` (użyj `dict.fromkeys(snapshots)`), żeby żadne zdjęcie nie pojawiało się w raporcie wielokrotnie.
2. W `main.py` przy zapisie snapshotu decyzji (`LOCKED_DECISION`):
   * Użyj licznika na ulicę w bieżącym rozdaniu (np. `decision_preflop_1`, `decision_preflop_2`), tylko gdy faktycznie zmieniła się zatwierdzona decyzja (nie nadpisuj i nie dubluj ścieżek).

## 2. Krok 2: Realna Ulica, Poprawny `tournament_result`, Filtr Glitchy OCR i Czyste `Timing Tell` (`state/tracker.py`, `strategy/exploit.py`)

### 2.1. Realna ulica z liczby kart na stole (`state/tracker.py`)
1. Dodaj funkcję pomocniczą `_resolve_real_street(state: TableState) -> str`:
   ```python
   def _resolve_real_street(state: TableState) -> str:
       n_board = len(getattr(state, "board_cards", []) or [])
       if n_board >= 5:
           return "RIVER"
       if n_board == 4:
           return "TURN"
       if n_board == 3:
           return "FLOP"
       return "PREFLOP"
   ```
2. W `TableTracker` utrzymuj `self._current_real_street: str` (ustawiane w `_init_current_hand` z `_resolve_real_street(state)`):
   * `STREET_CHANGE` zachodzi **WYŁĄCZNIE** gdy `new_real_street != self._current_real_street` (i wyłącznie do przodu: `PREFLOP → FLOP → TURN → RIVER`, nie przy przejściu `WAITING_FOR_TURN <-> PREFLOP`!).
   * Tylko przy takim realnym `STREET_CHANGE`:
     * zeruj `p_dict["street_bet"] = 0`,
     * uruchamiaj Warunek B (`FOLD` dla niewyrównanego betu z poprzedniej ulicy),
     * zeruj `last_reaction_ms = None` u wszystkich graczy (żeby czas z Preflopu nigdy nie przenosił się na Flop!).
   * W `action_log` oraz `record_recommendation` zawsze wpisuj **`real_street`** (`PREFLOP`/`FLOP`/`TURN`/`RIVER`), nigdy `WAITING_FOR_TURN`.

### 2.2. Naprawa `tournament_result` (brak fałszywego końca przy All-Inie dwóch rywali)
W `state/tracker.py` w sekcji wykrywania `tournament_result`:
```python
pot_val = int(getattr(state, "pot", 0) or 0)
eliminated_count = sum(
    1 for sid in (0, 1, 2)
    if self.current_hand.get("players", {}).get(sid, {}).get("eliminated", False)
)
big_stack_p = [
    sid for sid in (0, 1, 2)
    if sid in state.players and (getattr(state.players[sid], "stack", None) or 0) >= 880
]
# Koniec turnieju WYŁĄCZNIE gdy:
# (A) 1 gracz ma >= 880 żetonów i pula jest już zebrana (pot == 0), LUB
# (B) dokładnie 2 graczy ma status OUT (eliminated == True, stack is None) i 1 gracz pozostał z stack > 0 oraz pot == 0
if pot_val == 0 and (len(big_stack_p) == 1 or eliminated_count == 2):
    ...
```
Dzięki warunkowi `pot_val == 0` oraz rozróżnieniu `eliminated == True` (`stack is None`) od `stack == 0` podczas All-Ina, sytuacja z `21:44:49` (`S0=100`, `S1=0`, `S2=0`, `pot=800`) **nigdy więcej** nie ogłosi fałszywego końca stołu!

### 2.3. Filtr glitchy animacji OCR (`< small_blind`) oraz artefaktów zgarniania puli (`> 2 * big_blind` na starcie)
1. W `_init_current_hand(state)`:
   * Jeśli `len(state.board_cards) == 0` i `not state.hero_cards` (sam start nowego rozdania, animacja po poprzednim rozdaniu) i `cur_bet > 2 * max(1, state.big_blind)` (np. `740` przy `30/60`): traktuj `cur_bet` jako `0` (artefakt animacji zgarniania puli, nie dopisuj `BET 740`!).
2. W `update(state)` przy wzroście `curr_p.current_bet > street_bet`:
   * Jeśli `0 < curr_p.current_bet < max(1, state.small_blind)` i `(curr_p.stack or 0) > 0`: **ignoruj ten glitch OCR** (nie zapisuj `BET 1`, `BET 2`, `RAISE 4` i nie aktualizuj `street_bet`).

### 2.4. Czysta tabela `HUD vs Hero` i naprawa fałszywych `Timing Tell`
1. **`state/tracker.py` (`record_recommendation`)**:
   * Pomijaj rekomendacje z `reason` zaczynającym się od `"[PLAN]"` (nie zaśmiecaj tabeli `HUD vs Hero` podglądem sprzed tury — zostaw tylko realne decyzje podjęte w turze Hero!).
   * Używaj `real_street` (nigdy `WAITING_FOR_TURN`) i deduplikuj po `(real_street, action, sizing_bb, sizing_chips)`.
2. **`strategy/exploit.py` (linie ~55–65)**:
   * Zmień warunek `last_reaction_ms < 500` na **`150 <= last_reaction_ms < 500`**, żeby `0 ms` (artefakt klatki przejścia) nigdy nie odpalał fałszywego `Timing Tell: fast check <500ms`.

## 3. Krok 3: Testy Jednostkowe i Weryfikacja (Obowiązkowe)

1. **Nowe testy w `tests/test_state.py`:**
   * `test_tracker_no_false_tournament_end_on_two_opponents_all_in`: `S0=100`, `S1=0`, `S2=0`, `pot=800` → `tournament_result` MUSI być `None`; dopiero przy `S2=900, pot=0` (lub 2 graczy `OUT` i `pot=0`) ustawia się `tournament_result`.
   * `test_tracker_waiting_for_turn_does_not_double_invested_or_false_fold`: przejścia `WAITING_FOR_TURN -> PREFLOP -> WAITING_FOR_TURN` przy tym samym becie `40` na stole NIE zwiększają `invested_total` ponad `40` i NIE ustawiają fałszywego `FOLD`.
   * `test_tracker_ignores_sub_sb_ocr_glitch_and_stale_pot_sweep`: `BET 1`, `BET 2`, `RAISE 4` (< `small_blind=10`) są ignorowane; `cur_bet=740` na starcie rozdania `30/60` bez kart na boardzie jest ignorowane.
   * `test_hand_history_saves_both_zip_and_standalone_md_with_summary`: po `finalize_game` w `hand_histories/` istnieją dokładnie 1 plik `.zip` i 1 plik `.md` z sekcją `## 📊 Podsumowanie gry` i bez duplikatów w `snapshots`.
2. **Nowe testy w `tests/test_strategy.py`:**
   * `test_exploit_timing_tell_ignores_zero_ms_transition_artifact`: `last_reaction_ms = 0` lub `50` NIE odpala `Timing Tell: fast check <500ms`; dopiero `250` odpala.
3. **Nowy test w `tests/test_ui_and_main.py`:**
   * `test_hero_all_in_stack_zero_returns_wait_not_all_in_zero`: przy `hero.stack == 0` system zwraca `WAIT` (`"Hero is All-In"`), nie `ALL_IN (0)`.
4. **Weryfikacja końcowa:**
   * Uruchom pełny **`pytest -v tests/`** — 100% testów na zielono.
   * Sprawdź brak regresji na nagraniach w `nagrania testowe/` (100% `VALID` przez `RIM`).

## 4. Obowiązkowa Synchronizacja na GitHub (Po Zakończeniu Prac)

1. Jeśli pojawiły się jakiekolwiek niejasności — zapisz je w **`QUESTIONS_V14_2.md`** w katalogu głównym repozytorium (nie zgaduj!). Jeśli wszystko było jasne, nie twórz tego pliku.
2. Dopisz szczegółowy raport V14.2 na samej górze **`PROGRESS_LOG.md`**.
3. Wykonaj `git add -A`, `git commit -m "V14.2: Single ZIP+MD per game, real street tracking, fix false tournament end & 0ms Timing Tell, filter OCR glitches"`, `git push origin main`.
4. W odpowiedzi końcowej napisz krótkie potwierdzenie (z informacją, czy utworzono `QUESTIONS_V14_2.md`) i podaj **WYŁĄCZNIE** link do repozytorium:
   `https://github.com/leonkazimierzzielinski-spec/poker-genius`
