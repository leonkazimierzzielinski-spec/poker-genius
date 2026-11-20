# Plan Finalnej Naprawy i Usprawnień — Wersja V6 (`poker_assistant`)

Dokument zamyka wszystkie **6 konkretnych, udowodnionych błędów i braków** ujawnionych w audycie `audit_pack_v5.zip` (1 655 klatek z 5 nagrań), a dodatkowo wprowadza **tryb podglądu w przód (`[PLAN]`)**, dzięki któremu HUD pokazuje rekomendację zanim jeszcze zapali się Twój timer.

---

## 1. Co udowodnił audyt V5 (6 celów tej tury)

| Cel | Problem udowodniony w `audit_pack_v5.zip` | Docelowa naprawa |
|---|---|---|
| **1. Gracz na All-In (`B2`)** | Aż **147 klatek** (w tym tura Hero na `211257` f3880–3890) odrzucanych błędem `Missing stack reading`, bo Stake wyświetla tekst `"All-In"` zamiast `0`. | W `VisionPipeline`: jeśli `stack is None` i `current_bet > 0` → `stack = 0, status_text = "ALL_IN"`. W `StateValidator`: akceptuj `stack is None`, jeśli suma niepustych stacków + `pot` == `900`. |
| **2. BTN vs All-In / Raise (`B6`)** | Na klatkach `3863` / `3880` (`211257`) Hero siedzi na BTN po limpie (`bet 20`), rywal S1 wchodzi All-In (`bet 166`), a `determine_preflop_spot` nadal zwraca `BTN_OPEN`! | Jeśli `hero_seat == btn_seat` i `sb_bet > bb_val` lub `bb_bet > bb_val` (lub rywal ma `ALL_IN`), zwróć spot obrony przed shove/raisem (`BB_VS_SB_SHOVE` / `BB_VS_SB_RAISE`), a `BTN_OPEN` tylko gdy nikt nie przebił. |
| **3. Realistyczne EV Postflop (`B5`)** | W 21 klatkach postflop silnik krzyczał `ALL_IN` ze średnim EV `+10.67 BB` (max `+21.27 BB`), bo `calculate_ev_bb` przyjmował stałe `fold_equity=0.40` przeciw losowemu zakresowi bez uwzględnienia, że przy callu rywal ma silniejsze ręce. | Realistyczna kalibracja modelu postflop w `main.py`: (a) przy `shove_ev` i `bet_ev` użyj realistycznego, skalowanego `fold_equity` zależnego od wielkości zakładu i SPR oraz skoryguj equity po callu (`call_equity = max(0.0, equity - penalty)`), (b) dla `facing_bet` nie dawaj `fold_equity=0.40` na 3-bet shove przeciwko betowi rywala (max `0.15–0.20`). |
| **4. Odczyt kart na skali `1.28x` i czyste szablony (`B1`, `B3`)** | Na `211257` f3643 wycinki `hero_card_1.png` (`Jc`) i `hero_card_2.png` (`4d`) są idealnie ostre, ale: (a) próg obniżony do `0.70` wpuszczał fałszywe `Ac (0.71)` i `8d (0.76)`, (b) szablon `Jc.png` ma uciętą lewą krawędź, a `2d.png` / `Kh.png` mają stary rozmiar `32x50`, (c) karty Hero są lekko pochylone względem boardu. | (a) Napraw ucięty szablon `Jc.png` (i ujednolić `2d.png`, `Kh.png`, `4c.png`, `Kc.png` do standardu `50x75` lub dodaj czyste warianty `Jc_hero.png`, `4d_hero.png` z `211257` f3643), (b) podnieś minimalny próg dla skalowanych stołów z `0.70` na `0.82` (żeby nigdy nie przepuszczać fałszywek `0.71`), (c) sprawdź dopasowanie kątowe/skalowe w `hero_card_1/2` na `211257` f3643. |
| **5. Szybkość na innych skalach (`752 ms` → `< 150 ms`) + stabilne `table_id` (`B9`)** | Na `211257` średnia latencja wynosiła aż **752 ms (P95 1298 ms)**, bo `find_all_anchors` na każdej klatce od nowa szukało w `1.0x`, nie znajdowało i skanowało kolejne skale. Dodatkowo na `2 gry na raz` nadal pojawiło się 28 błędów `Blinds decreased`. | (a) Cache ostatnio wykrytej skali kotwicy (`_last_anchor_scale`) w `VisionPipeline` / `main.py` — jako pierwszą sprawdzaj ostatnią trafioną skalę, co zbije latencję na `211257` z `752 ms` do `< 150 ms`! (b) W `main.py` wywołuj `validator.reset_table(resolved_tid)` zawsze, gdy `resolve_table_id` nadpisze stary slot nowym turniejem (eksmisja LRU) lub gdy w tym samym `table_id` jednocześnie zmienił się `prize_pool` albo wszystkie 3 stacki wróciły do ~300 (`Blinds 10/20` nowego turnieju). |
| **6. Tryb Podglądu w Przód (`[PLAN]`) zamiast `WAIT`** | Poza turą Hero HUD pokazuje `WAIT`, mimo że gracz ma już 2 karty i widzi ruchy rywali (np. All-In S1 na f3863). | Gdy `is_valid == True`, `len(hero_cards) == 2`, ale `is_hero_turn == False`, wylicz wirtualne `available_actions` z zakładów na stole i wyświetl w HUD rekomendację jako **`[PLAN] <AKCJA>`** (lekko przygaszony styl, wyraźna etykieta `PLAN — czekam na turę`). |

