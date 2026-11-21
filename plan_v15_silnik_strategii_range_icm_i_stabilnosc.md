# Plan V15 — Nowy Silnik Strategii (`Range-vs-Range` + Pełny Preflop 0–15 BB + ICM od 5x), Alternatywa na HUD, Stabilność `Ts` oraz Eksport Wszystkich Gier (`poker_assistant`)

Dokument jest kompletną specyfikacją wdrożeniową V15 opartą o wyniki researchu strategii 3-max Hyper-Turbo 15 BB, specyfikację sprzętu użytkownika (**Intel Core Ultra 5 225H**, 14 rdzeni @ 4.9 GHz AVX2, Intel Arc 130T, budżet do `3 s` na trudny postflop) oraz analizę 3 realnych turniejów (`game_223325` – `game_224328`).

> **Zasada "Zero działania na ślepo" (`QUESTIONS_V15.md`)**: Jeśli podczas wdrożenia trafisz na cokolwiek niejednoznacznego, konflikt z istniejącym kodem albo decyzję produktową/strategiczną, której ten plan nie rozstrzyga — **NIE zgaduj**. Zrealizuj wszystkie pewne elementy, a otwarte pytania (kontekst + konkretne opcje A/B) zapisz w pliku **`QUESTIONS_V15.md`** w katalogu głównym repozytorium i wypchnij go razem z commitem. Jeśli wszystko było jasne, nie twórz tego pliku.

## 0. Kluczowe Decyzje Architektoniczne (Już Podjęte)

| Obszar | Podjęta decyzja (obowiązująca) | Powód |
|---|---|---|
| **Budżet czasu decyzji** | Podnieś budżet obliczeń w `DecisionLock` (liczonych **raz** na sytuację) do **`time_budget_ms=400.0`** na Flopie/Turnie i **pełnej dokładnej enumeracji (exact)** na Riverze (limit twardy `< 1.5 s`, bezpiecznie poniżej limitu `3 s` użytkownika). | Intel Core Ultra 5 225H (14 rdzeni, 4.9 GHz, AVX2) policzy to błyskawicznie, a wyższa próbka + exact River radykalnie poprawią trafność EV. |
| **Twarde reguły bezpieczeństwa** | (1) **Absolutny zakaz `FOLD` przy `to_call == 0`** (gdy dostępny jest `CHECK`, usuń `FOLD` z kandydatów!). (2) **Usuń** ślepy `MDA Iso-Shove +0.10 BB` i `Timing Tell: fast check <500ms` z `strategy/exploit.py`. | Eliminuje natychmiast dwa najdroższe błędy z sesji live (`ALL_IN 14.5 BB z Q8s` i `FOLD z J5o` przy darmowym checku). |
| **Postflop Range-vs-Range** | Nowy moduł `engine/range_engine.py` (`RangeTracker` + `narrow_range_by_action`): zamiast liczyć equity przeciw `random hand`, utrzymuje zważony zakres rywala z akcji preflop i zawęża go po każdej akcji postflop (`check`, `1 BB bet/donk`, `bet 50%+`, `raise/check-raise`). | Pierwszy prawdziwy silnik postflop grający przeciwko zakresowi rywala, a nie losowym kartom. |
| **ICM od mnożnika `5x`** | Nowy lekki moduł `strategy/icm.py` (Malmuth-Harville dla wypłat 1. i 2. miejsca, np. 70%/30% lub 75%/25% gdy `prize_pool >= 5 * buy_in`). W `2x`/`3x` czyste cEV; od `5x` w 3-max aplikuje czynnik Bubble Factor na granicznych all-inach. | Dopasowane do struktury Stake JAQKPOT!, gdzie od `5x` zarabia też 2. miejsce. |
| **Proste sizingi + bliska alternatywa** | Proste sizingi w wielokrotnościach BB (`1 BB`, `2 BB`, `~50% pot` skwantyzowane do BB, `ALL-IN`). Gdy 2. najlepsza akcja ma `EV >= best_ev - 0.05 BB`, zapisz ją w opcjonalnych polach `Decision.alt_action` / `alt_ev_bb` i pokaż dyskretnie na HUD obok głównej decyzji. | Szybkie klikanie na zegarze 10 s + widoczność bliskich spotów bez migotania HUD. |
| **Naprawa 1-klatkowego glitcha `Ts` i `prize0`** | W `state/tracker.py`: **3-klatkowy debounce** na zmianę kart Hero + **zakaz `NEW_HAND` ze zmiany kart, gdy na stole leży już board (`len(board_cards) >= 3`)**. W `finalize_game`: nie nadpisuj `prize_pool > 0` zerem. | Usuwa rozcinanie rozdań `55`/`44`/`KQ` na 3 kawałki przez 1-klatkowy odczyt `Ts` oraz `prize0` w nazwach plików. |
| **Zbiorczy eksport do 1 pliku `.md`** | Nowy skrypt `tools/export_games_md.py` łączący wszystkie gry z `hand_histories/` w jeden raport `hand_histories/ALL_GAMES_REPORT.md` ze zbiorczą tabelą podsumowania na górze. | Jedna komenda w PowerShellu daje gotowy plik do przesłania do analizy zbiorczej. |