---

## 2. Szczegółowa Specyfikacja Zmian (Krok po Kroku)

### Krok 1: Obsługa graczy All-In (`vision/pipeline.py` + `state/validator.py`)

1. **W `vision/pipeline.py` (`process_frame`):**
   - W pętli po `seat_id in (0, 1, 2)`: jeśli `stack is None and current_bet > 0`, ustaw:
     ```python
     stack = 0
     status_text = "ALL_IN"
     is_active = True
     ```
2. **W `state/validator.py` (`validate`):**
   - Jeśli co najmniej 1 gracz ma `stack is None`:
     - Policz `non_none_stacks = [p.stack for p in state.players.values() if p.stack is not None]`.
     - Policz `present_players = sum(1 for p in state.players.values() if (p.stack is not None or p.current_bet > 0))`.
     - Policz `sum_with_bets = state.pot + sum((p.stack or 0) + p.current_bet for p in state.players.values())` oraz `sum_pot_stacks = state.pot + sum((p.stack or 0) for p in state.players.values())`.
     - **Reguła akceptacji:** Jeśli `present_players >= 2` (lub `len(non_none_stacks) >= 1` przy all-in 2 graczy i `state.pot == self.total_chips`) ORAZ `(sum_with_bets == self.total_chips or sum_pot_stacks == self.total_chips)` — **NIE** dodawaj błędu `"Missing stack reading"`.
     - W przeciwnym razie (gdy brakuje stacka i suma nie domyka się do 900) nadal zgłaszaj `"Missing stack reading"` (zachowuje pełną zgodność z testami `test_validator_missing_stack_and_negative_chips` i `test_validator_heads_up_valid_sum_900`!).

---

### Krok 2: Naprawa `determine_preflop_spot` dla Hero na BTN przeciwko All-In / Raise (`main.py`)

W `main.py` w funkcji `determine_preflop_spot(state)`:
- W gałęzi `if hero_seat == btn_seat:` (zarówno dla 3-max, jak i Heads-Up!):
  - Sprawdź rywali (`sb_player`, `bb_player` — lub jedynego aktywnego rywala w Heads-Up):
    - Jeśli którykolwiek rywal zagrał shove (`_is_preflop_shove(opp, bb_val)`): zwróć `"BB_VS_SB_SHOVE"` (albo dedykowany spot obrony vs shove, który istnieje w `nash_3max.json`).
    - Jeśli którykolwiek rywal zagrał raise (`opp_bet > bb_val` i nie jest to shove): zwróć `"BB_VS_SB_RAISE"`.
    - Dopiero jeśli żaden rywal nie podbił ponad `bb_val`, zwróć `"BTN_OPEN"` (w 3-max) lub `"SB_OPEN"` (w Heads-Up).
- **Ważne dla `evaluate_candidates`:** Dla spotów `*_RAISE` oraz przy `BB_VS_SB_SHOVE`, upewnij się, że `effective_bb` uwzględnia graczy ze `stack == 0, current_bet > 0` (All-In) jako aktywnych rywali z `total = current_bet` (np. na klatce `3880` S1 ma `stack=0, bet=166` -> `total = 166 = 8.3 BB`, a nie pomijany jako nieaktywny!).

---

### Krok 3: Realistyczna kalibracja EV Postflop (`main.py`)

W `main.py` w `evaluate_candidates` (gałąź `FLOP`, `TURN`, `RIVER`, fallback Monte Carlo):
- Dotychczasowy kod liczył `shove_ev` z `fold_equity=0.40` i surowym `equity` przeciwko losowemu 100% zakresowi rywala, przez co prawie każda para/draw krzyczała `ALL_IN` z `+10 BB`.
- Wprowadź realistyczny model konserwatywny:
  1. **Korekta equity przy sprawdzeniu (calling range penalty):** Rywal sprawdzający duży zakład/all-in ma silniejszy zakres niż losowe 2 karty:
     - Dla `BET_30`: `bet_call_equity = max(0.05, equity - 0.06)`, `bet_fe = 0.25`.
     - Dla `ALL_IN` (gdy nie mierzymy się z betem): `shove_call_equity = max(0.05, equity - 0.14)`, a `shove_fe` spada przy dużym overbecie: `spr = stack_bb / max(1.0, pot_bb)`; `shove_fe = 0.30 if spr <= 1.5 else (0.22 if spr <= 3.0 else 0.15)`.
     - Dla `ALL_IN` jako 3-bet/raise przeciwko betowi rywala (`facing_bet=True`): `shove_call_equity = max(0.05, equity - 0.16)`, `shove_fe = 0.18` (rywal już zabetował, więc folduje znacznie rzadziej niż 40%).
     - Dla `CALL` (`facing_bet=True`): `call_equity = max(0.05, equity - 0.08)` (rywal betujący ma mocniejszy zakres niż losowe karty).
  2. Obliczaj EV za pomocą `mc_calc.calculate_ev_bb(...)` z tymi skorygowanymi parametrami, dzięki czemu:
     - Z top parą / dwiema parami na niskim SPR nadal wygrywa `BET_30` lub `ALL_IN`,
     - Z marginalną parą / drawem przy dużym SPR (np. `13 BB` w puli `4 BB`) system wybiera rozsądne `BET_30`, `CALL` albo `CHECK`, zamiast rzucać `ALL_IN` za 13 BB o małą pulę!

---

### Krok 4: Naprawa szablonów i progu kart dla skalowanych stołów (`data/templates/cards/`, `vision/pipeline.py`)

1. **Czyszczenie wadliwych szablonów:**
   - Wytnij czysty szablon **`Jc.png`** (`50x75`) z klatki `3643` nagrania `211257` (po `_warp_to_canonical` z `INTER_AREA`) oraz sprawdź/zapisz wariant `4d_hero.png` (`50x75`) z tej samej klatki `3643` (zachowując istniejący `4d.png` dla `2 gry na raz` f2418!).
   - Sprawdź, czy na klatce `3643` (`211257`) po tej zmianie `hero_card_1` zwraca **`Jc` (> 0.90)**, a `hero_card_2` zwraca **`4d` (> 0.90)**, jednocześnie nie psując klatki `2418` (`4d Qs`) ani `224127`.