## 1. Krok 1: Naprawy Krytyczne Trackera i Zapisu (`state/tracker.py`, `state/hand_history.py`, `main.py`)

1. **3-klatkowy debounce na `hero_cards_changed` i ochrona postflopu (`state/tracker.py`):**
   * Dodaj licznik `self._pending_hero_cards: list[str] | None = None` i `self._pending_hero_frames: int = 0` oraz `self._hero_cards_confirm_frames: int = 3` (w testach jednostkowych z 1-klatkowymi skokami zachowaj parametr `hero_cards_confirm_frames: int = 3` z możliwością ustawienia `1`, a dla prawdziwego `NEW_HAND` wyzwalanego przez zmianę dealera `dealer_changed` lub `street_reset` nie wymagaj debounce kart!).
   * Gdy `state.hero_cards != prev_known_hero`:
     * Jeśli `len(state.board_cards) >= 3` i nie zmienił się dealer oraz nie nastąpił `street_reset` → **NIGDY** nie wyzwalaj `NEW_HAND` (to zawsze 1-klatkowy błąd OCR na postflopie, np. `5h Ts` zamiast `5h 5d`!). Zignoruj ten błędny odczyt kart Hero.
     * Na preflopie (`len(state.board_cards) == 0`): wymagaj, by identyczne nowe `state.hero_cards` powtórzyły się w `self._hero_cards_confirm_frames` kolejnych klatkach `VALID` (domyślnie `3`), zanim `hero_cards_changed` wyzwoli `NEW_HAND`.
2. **3-klatkowe potwierdzenie `OUT` dla Hero (`seat_id == 0`):**
   * Nie ustawiaj `eliminated = True` (`OUT`) dla `seat_id == 0` po pojedynczej klatce z `stack is None` (np. gdy okienko/animacja na 1 klatkę zasłoniła stack `35` w `game_224114`). Wymagaj 3 kolejnych klatek `VALID` z `stack is None` i `not is_active`.
3. **Zachowanie `prize_pool > 0` (`state/hand_history.py`):**
   * W `record_hand` i `finalize_game`: jeśli przekazane `prize_pool` wynosi `0` lub `None`, a gra ma już zapisane `game["prize_pool"] > 0`, **NIE nadpisuj go zerem**! W nazwie pliku używaj `game["prize_pool"]` (koniec z `prize0.md` dla turniejów `$4` i `$6`).

## 2. Krok 2: Twarde Reguły Bezpieczeństwa, Pełny Preflop 0–15 BB i ICM od `5x` (`engine/preflop_nash.py`, `data/preflop_tables/nash_3max.json`, `strategy/exploit.py`, `strategy/icm.py`, `strategy/decision_maker.py`)

### 2.1. Usunięcie błędów ze `strategy/exploit.py` i `strategy/decision_maker.py`
1. **Absolutny zakaz `FOLD` przy darmowym `CHECK` (`strategy/decision_maker.py` + `strategy/simplifier.py`):**
   * Gdy `to_call == 0` (tj. `max_opp_bet <= hero_bet`) lub `"CHECK"` jest wśród `available_actions` bez otwartego zakładu do sprawdzenia: usuń `"FOLD"` ze słownika kandydatów `candidate_evs` przed wyborem akcji. Bot **NIGDY** nie może zasugerować `FOLD`, gdy może za darmo kliknąć `CHECK`.
2. **Czyszczenie `strategy/exploit.py`:**
   * **USUŃ** bezwarunkowy bonus `evs["ALL_IN"] += 0.10` dla `BB_ISO_VS_LIMP` (to on kazał wsuwać `Q8s` za 14.5 BB!).
   * **USUŃ** regułę `Timing Tell: fast check <500ms` (szum z klatek i auto-checków).
   * Zostaw wyłącznie czyste, ograniczone korekty oparte o **realną akcję i sizing** (np. mały `1 BB` donk-bet na flopie traktowany jako słaby/capped zakres rywala; duży bet/raise na turnie/riverze obsługiwany przez `RangeTracker` w Kroku 3).

### 2.2. Kompletny, solverowy Preflop 0–15 BB (`data/preflop_tables/nash_3max.json` + `engine/preflop_nash.py`)
Zastąp obecne uproszczone tabele pełną, spójną strukturą zakresów 3-max + Heads-Up dla 6 progów efektywnego stacka (`15`, `12`, `10`, `8`, `6`, `4` BB) dla każdego ze spotów:
* **`BTN_OPEN`**:
  * `12–15 BB`: otwarcia `MIN_RAISE` (2 BB) ~40–45% rąk (pary, broadwaye, suited A/K/Q/J/connectors), bez bezsensownych shove'ów 15 BB ze średnimi rękami;
  * `8–11 BB`: mix `MIN_RAISE` (premium + grywalne) i `ALL_IN` (małe pary `22–66`, słabe `Ax`, `K9o–KJo` blokujące calle);
  * `<= 7 BB`: czysty Nash Push/Fold (~45–60% shove).
* **`SB_BVB` (SB vs BB po foldzie BTN)** oraz **`HU_SB`**:
  * `11–15 BB`: 3-way podział na `MIN_RAISE` (silny spolaryzowany zakres), `LIMP/CALL` (szeroki zakres średnich i spekulatywnych rąk) i `ALL_IN` (tylko krótkie stacki / ręce słabo grające postflop przy `<= 10 BB`), `FOLD` tylko najgorsze ~15–20% offsuit śmieci (`32o`, `72o`, `83o`, `93o`...).
  * `<= 8 BB`: dokładne progi Nash Push/Fold (`HoldemResources HUNE`).
* **`BB_VS_LIMP` (BB po limpie SB/BTN)**:
  * **NIGDY `FOLD`!** Zawsze co najmniej `CHECK`.
  * `11–15 BB`: **`MIN_RAISE` (iso-raise 2–3 BB)** z wartościowymi rękami (`77+`, `A9o+`, `A7s+`, `KJo+`, `K9s+`, `QTs+`) + spolaryzowane blefy; **`ALL_IN` TYLKO** przy `<= 9 BB` (lub ręce `22–66`, `A2o–A8o` przy `<= 10 BB`), a ręce typu `Q8s` przy `14.5 BB` grają **`MIN_RAISE` lub `CHECK`**, NIGDY All-In!
* **`BB_VS_MR` (obrona BB vs min-raise 2 BB)**, **`BB_VS_SHOVE`** i **`SB_VS_BTN`**:
  * Szeroka, poprawna matematycznie obrona BB vs min-raise (pot odds ~25% — defend ~55–65% rąk przy `10–15 BB`, 3-bet shove z `77+`, `ATs+`, `AJo+`, `KQs` i wybranymi blokerami), dokładne zakresy calla vs shove według Nasha (`HUNE`).

### 2.3. Moduł ICM od mnożnika `5x` (`strategy/icm.py`)
* Zaimplementuj `calculate_icm_equities(stacks: list[int], payouts: list[float]) -> list[float]` (Malmuth-Harville dla 3 graczy) oraz `compute_bubble_factor(hero_stack, opp_stack, third_stack, payouts) -> float`.
* Aktywuj automatycznie, gdy `num_alive == 3` oraz `prize_pool >= 5 * buy_in` (domyślny podział dla 5x+: `[0.75, 0.25, 0.0]` lub konfigurowalny w `config.json` pod `icm.payout_splits`).
* W 3-max przy `>= 5x` zmniejszaj EV granicznych sprawdzeń `ALL_IN` / `CALL` przez wymagane wyższe equity (`req_eq_icm` z Bubble Factor) — dzięki temu na dużych mnożnikach system nie ryzykuje bez sensu wyeliminowania jako 3., gdy inny gracz jest short-stackiem.

## 3. Krok 3: Nowy Silnik Postflop `Range-vs-Range` (`engine/range_engine.py`, `engine/monte_carlo.py`, `main.py`)

Zamiast liczyć equity przeciw losowej ręce (`random hand`), wprowadź lekki, deterministyczny silnik zakresów działający w `< 400 ms` (budżet do `1.5 s`, limit użytkownika `3 s`):