2. **Podniesienie progu bezpieczeństwa dla skalowanych stołów (`vision/pipeline.py`):**
   - Zmień w `vision/pipeline.py` linię 287: zamiast niebezpiecznego `0.70` (które przepuszczało `Ac: 0.71` i `8d: 0.76`) ustaw **`min(orig_card_thresh, 0.82)`**.
   - W `_warp_to_canonical`: gdy `tw > CW or th > CH` (zmniejszanie obrazu, jak `211257`), używaj `cv2.INTER_AREA`, a przy powiększaniu `cv2.INTER_LINEAR`.

---

### Krok 5: Cache skali kotwicy (`752 ms` → `< 150 ms`) i eliminacja `Blinds decreased` (`vision/anchor.py`, `vision/pipeline.py`, `main.py`)

1. **Cache ostatniej trafionej skali kotwicy (`vision/anchor.py` + `vision/pipeline.py` + `main.py`):**
   - W `find_all_anchors(..., preferred_scale: float | None = None)` i `find_anchor(..., preferred_scale: float | None = None)`:
     - Jeśli podano `preferred_scale` (np. `1.28`), sprawdź ją **jako pierwszą** przed listą `scales`.
     - Zapisuj ostatnio trafioną skalę w `pipeline._last_anchor_scale` i przekazuj ją w `main.py` jako `preferred_scale=pipeline._last_anchor_scale`.
     - Efekt: na nagraniu `211257` (skala `1.28x`) pierwsza klatka znajdzie `1.28`, a wszystkie kolejne trafią za **pierwszym** strzałem, zbijając średnią latencję z `752 ms` poniżej `150–200 ms`!
2. **Eliminacja fałszywych `Blinds decreased` (`vision/pipeline.py` + `main.py`):**
   - Dodaj w `VisionPipeline` atrybut `self.last_evicted_table_id: str | None = None` ustawiany wtedy, gdy `resolve_table_id` nadpisze najstarszy slot LRU nowym turniejem.
   - W `main.py`: jeśli `pipeline.last_evicted_table_id == resolved_tid`, wywołaj `validator.reset_table(resolved_tid)` oraz zresetuj `trackers.pop(resolved_tid, None)`.
   - Ponadto w `main.py`: jeśli `validator.validate(state)` zwróci **wyłącznie** błąd `"Blinds decreased..."`, a jednocześnie na stole `small_blind == 10, big_blind == 20` i suma stacków wskazuje na start nowego turnieju (wszyscy gracze mają stacki w okolicach 260–320 i inny `prize_pool` lub nowy nagłówek), zresetuj tabelę blindów w walidatorze (`validator.reset_table(resolved_tid)`) i ponów walidację.

---

### Krok 6: Tryb Podglądu w Przód (`[PLAN]`) w HUD (`strategy/decision_maker.py`, `main.py`, `ui/hud.py`)