1. **Nowy moduł `engine/range_engine.py`:**
   * **`get_preflop_villain_range(position: str, preflop_action: str, effective_bb: float) -> dict[tuple[str, str], float]`**: zwraca zważony zakres startowy rywala (spośród 1326 kombinacji, po odjęciu kart Hero i boardu) dla: `OPEN_RAISE` (~42%), `LIMP` (~55%), `CALL_OPEN` (~55%), `3BET_OR_SHOVE` (~14%).
   * **`narrow_range_by_postflop_action(villain_range, board_cards, action_type: str, bet_to_pot: float, street: str) -> dict[tuple[str, str], float]`**:
     * Klasyfikuje każdą kombinację w zakresie rywala na aktualnym boardzie w 5 czytelnych koszyków siły (korzystając z szybkiej oceny `phevaluator` + prostego detektora drawów koloru/strita): `MONSTER` (2 pary+), `STRONG` (top pair / overpair), `MEDIUM` (druga/trzecia para / A-high), `DRAW` (FD / OESD), `AIR`.
     * Aktualizuje wagi kombinacji według deterministycznej macierzy przejścia opartej o **dane populacyjne mikrostawk (MDA)**:
       - `CHECK` → zmniejsza wagi `MONSTER`/`STRONG`, zwiększa `MEDIUM`/`AIR` (capped range).
       - `SMALL_BET` (`<= 0.35 * pot` lub `1 BB` donk-bet) → szeroki, merged zakres (`STRONG`, `MEDIUM`, `DRAW`, część `AIR`).
       - `MEDIUM_BET` (`0.35–0.70 * pot`) → głównie `MONSTER`, `STRONG`, `DRAW` + umiarkowane blefy.
       - `BIG_BET_OR_RAISE` (`> 0.70 * pot` lub `RAISE`/`CHECK_RAISE`, szczególnie na Turnie/Riverze) → bardzo wysokie wagi dla `MONSTER` i `STRONG`, silnie zredukowane `AIR` (uwzględnia mocne niedoblefowywanie na mikrostawkach!).
   * **`compute_range_vs_hand_equity(hero_cards, board_cards, villain_range, time_budget_ms=400.0) -> float`**:
     * **Na Riverze (`len(board_cards) == 5`)**: **exact enumeration** po wszystkich kombinacjach w `villain_range` (0% błędu losowego, czas `< 5 ms`!).
     * **Na Turnie (`len(board_cards) == 4`)**: ważone próbkowanie / dokładna enumeracja po losowanych/wszystkich 44 kartach rivera (deterministyczny seed!).
     * **Na Flopie (`len(board_cards) == 3`)**: ważone próbkowanie Monte Carlo z `villain_range` (budżet `400 ms`, deterministyczny seed).
2. **Proste sizingi postflop w `main.py`:**
   * Kandydaci przy braku betu: `CHECK`, `BET_SMALL` (`1 BB` lub `~33% pot` skwantyzowane do BB), `BET_MED` (`~50% pot` skwantyzowane do BB — tylko gdy różni się od `BET_SMALL` i `< 65%` eff stack), `ALL_IN`.
   * Kandydaci przeciwko betowi: `FOLD`, `CALL`, `ALL_IN` (plus `RAISE` w wielokrotności BB, gdy efektywny stack jest głęboki).
   * Fold equity w modelu EV nie jest już stałą liczbą `0.25`, lecz wynika ze struktury zawężonego zakresu rywala (jaki % jego `AIR` + słabego `MEDIUM` spasuje wobec danego sizingu i tekstury boardu: suchy vs mokry!).

## 4. Krok 4: Pokazywanie Bliskiej Alternatywy na HUD (`core/contracts.py`, `strategy/decision_maker.py`, `ui/hud.py`)

1. W `core/contracts.py:Decision` dodaj opcjonalne pola (z domyślnym `None`, 100% kompatybilności wstecznej):
   ```python
   alt_action: str | None = None
   alt_ev_bb: float | None = None
   alt_sizing_bb: int | None = None
   alt_sizing_chips: int | None = None
   ```
2. W `strategy/decision_maker.py` i `main.py`:
   * Jeśli 2. najlepsza legalna akcja ma `alt_ev_bb >= best_ev_bb - 0.05` (różnica `< 0.05 BB` i inna akcja niż główna): wypełnij `alt_action`, `alt_ev_bb`, `alt_sizing_bb`, `alt_sizing_chips`.
3. W `ui/hud.py` (`on_decision_updated`):
   * Jeśli `decision.alt_action` jest obecne, wyświetl pod główną odznaką subtelną, czytelną linijkę:
     `Alt: BET 1 BB (20) (+1.04 BB)` (np. `font-size: 11px; color: #94a3b8;`).

## 5. Krok 5: Narzędzia Pomocnicze — Zbiorczy Eksport Gier i Importer `GTOpen` (`tools/export_games_md.py`, `tools/import_gtopen.py`)

1. **`tools/export_games_md.py`:**
   * CLI: `python tools/export_games_md.py` (domyślnie czyta `hand_histories/*.md`, pomija poprzedni `ALL_GAMES_REPORT.md`, zapisuje `hand_histories/ALL_GAMES_REPORT.md`).
   * Na samej górze pliku generuje zwięzłą **Tabelę Zbiorczą Sesji**: łączna liczba gier, łączna liczba rozdań, rozkład pul nagród, wykryci zwycięzcy stołów oraz łączna liczba decyzji HUD — a poniżej pełną treść wszystkich gier chronologicznie.
2. **`tools/import_gtopen.py` (gotowy most pod offline `GTOpen`):**
   * Lekki konwerter potrafiący wczytać wyeksportowane z `GTOpen` zakresy JSON/tekstowe (format `AA,KQs:0.5,A5s-A2s`) i zapisać je w formacie `data/preflop_tables/nash_3max.json` oraz `data/flop_db/` (z walidacją schematu).

## 6. Krok 6: Testy Jednostkowe i Weryfikacja (Obowiązkowe)

1. **Nowe testy jednostkowe:**
   * `tests/test_strategy.py`:
     * `test_never_fold_when_free_check_available` (BB po limpie `to_call == 0` z `Jh 5c` NIGDY nie zwraca `FOLD`).
     * `test_bb_vs_limp_deep_14bb_q8s_not_all_in` (`Qh 8h` przy `14.5 BB` na BB po limpie nie zwraca `ALL_IN`).
     * `test_icm_bubble_factor_activates_at_5x_and_above` (w `2x/3x` brak korekty ICM, w `5x+` Bubble Factor > 1.0).
     * `test_decision_populates_alt_action_within_0_05_bb` (gdy 2. akcja jest w `0.05 BB`, wypełnia `alt_action` i `alt_ev_bb`).
   * `tests/test_engine.py`:
     * `test_range_narrowing_big_river_bet_reduces_air_and_lowers_bluffcatcher_equity` (weryfikuje, że equity słabej pary przeciw dużemu betowi na riverze jest istotnie niższe niż przeciw losowej ręce; weryfikuje exact enumeration na Riverze).
   * `tests/test_state.py`:
     * `test_tracker_3_frame_debounce_ignores_single_frame_ts_glitch_on_postflop` (`5h 5d -> 5h Ts -> 5h 5d` NIE tworzy nowych rozdań).
     * `test_hand_history_preserves_nonzero_prize_pool_on_finalize` (nie nadpisuje `$4` zerem `prize0`).
     * `test_export_games_md_combines_multiple_games` (test `tools/export_games_md.py` w `tmp_path`).
   * `tests/test_ui_and_main.py`:
     * `test_hud_renders_alt_action_when_present`.
2. **Weryfikacja końcowa:**
   * Uruchom pełny **`pytest -v tests/`** — 100% testów na zielono.
   * Zweryfikuj brak regresji na nagraniach w `nagrania testowe/` (100% `VALID` przez `RIM`).

## 7. Obowiązkowa Synchronizacja na GitHub (Po Zakończeniu Prac)

1. Jeśli pojawiły się jakiekolwiek niejasności lub otwarte pytania — zapisz je w **`QUESTIONS_V15.md`** w katalogu głównym repozytorium (nie zgaduj!). Jeśli wszystko było jasne, nie twórz tego pliku.
2. Dopisz szczegółowy raport V15 na samej górze **`PROGRESS_LOG.md`**.
3. Wykonaj `git add -A`, `git commit -m "V15: Range-vs-Range postflop engine, full 0-15BB preflop + 5x ICM, alt action on HUD, Ts debounce & games exporter"`, `git push origin main`.
4. W odpowiedzi końcowej napisz krótkie potwierdzenie (z informacją, czy utworzono `QUESTIONS_V15.md`) i podaj **WYŁĄCZNIE** link do repozytorium:
   `https://github.com/leonkazimierzzielinski-spec/poker-genius`