**Zasada działania:**
- Gdy `state.is_valid == True` i `len(state.hero_cards) == 2`:
  - **Tura Hero (`is_hero_turn == True`):** Bez zmian — normalna, żywa rekomendacja (`ALL_IN`, `BET_30`, `CALL`, `CHECK`, `FOLD`) w pełnym kolorze.
  - **Oczekiwanie na turę (`is_hero_turn == False`, np. klatki `2418`, `2605`, `3863`):**
    1. W `vision/pipeline.py`: ustalaj `street` na podstawie `len(board_cards)` (`0 -> PREFLOP`, `3 -> FLOP`, `4 -> TURN`, `5 -> RIVER`) zawsze gdy `len(hero_cards) == 2` (nie nadpisuj na `WAITING_FOR_TURN` tylko dlatego, że `is_hero_turn == False`; `WAITING_FOR_TURN` zostaw tylko gdy `len(hero_cards) != 2`). *Uwaga: sprawdź, czy istniejące testy `test_vision.py` / `test_strategy.py` oczekują `WAITING_FOR_TURN` — jeśli tak, zaktualizuj w `main.py` zamiast łamać kontrakt `VisionPipeline`, albo przekaż parametr `allow_preview: bool = False` do `DecisionMaker.decide(...)`!*
    2. **Najbezpieczniejsza ścieżka (zero łamania starych testów!):**
       - Pozostaw `VisionPipeline` oraz domyślne `DecisionMaker.decide(..., allow_preview: bool = False)` w 100% kompatybilne ze wszystkimi 77 istniejącymi testami!
       - W `main.py` (`processing_loop`), gdy `state.is_valid and len(state.hero_cards) == 2 and not state.is_hero_turn`:
         - Wyznacz wirtualny `preview_street` z `len(state.board_cards)` (`PREFLOP`/`FLOP`/`TURN`/`RIVER`) oraz wirtualne `preview_actions` ze stanu zakładów (`["FOLD", "CALL", "BET"]` gdy `max_opp_bet > hero_bet`, inaczej `["CHECK", "BET"]`).
         - Wywołaj `evaluate_candidates` i `decision_maker.decide(..., allow_preview=True)` (które dla `allow_preview=True` liczy normalną decyzję, ale ustawia prefiks w `reason`, np. `"[PLAN] ..."` oraz w `Decision.action` lub osobnej fladze/formacie dla HUD).
       - W `ui/hud.py` (`on_decision_updated`): jeśli `reason.startswith("[PLAN]")`:
         - Wyświetl badge z etykietą **`PLAN: {action}`** w lekko przygaszonym odcieniu (np. ciemniejszy/przezroczysty kolor z ramką przerywaną) oraz podpisem `⏳ Podgląd w przód (czekam na turę)` — tak aby na pierwszy rzut oka odróżnić plan przed turą od aktywnej decyzji w Twojej turze.
- Gdy `len(hero_cards) != 2` lub `not state.is_valid`: HUD nadal pokazuje `WAIT`.

---

## 3. Kryteria Odbioru i Obowiązkowa Weryfikacja

Po wdrożeniu wszystkich 6 kroków agent musi uruchomić:

1. **Pełny zestaw testów `pytest -v tests/`** (w tym nowe testy jednostkowe):
   - `test_validator_all_in_stack_none_valid` (gracz na All-In ze `stack=None, bet=166` i sumą 900 -> `VALID`),
   - `test_determine_preflop_spot_btn_vs_shove` (Hero na BTN po limpie vs SB/BB All-In -> spot obrony przed shove, NIE `BTN_OPEN`),
   - `test_postflop_ev_conservative_no_blind_shove` (sprawdza, że marginalna ręka z 50% equity przy wysokim SPR nie dostaje +10 BB na `ALL_IN`),
   - `test_find_all_anchors_preferred_scale_fast_path` (sprawdza szybką ścieżkę `preferred_scale`),
   - `test_decision_maker_preview_mode` (sprawdza `allow_preview=True` vs domyślne `allow_preview=False`).
2. **Test na realnych klatkach (pełna ścieżka `main.py`):**
   - `211257` klatka **`3643`**: `Hero: [Jc, 4d]` (NIE `Ac 8d`!), `Spot: BTN_OPEN`, `Decision: FOLD` (NIE `ALL_IN`!), latencja po rozgrzewce `< 200 ms`.
   - `211257` klatka **`3863`** (poza turą Hero, S1 All-In `166`): `Status: VALID`, `S1: stack=0 (bet 166, ALL_IN)`, tryb podglądu zwraca **`[PLAN] FOLD`** (z `Jc 4d` vs All-In `166`!).
   - `211257` klatka **`3880`** (tura Hero vs S1 All-In `166`): `Status: VALID`, `Hero Turn: True`, `Spot: BB_VS_SB_SHOVE` (NIE `BTN_OPEN`!), `Decision: FOLD` (NIE `WAIT`!).
   - `2 gry na raz` klatka **`1383`** i **`1627`**: realistyczne EV postflop (brak absurdalnego `+10.74 BB` z samego ślepego shova) oraz `0` błędów `Blinds decreased` w szybkim przelocie po `2 gry na raz`.
3. Wszystkie **82+ testów `pytest -v tests/`** przechodzą w 100%, a katalog projektu jest czysty z plików roboczych.
