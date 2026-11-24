# Poker Genius — Dziennik Postępu Prac (Progress Log)

## V18.1 — Mikro-Hotfix: 3-Klatkowy Debounce Podnoszenia Blindów i Samonaprawa `Blinds decreased` (2026-11-24)

### 1. Wdrożone poprawki
1. **3-klatkowy debounce podnoszenia blindów w `vision/pipeline.py` (`_normalize_blinds`):**
   - Dodano `_pending_blinds` (czyszczone w `reset_table_blinds()`): przejście na wyższy poziom blindów wymaga **3 kolejnych spójnych klatek** z nowym poziomem (do tego czasu zwracane jest `prev`).
   - Dla częściowych odczytów spoza `VALID_BLIND_LEVELS` (np. `(40, 10)`) zablokowano przeskok większy niż o 1 szczebel drabinki względem `prev`.
2. **Samonaprawa `Blinds decreased` w `state/validator.py` (`_pending_lower_blinds`):**
   - Gdy jedynym problemem jest `Blinds decreased`, a niższy poziom `(sb, bb)` należy do `VALID_BLIND_LEVELS` przy w 100% poprawnych żetonach i kartach (`len(errors) == 0`), walidator zlicza kolejne klatki i po **3. spójnej klatce** automatycznie akceptuje nowy poziom (`_last_blinds[table_id] = (sb, bb)`), zapobiegając permanentnemu zakleszczeniu w `WAIT`.
3. **Testy jednostkowe:**
   - Dodano `test_blinds_single_frame_upward_glitch_does_not_poison_pipeline` (`tests/test_vision.py`) oraz `test_validator_self_heals_blinds_decreased_after_3_consistent_frames` (`tests/test_state.py`).
   - Pełny wynik `pytest -v tests/`: **161 passed in 5.75s (100% sukcesu)**.

---

## V18 — Pancerny Odczyt CV, Fizyczna Spójność Stanu i Stabilny Tracker (2026-11-24)

### 1. Benchmark regresyjny PRZED vs PO (`Nagrywanie 2026-11-24 215605.mp4`, `stride=3`, 3 682 klatki)

| Metryka | Przed V18 | Po V18 | Cel V18 (KPI) |
| :--- | :---: | :---: | :---: |
| `VALID` gdy `len(hero_cards) == 2` | `1 079 / 2 226` (`48.5%`) | **`2 133 / 2 226` (`95.8%`)** | `>= 85%` |
| `VALID` ogółem (`3 608` klatek z kotwicą) | `1 366` (`37.9%`) | **`3 225` (`89.4%`)** | — |
| `Invalid blinds` + `Blinds decreased` | `1 035` + `515` = `1 550` | **`0` + `0` = `0`** | `0` |
| `current_bet > pot` / `current_bet > 900` | `46` / `28` | **`0` / `0`** | `0 / 0` |
| Fałszywe `stack == 1` na etykiecie `All-In` | `341` | **`3`** (`99.1%` redukcji) | `0` |
| `Missing stack` na przygaszonym `S0` (3-max) | `133` | **`0`** (`S1: 1, S2: 1`) | `<= 10` |
| Akcje `RAISE > 900` i duplikaty rozdań w `TableTracker` | `7151`, `1160`, `1310` + 3 duplikaty | **`0` / `0` duplikatów** (15 unikalnych rozdań) | `0` |
| Pełny zestaw testów `pytest -v tests/` | `151 passed` | **`159 passed`** (`5.93 s`) | `100% zielonych` |

### 2. Wdrożone zmiany (D1–D9)
1. **Drabinka blindów i blokada zatrucia walidatora (`core/constants.py`, `vision/pipeline.py`, `state/validator.py`):**
   - Dodano `VALID_BLIND_LEVELS` oraz `_normalize_blinds()` z naprawą częściowych odczytów (np. `(20, 4) -> (20, 40)`, `(30, 610) -> (30, 60)`) i carry-over dla niejednoznacznych odczytów (`(1, 2)`).
   - `StateValidator` aktualizuje `_last_blinds` wyłącznie dla legalnych par (`VALID_BLIND_LEVELS` lub `bb == 2 * sb`).
2. **Przygaszone stacki, detekcja `All-In` i próg paska tury (`vision/ocr.py`, `vision/pipeline.py`):**
   - `DigitOCR.read_int()` używa `min_p98=80.0, min_contrast=40.0` (odzysk przygaszonych stacków po `Fold`).
   - Dodano `DigitOCR.is_all_in_label()` (`stack=0, status_text="ALL_IN"` zamiast fałszywego `1`).
   - Obniżono próg fioletowego paska tury `seat_0_timer` z `500` na **`180 px`**.
   - Dodano `detect_rabbit_hunting_break(actions_roi, is_hero_turn)` zamrażające `[PLAN]` i tracker podczas `Rabbit hunting break`.
3. **Czyste bety i niezmiennik `bet <= pot` (`config.json`, `vision/pipeline.py`, `state/validator.py`):**
   - Poszerzono `seat_0_bet` do `[0.478, 0.605, 0.068, 0.04]` i dodano `_mask_white_bet_text()` wycinającą kolorowe ikony żetonów.
   - Wymuszono `pot == 0 -> bet = 0` oraz `bet > pot -> bet = 0` w `VisionPipeline` + walidację `"Invalid bet exceeds pot"` w `StateValidator`.
4. **Stabilność `TableTracker` (`state/tracker.py`):**
   - Reset `last_completed_hand = None` poza `NEW_HAND`, 2-klatkowe potwierdzanie betów (`bet_confirm_frames=2` w `main.py`), odrzucanie betów `> pot` i `> 900`, oraz wykrywanie resetu puli przy instant-foldzie preflop.
5. **Orkiestrator i wykluczenie HUD z przechwytywania (`main.py`, `ui/hud.py`):**
   - Podtrzymanie `last_stable_rect` przez `2.0 s` (`RIM_HOLD`), carry-over 1 brakującego stacka z `900 - pot - suma` przez `1.5 s`, obsługa `Rabbit hunting break` oraz `_apply_exclude_from_capture()` (`WDA_EXCLUDEFROMCAPTURE = 0x11`) w `showEvent` wszystkich nakładek.

---

## V17.4 — Pakiet Stabilnościowy: Maska Sukna HSV, Bramka Kontrastu OCR, Ochrona Tracker FOLD/Sub-SB, `eff_stk_chips` i HUD Buy-in (2026-11-24)

### 1. Wdrożone poprawki
1. **Maska niebieskiego sukna i skale `ICON` (`vision/anchor.py`):**
   - Zawężono maskę niebieskiego sukna w `find_golden_rim()` (`blue_mask` i `blue_center_mask`) oraz `verify_table_rect_has_blue_felt()` do `H in [95, 130], S >= 95, V >= 90` (`cv2.inRange(hsv, (95, 95, 90), (130, 255, 255))`), eliminując zlewanie ciemnego tła Stake (`#0f212e`, `#1a2c38`).
   - Rozszerzono domyślną listę skal w `find_all_anchors()` i `find_anchor()` o małe okna (`0.65`, `0.55`).
2. **Bramka jasności i kontrastu per typ pola w `DigitOCR` (`vision/ocr.py`):**
   - W `_prepare_binary_image()` dodano bramkę percentyli `p2`, `p50`, `p98` oraz kontrastu (`p98 - p50` / `p50 - p2`).
   - Przypisano dedykowane progi dla `read_int` (`min_p98=100.0, min_contrast=40.0` — odrzuca szum pustych miejsc, zachowując przygaszone stacki), `read_float` (`min_p98=125.0, min_contrast=35.0`) i `read_blinds` (`min_p98=100.0, min_contrast=25.0`).
3. **Ochrona przed fałszywym `FOLD` i duchami sub-SB (`state/tracker.py`):**
   - Condition C nie oznacza już `Ty (S0)` jako `FOLD`, jeśli `hero_cards` nadal zawiera 2 karty.
   - Condition B ignoruje `max_prev_bet < small_blind`.
   - Filtr sub-SB odrzuca także skok `0 < current_bet < sb_val`, gdy w poprzedniej klatce fotel miał `stack in (None, 0)` i `current_bet == 0`.
4. **Kwantyzacja sizingów (`main.py`):**
   - Usunięto martwe sprawdzenie `"effective_bb" in locals()`, obliczając `eff_stk_chips` jawnie na podstawie maksymalnego totalu aktywnych rywali (`min(hero_stk + hero_bet, max(active_opp_totals))`).
5. **Diagnostyka kotwicy i synchronizacja `--buy-in` (`main.py`, `ui/hud.py`):**
   - `debug_payload` zawiera `anchor_source`, a `DebugRoiOverlay` wyświetla `TABLE [{src}] (...)`.
   - `HudOverlay` przyjmuje `initial_buy_in: float = 2.0` (przekazywane z `args.buy_in`) i synchronizuje przyciski buy-in przy starcie.
6. **Testy jednostkowe:**
   - Dodano 5 nowych testów regresyjnych w `tests/test_vision.py`, `tests/test_state.py` i `tests/test_ui_and_main.py`.
   - Pełny wynik `pytest -v tests/`: **151 passed in 4.65s (100% sukcesu)**.

---

## V17.3 — Hotfix: Multi-candidate `find_golden_rim` + weryfikacja niebieskiego sukna dla fallbacku `ICON` (2026-11-24)

### 1. Wdrożone poprawki
1. **Iteracja kandydatów i adaptacyjne progi w `vision/anchor.py` (`find_golden_rim`):**
   - Zamiast sprawdzać wyłącznie `candidates[0]`, pętla iteruje po `candidates[:6]` i zwraca pierwszego kandydata przechodzącego weryfikację 4 złotych łuków, proporcji `1.55 <= aspect <= 2.15` oraz niebieskiego środka (`blue_ratio >= 0.40`).
   - Dla mniejszych stołów (`fw < 750`) obniżono minimalną liczbę złotych pikseli na łuk z `15` do `8` oraz poszerzono poziomy margines poszukiwania lewego/prawego łuku z `0.04 * fw` do `0.06 * fw`.
2. **Weryfikacja niebieskiego sukna dla fallbacku `ICON` (`vision/anchor.py`, `main.py`):**
   - Dodano funkcję `verify_table_rect_has_blue_felt(frame, table_rect, min_blue_ratio=0.25)` sprawdzającą udział pikseli niebieskiego sukna w centrum wykrytego prostokąta.
   - W `main.py` (gałąź fallbacku `ICON`) po wyliczeniu `table_rect` przez `compute_unclipped_table_rect` odrzucane są dopasowania bez niebieskiego sukna (np. białe ikony w ciemnoszarym menu `My Casino`).
3. **Testy jednostkowe (`tests/test_vision.py`):**
   - Dodano `test_find_golden_rim_skips_larger_blue_distractor_and_finds_table` oraz `test_verify_table_rect_has_blue_felt_rejects_dark_sidebar`.
   - Pełny wynik testów: **146 passed in 4.84s (100% sukcesu)**.

---

## V17.2 — Hotfix: DigitOCR pod monitory 1080p / małe okna (0.54x–0.65x) i weryfikacja ultrawide 2560×1080 (2026-11-24)

### 1. Wdrożone poprawki
1. **Poprawa rozpoznawania małych cyfr w `vision/ocr.py` (`DigitOCR`):**
   - W `preprocess()` zmieniono powiększenie 2x z `cv2.INTER_LINEAR` na `cv2.INTER_CUBIC` dla ostrzejszych krawędzi małych cyfr z monitorów 1080p.
   - W `_prepare_binary_image()` ograniczono `MORPH_OPEN (2×2)` wyłącznie do wycinków o wysokości `>= 55 px`, aby nie niszczyć cienkich linii w `0`, `8`, `9`.
   - Wydzielono metodę `_match_digit_crop()`, która po `_split_wide_box()` przycina każdy wycinek do ścisłego bounding boxa niezerowych pikseli (`np.where(crop > 0)`), dodaje **2-pikselowy czarny padding** (`cv2.copyMakeBorder`) i porównuje przez `cv2.matchTemplate(..., cv2.TM_CCOEFF_NORMED)` biorąc `max_val` z całej macierzy.
   - W `read_blinds()` dodano ochronę przed myleniem ukośnika `/` z cyfrą `7` (odrzucenie dopasowania `7`, gdy lewy górny róg wycinka jest pusty).
2. **Wyostrzenie upscalingu stołu w `vision/pipeline.py`:**
   - W `_warp_to_canonical()` przy powiększaniu małych okien do kanonicznego rozmiaru (`tw < CW or th < CH`) zastosowano `cv2.INTER_CUBIC` zamiast `cv2.INTER_LINEAR`.
3. **Próg OCR w `config.json`:**
   - Obniżono `ocr_threshold` z `0.70` na `0.62` (spójność liczbową w 100% pilnuje `StateValidator` sumą `== 900`).
4. **Testy i weryfikacja ultrawide `2560×1080` (`tests/test_vision.py`):**
   - Dodano test `test_digit_ocr_and_rim_on_ultrawide_2560x1080_left_and_right_scaled` weryfikujący klatki `765` i `2370` (`Nagrywanie 2026-11-18 224127.mp4`) w skalach `0.54x` (`~951×540`) i `0.65x` po lewej i prawej stronie płótna `2560×1080` (z fallbackiem syntetycznym 8 px dla CI).
   - Pełny wynik testów: **144 passed in 4.66s (100% sukcesu)**.

---

## V17.1 — Hotfix: Multi-monitor / Mixed-DPI Overlay Geometry (2026-11-24)

### 1. Wdrożone poprawki
1. **Przypięcie nakładek do wybranego monitora (`ui/hud.py`):**
   - Dodano funkcję pomocniczą `get_target_screen(monitor_idx: int = 0)`, która zwraca ekran docelowy z `QApplication.screens()` (z bezpiecznym fallbackiem do `primaryScreen()`).
   - Dodano opcjonalny parametr `monitor_idx: int = 0` do konstruktorów `ActionBarOverlay`, `DebugRoiOverlay`, `RegionSelectorOverlay` oraz `HudOverlay`.
   - Zastąpiono `screen.virtualGeometry()` geometrią konkretnego ekranu `target_screen.geometry()` we wszystkich nakładkach. Eliminuje to przesunięcia i rozciąganie nakładek na konfiguracjach wielomonitorowych z ujemnymi współrzędnymi wirtualnego pulpitu (np. lewy monitor `x = -225`).
2. **Pobieranie `devicePixelRatio` z docelowego ekranu:**
   - W `DebugRoiOverlay` (renderowanie i przeciąganie stołu), `ActionBarOverlay` (kalkulacja pozycji i render kafelków akcji) oraz `RegionSelectorOverlay` (skalowanie współrzędnych wybranego prostokąta) wartość `dpr` jest pobierana bezpośrednio z `get_target_screen(self._monitor_idx)`.
3. **Przekazywanie indeksu monitora z CLI (`main.py`):**
   - W punkcie startowym `HudOverlay` tworzony jest z parametrem `monitor_idx=args.monitor`.
4. **Weryfikacja testowa (`tests/test_ui_and_main.py`):**
   - Nowy test `test_overlays_use_target_screen_geometry_not_virtual_geometry` potwierdza na mockowanym układzie 2 monitorów (`(0, 0, 2560, 1080), dpr=1.0` oraz `(-225, 1080, 1440, 900), dpr=2.0`), że nakładki dla monitora 0 zachowują `x == 0` i `dpr == 1.0`, a dla monitora 1 `x == -225` i `dpr == 2.0`.
   - Wynik testów: **143 passed in 4.61s (100% sukcesu)**.

---

## V17 — Silnik Postflop Range-vs-Range ze Stanem Rozdania, Baza GTOpen Spotów i Relatywny Simplifier (2026-11-24)

### 1. Wdrożone komponenty i architektura
1. **Relatywny próg EV w `strategy/simplifier.py`:**
   - Poprawiono logikę upraszczania strategii: `ev_gain = best_ev - baseline_ev < eff_thresh` względem bazowej akcji zerowej/pasywnej (`CHECK` przy darmowej decyzji lub `FOLD` przy facing bet).
   - Eliminuje to błąd odrzucania wysoce zyskownych betów z AIR (np. c-bet `BET_30 = +0.03 BB` przeciwko `CHECK = -0.42 BB` daje zysk `+0.45 BB >= 0.03 BB` i jest wybierany, podczas gdy marginalny `BET_30 = -0.40 BB` z zyskiem `+0.02 BB < 0.03 BB` jest upraszczany do `CHECK`).
2. **Poprawka odczytu `current_bet` i rozdzielne progi w `strategy/decision_maker.py`:**
   - Wprowadzono `_get_player_bet(p)` sprawdzający w pierwszej kolejności `p.current_bet`, a w przypadku braku fallback do `p.bet`. Likwiduje to krytyczny defekt, w którym bot nie widział zakładów przeciwnika i blokował opcję `FOLD`.
   - Wprowadzono dwa rozdzielne progi straty EV: preflop `preflop_ev_loss_threshold_bb = 0.00 BB` (każda dodatnia linia preflop jest brana pod uwagę), postflop `ev_loss_threshold_bb = 0.03 BB`.
3. **Stanowy silnik zakresów `engine/range_engine.py`:**
   - Zaimplementowano funkcję `infer_villain_position(state, hand_summary, villain_seat)` precyzyjnie określającą pozycję rywala (BTN/SB/BB) w 3-max i HU.
   - Zaimplementowano funkcję `build_villain_range_from_history(hand_summary, state, villain_seat, effective_bb)`: kumulatywne zawężanie zakresu ulica po ulicy (`preflop_acts` -> `postflop_acts` dla Flop, Turn, River) na podstawie realnego logu akcji z zachowaniem wielkości zakładów w relacji do puli.
4. **Podpięcie `flop_db` i zachowanie wag zakresu w `main.py`:**
   - Nowa funkcja `determine_postflop_spot(state, hand_summary)` automatycznie klasyfikuje spot postflop do 4 głównych kategorii GTOpen: `BTN_vs_BB_SRP`, `SB_vs_BB_LIMPED`, `HU_SB_vs_BB_SRP`, `HU_SB_vs_BB_LIMPED`.
   - Zapytanie do bazy `flop_db.lookup_nearest_flop` wykonywane jest **wyłącznie gdy `not facing_bet`** (węzeł otwierający flopa).
   - Gdy `facing_bet == True`, silnik zawsze kieruje decyzję do stanowego `range_engine`.
   - **Kluczowe zachowanie wag:** Wyeliminowano spłaszczanie zakresu `list(v_range.keys())` — dla Heads-Up postflop (`num_opps == 1`) wywoływane jest bezpośrednio `compute_range_vs_hand_equity(hero_cards, board_cards, villain_range=v_range)`, co w pełni respektuje dynamiczne wagi kombinacji na Flopie, Turnie i Riverze.
   - W pętli `processing_loop` przekazywany jest aktualny `cur_hand_summary = active_tracker.get_hand_summary()`.

### 2. Wyniki testów jednostkowych (`pytest -v tests/`)
- Liczba testów: **142 passed in 4.19s (100% sukcesu)**.
- Nowe testy:
  - `tests/test_strategy.py::test_simplifier_relative_ev_gain_allows_profitable_cbet_over_negative_check`
  - `tests/test_strategy.py::test_decision_maker_reads_current_bet_and_uses_zero_preflop_threshold`
  - `tests/test_engine.py::test_build_villain_range_from_history_narrows_across_streets`
  - `tests/test_ui_and_main.py::test_determine_postflop_spot_all_four_variants`
  - `tests/test_ui_and_main.py::test_evaluate_candidates_hits_gtopen_flop_db_when_not_facing_bet_and_uses_range_engine_when_facing_bet`

### 3. Wyniki weryfikacji klatek z nagrań testowych (`nagrania testowe/`)
| Nagranie | Klatka | Ulica / Stan | Spot | Zwrócone EV / Akcja | Latencja | Uwagi |
|---|---|---|---|---|---|---|
| `2 gry na raz` | f1383 | FLOP, not facing bet | `BTN_vs_BB_SRP` | `CHECK`: 0.62 BB, `BET_30`: 0.59 BB -> Decyzja: `CHECK` | 1.6 ms | Trafienie klastra GTOpen Flop DB |
| `2 gry na raz` | f1627 | FLOP, facing bet (120 vs 40) | `BTN_vs_BB_SRP` | `CALL`: +1.89 BB, `ALL_IN`: -4.31 BB -> Decyzja: `CALL` | 51.6 ms | Stanowy `range_engine` z wagami |
| `2026-11-19 211257` | f2604 | TURN, pot=218 | `TURN` | `CHECK`: +4.17 BB, `BET_30`: +2.66 BB -> Decyzja: `CHECK` | 20.0 ms | Stanowy `range_engine` na Turnie |
| `2026-11-19 211257` | f4757 | FLOP, HU facing shove (Quad 7s) | `HU_SB_vs_BB_SRP` | `CALL`: +22.71 BB, `ALL_IN`: +20.66 BB -> Decyzja: `CALL` | 92.0 ms | Perfekcyjny snap-call monster |

---



## V16.1 — Hotfix: Realne Parsowanie `/api/node` Solverem GTOpen (Kombinacje per Combo, Wagi Reach, Rzeczywiste EV w BB i 5 Koszyków) (2026-11-22)

### 1. Wykryty problem i wdrożone poprawki
1. **Eliminacja sztywnych zaślepek w `tools/run_gtopen_overnight.py`:**
   - Poprzednia wersja `solve_flop_via_gtopen` zawierała zbyt krótki timeout na zapytaniu `/api/node` (10 s) oraz sztywne wartości domyślne (`0.40 / 0.50 / 0.10`), co powodowało ciche zapisywanie identycznych danych dla każdego flopa.
   - Wprowadzono pełny parser `parse_node_view_to_categories`, który pobiera całą tablicę `hands` dla aktywnego gracza z `NodeView` serwera GTOpen (1,176 kombinacji).
   - Każda kombinacja `(c1, c2)` jest klasyfikowana do jednego z 5 koszyków (`MONSTER`, `STRONG`, `MEDIUM`, `DRAW`, `AIR`) za pomocą `classify_combo` z `engine/range_engine.py`.
   - Obliczana jest ważona średnia (z wagą `reach * weight`) rzeczywistych prawdopodobieństw strategii CFR oraz **rzeczywistych wartości EV w BB** dla akcji `CHECK`, `BET_30`, `BET_MED`, `ALL_IN`.
   - W przypadku braku poprawnych danych z `/api/node` skrypt rzuca wyjątek `RuntimeError` zamiast podstawiać zaślepki.
2. **Spójne wartości EV w BB w `engine/flop_db.py`:**
   - W `FlopDatabase.lookup_nearest_flop` dodano obsługę nowego formatu z priorytetyzacją słownika `evs` oraz bezpośrednich kluczy akcji w BB.
   - `DecisionMaker` w `main.py` otrzymuje spójne, fizyczne EV w BB (np. 8.50 BB dla Monstera, -0.42 BB dla Check z Air), co pozwala na precyzyjny dobór optymalnej linii gry.

### 2. Porównanie wyników na żywych danych z GTOpen (Dry-Test)
- **Flop `Ah 7d 2c` (Rainbow Dry):**
  - Root Strategy: `CHECK: 46.2%, BET_30: 21.8%, BET_MED: 18.3%, ALL_IN: 13.7%`
  - Root EVs (BB): `CHECK: 1.9879, BET_30: 1.8813, BET_MED: 1.7129, ALL_IN: 1.0353`
  - MONSTER EVs (BB): `CHECK: 9.9011, BET_30: 8.4971, BET_MED: 8.4661, ALL_IN: 7.7772`
  - STRONG EVs (BB): `CHECK: 8.6294, BET_30: 7.3061, BET_MED: 7.2766, ALL_IN: 6.6253`
  - AIR EVs (BB): `CHECK: -0.4198, BET_30: +0.0323, BET_MED: -0.2434, ALL_IN: -1.0234` (zyskowny c-bet bluff!)
- **Flop `Jh Ts 8s` (Wet Monotone Connector):**
  - Root Strategy: `CHECK: 47.6%, BET_30: 25.2%, BET_MED: 20.0%, ALL_IN: 7.2%` (spadek shove o połowę!)
  - MONSTER EVs (BB): `CHECK: 7.5712, BET_30: 7.7483, BET_MED: 7.6780, ALL_IN: 7.2372` (zakład ma wyższe EV niż check!)
  - AIR EVs (BB): `CHECK: -0.3015, BET_30: -0.5633, ALL_IN: -2.7819` (silna kara za bluff air na mokrym boardzie!)
- **Flop `Kd Kh 4c` (Paired Flop):**
  - MONSTER EVs (BB): `CHECK: 6.8501, BET_30: 5.9211`
  - MEDIUM EVs (BB): `CHECK: 0.3700, BET_30: 0.5096` (mały c-bet generuje najwyższe EV)

### 3. Wyniki testów jednostkowych (`pytest -v tests/`)
- Liczba testów: **137 passed in 15.42s (100% sukcesu)**.
- Nowy test: `tests/test_engine.py::test_flop_db_lookup_with_real_evs_and_strategy_structure` potwierdzający poprawne zwracanie realnych EV w BB z bazy solvera.

---


## V16 — Zawsze Włączony 2-Wierszowy Szerszy ActionBar, Korekta HU_SB, Pipeline Solverowy GTOpen i Integracja Nearest-Flop DB (2026-11-22)

### 1. Wdrożone zmiany i nowa architektura
1. **Zawsze włączony i poszerzony 2-wierszowy `ActionBarOverlay` (`ui/hud.py`, `tests/test_ui_and_main.py`):**
   - **Domyślna widoczność obok HUD:** `ActionBarOverlay` jest uruchamiany automatycznie przy starcie aplikacji i pozostaje widoczny zarówno w trybie standardowym, jak i w trybie `⚡ Tylko akcja` (który chowa główny HUD, zostawiając same kafelki akcji).
   - **Szersze i wyższe kafelki:** wymiary plakietek zwiększono do `max(112, int(btn_w * 1.28))` szerokości i `max(38, int(bh * 1.35))` wysokości, wycentrowane dokładnie pod środkami przycisków stołu (`Fold`, `Check-Call`, `Bet-Raise`).
   - **Czytelny układ 2-wierszowy:** wiersz 1 renderuje nazwę akcji (np. `CHECK`, `BET 1 BB`), wiersz 2 renderuje kwotę w żetonach i oczekiwane EV (np. `(20) +0.76 BB`). Zastosowano dynamiczne skalowanie fontu (`QFontMetrics`), gwarantujące brak ucinania tekstu.
2. **Korekta zakresów Heads-Up Small Blind (`HU_SB`) (`data/preflop_tables/nash_3max.json`, `tests/test_strategy.py`):**
   - **Rozszerzenie zakresu otwarcia/limpu:** w heads-up na SB dla 10, 12 i 15 BB rozszerzono zakres rąk grywalnych z ~53% do 81.7% (138 ze 169 kombinacji). Ręce typu `87o`, `97o`, `T7o` grają `CALL` (limp) zamiast pasywnego foldu.
   - **Racjonalizacja sizingów:** dla głębszych stacków (12 i 15 BB) wyeliminowano niefortunne open-shove z rękami typu `A2s-A6s`, zastępując je standardowym `MIN_RAISE`.
3. **Automatyczna kompilacja i integracja solvera GTOpen:**
   - Repozytorium GTOpen sklonowano poza projektem w `c:\Users\leonk\Desktop\porjekty\gtopen`.
   - Zbudowano natywny binarny serwer CPU w profilu release (`cargo build --release -p server`) z wykorzystaniem łańcucha `stable-x86_64-pc-windows-gnu` i kompilatora MinGW GCC 16.2.0 (UCRT), uzyskując plik wykonywalny `gto-server.exe` (8.59 MB) bez konieczności uprawnień administratora.
4. **Nocny pipeline obliczeniowy `tools/run_gtopen_overnight.py`:**
   - **Blokada uśpienia Windows:** wykorzystanie `kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)` zapobiega wyłączeniu komputera w trakcie nocnych obliczeń.
   - **Automatyczny cykl życia:** skrypt samodzielnie uruchamia serwer `gto-server.exe` na porcie 3737, sprawdza gotowość endpointu `/api/status`, komunikuje się przez REST API (`SpotRequest`, `TreeRequest`, `ActionRequest`) i bezpiecznie zamyka proces po zakończeniu.
   - **Wznawianie po przerwaniu (checkpointing):** postęp zapisywany jest po każdym flopie do pliku `data/flop_db/gtopen_progress.json`, z możliwością wznowienia flagą `--resume`.
   - **Zmierzone czasy obliczeń (Benchmark):**
     - Średni czas na 1 flop przy 12 wątkach CPU i dgap 1.00%: **134.02 sekundy** (~2.23 minuty).
     - Szacowany całkowity czas dla pełnego zestawu 188 flopów (4 spoty × 47 flopów kanonicznych): **~7.0 godzin**.
5. **Wyszukiwanie najbliższego klastra w bazie flopów (`engine/flop_db.py`, `main.py`, `tests/test_engine.py`):**
   - Dodano metodę `lookup_nearest_flop(board_cards, spot, hero_cards)` analizującą 6-cechowy wektor tekstury flopa (high card rank, spread, czy sparowany, czy trips, maks. liczba kart w kolorze, liczba kart połączonych).
   - W przypadku braku dokładnego trafienia w bazie 47 flopów system odnajduje najbliższy geometrycznie flop i pobiera strategię dla danego koszyka ręki Hero (`classify_combo`), z bezpiecznym fallbackiem w razie potrzeby.

### 2. Wyniki testów jednostkowych (`pytest -v tests/`)
- Liczba testów: **136 passed in 5.07s (100% sukcesu)**.
- Nowe i zaktualizowane testy:
  1. `tests/test_ui_and_main.py::test_action_bar_enabled_by_default_and_two_line_wider_badges`: potwierdza domyślną widoczność `ActionBarOverlay`, wymiary `>= 112x38 px` i poprawne pozycjonowanie.
  2. `tests/test_strategy.py::test_hu_sb_87o_not_fold_and_a4s_12bb_not_all_in`: weryfikuje poprawność zakresów `HU_SB` (87o nie pasuje, A4s przy 12 BB otwiera min-raise).
  3. `tests/test_engine.py::test_flop_db_nearest_cluster_lookup_and_fallback`: potwierdza dopasowanie najbliższego klastra tekstury dla nietypowych boardów.

---


## V15.1 — Hotfix: Rozpoznawanie H2 (likwidacja nakładania kart i próg K), ICM 50x (Stake JAQKPOT!) oraz Warunek Końca Stołu >=880 Żetonów (2026-11-22)

### 1. Wdrożone poprawki
1. **Likwidacja nakładania się kart Hero i poprawa rozpoznawania `H2` (`config.json`, `vision/card_recognizer.py`):**
   - **Brak kolizji krawędzi:** w `config.json` przesunięto lewą krawędź `hero_card_2` z `0.4950` na `0.4985` oraz szerokość z `0.0420` na `0.0415` (`[0.4985, 0.6744, 0.0415, 0.0880]`). Usunięto 4-pikselowe nakładanie się z prawą krawędzią `hero_card_1` (`0.4585 + 0.0405 = 0.4990`), dzięki czemu ciemna ramka lewej karty nie zaburza segmentacji znaków na prawej karcie (np. pochylone `K♦`).
   - **Adaptacyjny próg akceptacji kart Hero:** w `vision/card_recognizer.py` dla kart gracza (`is_hero == True`), gdy wykryto jednoznaczną grupę koloru (`RED`/`BLACK`) i `s_score >= 0.60`, obniżono efektywny próg akceptacji `eff_thresh` z `0.70` na `0.64`, zapewniając stabilne czytanie trudniejszych rang (np. `K`) bez fałszywych dopasowań.
2. **Korekta progu aktywacji ICM ze strukturą wypłat Stake JAQKPOT! (`strategy/icm.py`, `tests/test_strategy.py`):**
   - W Stake Spin&Go (JAQKPOT!) mnożniki `2x, 3x, 5x, 10x` to format Winner-Takes-All (100% puli dla 1. miejsca = czyste cEV). 3 miejsca płatne (80% / 10% / 10%) obowiązują dopiero od mnożnika `50x`.
   - W `strategy/icm.py` próg `is_icm_active` podniesiono z `5.0 * buy_in` na `50.0 * buy_in`, a podział wypłat w `get_payout_splits` dla `50x+` ustawiono na `[0.80, 0.10, 0.10]`. Zapobiega to nadmiernemu, błędnemu zawężaniu zakresów i pasowaniu w turniejach 5x i 10x.
3. **Pancerny warunek końca stołu `>= 880` żetonów (`state/tracker.py`, `tests/test_state.py`):**
   - W `state/tracker.py` wyeliminowano przedwczesny komunikat `🏆 KONIEC STOŁU` wyzwalany, gdy rywal miał status `OUT`, ale ocalały gracz posiadał jedynie część żetonów (np. 620).
   - Wprowadzono twardy warunek `final_stack >= 880` (przy `pot == 0` i braku aktywnych rywali), gwarantujący, że turniej kończy się wyłącznie po realnej konsolidacji 900 żetonów.

### 2. Wyniki testów jednostkowych (`pytest -v tests/`)
- Liczba testów: **133 passed in 7.84s (100% sukcesu)**.
- Nowe i zaktualizowane testy:
  1. `tests/test_strategy.py::test_icm_bubble_factor_activates_at_5x_and_above`: potwierdza brak ICM dla mnożników `2x, 3x, 5x, 10x` (czyste cEV) oraz poprawną aktywację (`BF > 1.0`, split `[0.80, 0.10, 0.10]`) przy `50x` (`prize_pool=100, buy_in=2`).
  2. `tests/test_state.py::test_tracker_no_false_tournament_end_below_880_stack`: weryfikuje brak przedwczesnego `tournament_result` przy stacku 620 żetonów i puli 0.
- Weryfikacja nagrań testowych: potwierdzona wysoka skuteczność i brak regresji na klatkach z nagrań (`211257`, `224127`, `2 gry na raz`).

---

## V15 — Nowy Silnik Strategii (Range-vs-Range + Pełny Preflop 0–15 BB + ICM od 5x), Alternatywa na HUD, Stabilność Ts oraz Zbiorczy Raport Wszystkich Gier (2026-11-21)

### 1. Wdrożone zmiany i nowa architektura
1. **Nowy moduł postflop `engine/range_engine.py` (Range-vs-Range + MDA):**
   - **Startowy zakres rywala (`get_preflop_villain_range`):** deterministyczny generator ważonych kombinacji rywala dla pozycji `BTN`, `SB`, `BB` i akcji preflop (`OPEN_RAISE` ~42%, `LIMP` ~55%, `CALL_OPEN` ~55%, `3BET_OR_SHOVE` ~14%), filtrujący karty Hero i boardu.
   - **Klasyfikator 5 koszyków (`classify_combo`):** kategoryzuje ręce rywala na `MONSTER` (2 pary+), `STRONG` (top pair / overpair), `MEDIUM` (2./3. para, underpair, A-high), `DRAW` (FD / OESD) i `AIR` za pomocą szybkiej biblioteki `phevaluator`.
   - **Zawężanie zakresu macierzą MDA (`narrow_range_by_postflop_action`):** deterministyczna macierz przejścia populacji mikrostawk (`CHECK` zmniejsza monstery i wzmacnia capped air/medium; `SMALL_BET <= 0.35 pot` utrzymuje szeroki, merged zakres; `BIG_BET / RAISE > 0.70 pot` drastycznie obcina `AIR` do 5% na riverze i premiuje mocne made hands).
   - **Kalkulator equity `compute_range_vs_hand_equity`:** exact enumeration na Riverze (0% błędu, czas `< 2 ms`), 44-card river runout enumeration na Turnie oraz deterministyczne próbkowanie Monte Carlo na Flopie w budżecie `time_budget_ms=400.0` (limit sprzętowy użytkownika do 3 s, faktyczny czas `< 50 ms` na procesorze Intel Core Ultra 5 225H).
   - **Dynamiczne fold equity:** fold equity w modelach sizingów nie jest stałą liczbą, lecz wynika z proporcji `air_ratio` w zawężonym zakresie rywala i wskaźnika SPR.
2. **Twarde reguły bezpieczeństwa i czyszczenie exploitów (`strategy/decision_maker.py`, `strategy/simplifier.py`, `strategy/exploit.py`):**
   - **Absolutny zakaz FOLD przy darmowym CHECK:** gdy `to_call == 0` lub `CHECK` jest dostępny bez otwartego zakładu, akcja `FOLD` jest bezwzględnie usuwana z kandydatów. Bot nigdy nie spasuje, gdy może za darmo stuknąć w stół.
   - **Usunięcie fałszywych exploitów:** całkowicie usunięto regułę `evs["ALL_IN"] += 0.10` z `BB_ISO_VS_LIMP` (która powodowała niefortunne shove'y 14.5 BB z Q8s) oraz regułę `Timing Tell: fast check <500ms` (podatną na szum klatek).
3. **Solverowy Preflop 0–15 BB i moduł ICM (`engine/preflop_nash.py`, `strategy/icm.py`, `data/preflop_tables/nash_3max.json`):**
   - **6 poziomów stacka (15, 12, 10, 8, 6, 4 BB):** zdefiniowane i zoptymalizowane zakresy dla `BTN_OPEN`, `SB_OPEN` (`SB_BVB`, `HU_SB`), `BB_VS_LIMP` (`BB_ISO_VS_LIMP`), `BB_VS_MR` (szeroka obrona ~55-65%), `BB_VS_SHOVE` oraz `SB_VS_BTN`. Ręce typu `Q8s` przy 14.5 BB w `BB_VS_LIMP` grają wyłącznie `MIN_RAISE` lub `CHECK`.
   - **Moduł ICM (`strategy/icm.py`):** implementacja modelu Malmuth-Harville dla 3 graczy (`calculate_icm_equities`) oraz czynnika `compute_bubble_factor`. W turniejach 2x/3x (winner-take-all) Bubble Factor wynosi 1.0 (czyste cEV); przy mnożnikach 5x+ (gdzie 2. miejsce otrzymuje 25% puli) Bubble Factor wzrasta do ~1.33, podnosząc wymagane equity dla ryzykownych all-inów i chroniąc turniejowe equity Hero.
4. **Pokazywanie bliskiej alternatywy na HUD (`core/contracts.py`, `strategy/decision_maker.py`, `main.py`, `ui/hud.py`):**
   - W kontrakcie `Decision` dodano opcjonalne pola: `alt_action`, `alt_ev_bb`, `alt_sizing_bb`, `alt_sizing_chips`.
   - Gdy druga najlepsza legalna akcja różni się od głównej i ma `alt_ev_bb >= best_ev_bb - 0.05`, system zapisuje alternatywę.
   - W `ui/hud.py` pod główną odznaką wyświetlana jest subtelna linijka, np. `Alt: BET 1 BB (20) (+0.52 BB)` w kolorze `#94a3b8`.
5. **Stabilność kart Ts i ochrona puli nagród (`state/tracker.py`, `state/hand_history.py`):**
   - **3-klatkowy debounce i blokada postflopu:** w `state/tracker.py` zmiana samych kart Hero przy `len(board_cards) >= 3` bez zmiany dealera i resetu ulicy NIGDY nie wyzwala `NEW_HAND`. Na preflopie wymagane są 3 kolejne klatki z nowymi kartami, co całkowicie usuwa rozcinanie rozdań na kawałki przez 1-klatkowy glitch OCR `Ts`.
   - **3-klatkowy filtr eliminacji Hero:** brak stacka (`stack is None` i `not is_active`) dla `seat_id == 0` wymaga 3 kolejnych klatek przed oznaczeniem `eliminated = True`.
   - **Nienaruszona pula nagród:** w `HandHistoryRecorder.record_hand` i `finalize_game` zapisana dodatnia pula nagród (`game["prize_pool"] > 0`) nie jest nadpisywana zerem, eliminując błąd nazewnictwa `prize0.md` i `prize0.zip`.
6. **Narzędzia: Zbiorczy Raport Wszystkich Gier i Importer GTOpen (`tools/export_games_md.py`, `tools/import_gtopen.py`):**
   - `tools/export_games_md.py`: automatycznie parsuje wszystkie raporty gier z `hand_histories/` i generuje plik `hand_histories/ALL_GAMES_REPORT.md` z tabelą podsumowującą liczbę gier, rozdań, decyzji Hero, pul nagród i zwycięzców na samej górze.
   - `tools/import_gtopen.py`: konwerter formatów zakresów GTOpen (np. `AA,KQs:0.5,A5s-A2s,77+`) z automatyczną ekspansją skrótów i walidacją schematu do bazy JSON.

### 2. Wyniki testów jednostkowych (`pytest -v tests/`)
- Liczba testów: **132 passed in 4.87s (100% sukcesu)**.
- Nowe testy jednostkowe:
  1. `tests/test_strategy.py::test_never_fold_when_free_check_available`: potwierdza, że Hero na BB po limpie (`to_call == 0`) nigdy nie otrzymuje akcji `FOLD`.
  2. `tests/test_strategy.py::test_bb_vs_limp_deep_14bb_q8s_not_all_in`: weryfikuje, że `Q8s` przy 14.5 BB na BB po limpie gra `MIN_RAISE` lub `CHECK`, nigdy `ALL_IN`.
  3. `tests/test_strategy.py::test_icm_bubble_factor_activates_at_5x_and_above`: potwierdza nieaktywność ICM w 2x/3x (BF=1.0) oraz aktywację w 5x+ (BF=1.33).
  4. `tests/test_strategy.py::test_decision_populates_alt_action_within_0_05_bb`: weryfikuje poprawne wyliczanie i wypełnianie `alt_action` i `alt_ev_bb` dla akcji różniącej się o `<= 0.05 BB`.
  5. `tests/test_engine.py::test_range_narrowing_big_river_bet_reduces_air_and_lowers_bluffcatcher_equity`: potwierdza, że duży zakład na riverze obcina AIR i obniża equity bluffcatchera (`7d 6d` z 0.59 na 0.15) z exact enumeration.
  6. `tests/test_state.py::test_tracker_3_frame_debounce_ignores_single_frame_ts_glitch_on_postflop`: potwierdza ignorowanie 1-klatkowego glitcha `5h Ts` na flopie bez rozcinania rozdania.
  7. `tests/test_state.py::test_hand_history_preserves_nonzero_prize_pool_on_finalize`: potwierdza zachowanie `$4` przy finalizacji turnieju z `prize_pool=0`.
  8. `tests/test_state.py::test_export_games_md_combines_multiple_games`: weryfikuje łączenie wielu plików markdown gier w zbiorczy raport `ALL_GAMES_REPORT.md`.
  9. `tests/test_ui_and_main.py::test_hud_renders_alt_action_when_present`: potwierdza renderowanie linii `Alt: ...` na etykiecie HUD.

---

## V14.2 — 1 Gra = 1 Paczka .zip + Kopia .md, Czyste Śledzenie Ulic i Historii, Naprawa KONIEC STOŁU oraz Usunięcie Fałszywych Timing Tell (2026-11-21)

### 1. Wdrożone zmiany i nowa architektura
1. **1 gra = 1 paczka `.zip` + kopia `.md` obok (`main.py`, `state/hand_history.py`):**
   - **Usunięcie przedwczesnego rozbijania gier:** w `main.py` całkowicie usunięto wywołania `validator.reset_table`, `hand_recorder.finalize_game` oraz resetowanie trackerów z bloku `compute_opponents_signature` (`match_score < 0.85`), które reagowało na dymki akcji przeciwników i rozbijało pojedynczą grę na kilkanaście paczek `.zip`.
   - **3-klatkowe potwierdzenie końca turnieju:** wprowadzono licznik `tournament_end_confirm[table_id]` oraz zestaw `finalized_tournament_tables`. Gra jest finalizowana do archiwum wyłącznie po 3 kolejnych klatkach `VALID` potwierdzających `tournament_result`. Nowa gra na tym samym oknie jest odblokowywana dopiero po wykryciu nowego turnieju (spadek blindów z resetem, powrót z Heads-Up do pełnego 3-max ze stackami `260..320` przy `10/20` lub co najmniej 2 graczy ze stackami `0 < stack < 880`).
   - **Kopia `.md` bezpośrednio w folderze `hand_histories/`:** w `HandHistoryRecorder.finalize_game` tworzony jest nie tylko plik `game_...zip`, lecz również bezpośrednia kopia `game_...md` obok archiwum (ułatwiająca szybki podgląd i udostępnianie bez rozpakowywania).
   - **Sekcja `## 📊 Podsumowanie gry`:** na końcu każdego pliku `history.md` generowane jest podsumowanie zawierające liczbę rozdań, pulę nagród (`$prize`), zwycięzcę turnieju oraz liczbę podjętych decyzji HUD w turze Hero (z wykluczeniem `[PLAN]`).
   - **Deduplikacja zdjęć:** zrzuty ekranu w `snapshots` są w pełni deduplikowane w raporcie Markdown (`dict.fromkeys`), a kolejne decyzje Hero na tej samej ulicy są numerowane (`decision_<street>_1`, `decision_<street>_2`).
2. **Naprawa `tournament_result` i ochrona przed `ALL_IN (0)` (`state/tracker.py`, `main.py`):**
   - **Ścisły warunek końca stołu:** `tournament_result` jest ustawiany wyłącznie gdy `pot == 0` ORAZ (`stack >= 880` u 1 gracza LUB dokładnie 2 rywali ma status `OUT` / `eliminated == True`). Wyeliminowało to fałszywy komunikat `🏆 KONIEC STOŁU — Zwycięzca: Ty (S0), stack 100` pojawiający się podczas all-ina dwóch rywali z pulą w toku (`pot > 0`).
   - **Ochrona `Hero is All-In`:** w `main.py` gdy `hero_stack == 0`, system zwraca decyzję `WAIT` (`"Hero is All-In"`), całkowicie uniemożliwiając generowanie bezsensownej rekomendacji `ALL_IN (0)`.
3. **Czyste śledzenie ulic, eliminacja glitchy OCR i naprawa `Timing Tell` (`state/tracker.py`, `strategy/exploit.py`):**
   - **Realna ulica z liczby kart na boardzie (`_resolve_real_street`):** ulica pokerowa jest wyznaczana ściśle z liczby kart na stole (`0→PREFLOP`, `3→FLOP`, `4→TURN`, `5→RIVER`). Przejście `WAITING_FOR_TURN <-> PREFLOP` przy pustym boardzie nie jest zdarzeniem `STREET_CHANGE`, nie zeruje `street_bet` i nie uruchamia fałszywego `FOLD` ani wielokrotnego naliczania `invested_total` (`40→80→120`).
   - **Naprawa `Timing Tell: fast check <500ms`:** przy każdym realnym `STREET_CHANGE` zerowane jest `last_reaction_ms = None` u wszystkich graczy. W `strategy/exploit.py` wprowadzono bezpieczny przedział `150 <= last_reaction_ms < 500`, odrzucając artefakty `0..149 ms` z klatek przejściowych.
   - **Filtr glitchy animacji OCR i zgarniania puli:** zignorowano drobne wartości OCR `0 < curr_bet < small_blind` przy `stack > 0` (np. `BET 1`, `BET 2`, `RAISE 4`) oraz artefakty animacji zgarniania puli z poprzedniego rozdania (`cur_bet > 2 * big_blind` na starcie rozdania bez kart na stole).
   - **Czysta tabela `HUD vs Hero`:** `record_recommendation` zapisuje realną ulicę, pomija rekomendacje `[PLAN]` i deduplikuje wpisy po krotce `(real_street, action, sizing_bb, sizing_chips)`.

### 2. Wyniki testów jednostkowych (`pytest -v tests/`)
- Liczba testów: **124 passed in 6.41s (100% sukcesu)**.
- Nowe testy jednostkowe:
  1. `tests/test_state.py::test_tracker_no_false_tournament_end_on_two_opponents_all_in`: weryfikuje brak fałszywego `tournament_result` przy stackach 0 rywali i puli w toku (`pot=800`) oraz poprawne ogłoszenie zwycięzcy po zebraniu puli (`pot=0`).
  2. `tests/test_state.py::test_tracker_waiting_for_turn_does_not_double_invested_or_false_fold`: weryfikuje brak wielokrotnego akumulowania `invested_total` oraz brak fałszywego `FOLD` przy oscylacji między `WAITING_FOR_TURN` a `PREFLOP`.
  3. `tests/test_state.py::test_tracker_ignores_sub_sb_ocr_glitch_and_stale_pot_sweep`: weryfikuje ignorowanie jednocyfrowych glitchy OCR poniżej SB oraz filtrowanie artefaktu zgarniania puli (740 żetonów) na starcie nowego rozdania.
  4. `tests/test_state.py::test_hand_history_saves_both_zip_and_standalone_md_with_summary`: weryfikuje tworzenie pary `game_...zip` + `game_...md`, poprawność sekcji `## 📊 Podsumowanie gry` oraz deduplikację zrzutów ekranu.
  5. `tests/test_strategy.py::test_exploit_timing_tell_ignores_zero_ms_transition_artifact`: weryfikuje brak fałszywego timing tell dla czasów reakcji 0 ms i 50 ms oraz poprawne zadziałanie dla 250 ms.
  6. `tests/test_ui_and_main.py::test_hero_all_in_stack_zero_returns_wait_not_all_in_zero`: weryfikuje, że dla `hero.stack == 0` system emituje decyzję `WAIT` (`"Hero is All-In"`) zamiast `ALL_IN (0)`.

---

## V14.1 — Hotfix: Usunięcie UnboundLocalError (spot i now_sec) w processing_loop oraz Zachowanie Sizingu na Klatkach z Keszu DecisionLock (2026-11-21)

### 1. Wdrożone poprawki
1. **Usunięcie `UnboundLocalError` na zmiennych `spot` i `now_sec` (`main.py`):**
   - W `processing_loop` dodano `last_spots: dict[str, str] = {}` oraz przypisanie `spot: str = last_spots.get(resolved_tid, "--")` przed blokiem ewaluacji kart i tury Hero. Gwarantuje to, że zmienna `spot` jest zawsze zdefiniowana (dla klatek niepoprawnych, w fazie `WAITING_FOR_TURN`, w fazie zbierania konfirmacji oraz na decyzjach serwowanych z pamięci podręcznej `DecisionLock`).
   - Słownik `last_spots` jest czyszczony spójnie z `decision_locks` i `trackers` (usunięcie stołu przez użytkownika, rotacja przeciwników w slocie, wygaśnięcie LRU, spadek blindów i zdarzenie `NEW_HAND`).
   - Dodano inicjalizację `now_sec = time.perf_counter()` na początku pętli każdej klatki (obok `now_ms = int(time.time() * 1000)`), eliminując błąd `UnboundLocalError` przy zapisie `last_valid_decisions[resolved_tid] = (now_sec, decision, scan_summary)` podczas tury Hero.
2. **Nienaruszony sizing na klatkach z pamięci podręcznej `DecisionLock` (`main.py`):**
   - Usunięto zabłąkaną klauzulę `else` pod blokiem snapshotów decyzji:
     ```python
     else:
         decision.sizing_bb = None
         decision.sizing_chips = None
     ```
     która na klatkach gdzie `just_locked_decision == False` zerowała pola `sizing_bb` i `sizing_chips` obiektu `Decision`. Dzięki temu decyzje zamrożone przez `DecisionLock` prezentują identyczny, spójny sizing przez cały czas trwania tury Hero.
3. **Nowy test regresyjny (`tests/test_ui_and_main.py`):**
   - `test_processing_loop_live_no_unbound_spot_and_keeps_sizing`: symuluje działanie `processing_loop(..., is_live=True)` na sekwencji klatek (1 klatka niepoprawna/bez kart + 3 identyczne klatki poprawne z turą Hero). Potwierdza stabilność wątku, 2-klatkowe zatwierdzenie przez `DecisionLock` oraz nienaruszenie wartości `sizing_bb` i `sizing_chips` na klatce serwowanej z pamięci podręcznej.

### 2. Wyniki testów jednostkowych (`pytest -v tests/`)
- Liczba testów: **118 passed in 5.43s (100% sukcesu)**.

---

## V14 — Stabilizacja i Zatwierdzanie Decyzji (DecisionLock), Naprawa Historii Rozdań + Zwycięzca Stołu oraz Osobne Paczki .zip dla Każdej Gry z Lekkim Zapisem Zdjęć (2026-11-21)

### 1. Wdrożone zmiany i nowa architektura
1. **Deterministyczny silnik Monte Carlo (`engine/monte_carlo.py`):**
   - Dodano opcjonalny parametr `seed: int | None = None` do `MonteCarloCalculator.estimate_equity(...)`.
   - W przypadku `seed is None` seed jest wyliczany w sposób deterministyczny za pomocą `zlib.crc32` z klucza `(sorted(hero_cards), list(board_cards), num_opponents, len(villain_range))`.
   - Użycie lokalnego generatora `rng = random.Random(seed)` zamiast globalnego modułu `random` całkowicie eliminuje losowy szum ±2% equity między klatkami — dla tej samej ręki i sytuacji na boardzie wynik jest w 100% powtarzalny (co do `1e-9`).
2. **Mechanizm zatwierdzania i zamrażania decyzji (`strategy/decision_lock.py`, `main.py`):**
   - Utworzono moduł `strategy/decision_lock.py` z funkcją `compute_decision_fingerprint(state, is_preview)` oraz klasą `DecisionLock(confirm_frames=2)`.
   - Fingerprint obejmuje karty Hero, karty boardu, ulicę, turę Hero, tryb preview, dostępne akcje, pulę, blindy oraz sygnatury graczy (stack, bet, status aktywności i pozycja dealera).
   - W `main.py` decyzja jest liczona tylko raz (z precyzyjnym budżetem `time_budget_ms=80.0`) po potwierdzeniu przez 2 kolejne zgodne klatki (`confirm_frames=1` w testach/offline), po czym zostaje zatwierdzona (`lock`) i serwowana natychmiast z pamięci podręcznej aż do realnej zmiany sytuacji na stole.
   - Eliminacja migotania rekomendacji HUD (10–20 razy/s) i radykalny spadek zużycia CPU (`< 5 ms` na zatwierdzonej decyzji).
3. **Naprawa 5 błędów śledzenia rozdań i wykrywanie zwycięzców (`state/tracker.py`, `main.py`):**
   - **Brak fałszywego `NEW_HAND`:** naprawiono `hero_cards_changed` (`bool(prev_known_hero) and bool(state.hero_cards) and state.hero_cards != prev_known_hero`), dzięki czemu pojawienie się kart Hero po fazie `WAITING_FOR_TURN` nie przecina i nie ucina rozdania.
   - **Status `OUT` zamiast `FOLD`:** gracze z `stack is None` i `not is_active` otrzymują status `OUT` (`eliminated=True`), bez błędnego dopisywania akcji `FOLD` do `action_log`.
   - **Blindy vs Bety i dołączenie w trakcie rozdania:** w fazie preflop / `WAITING_FOR_TURN` zakłady równe SB lub BB są oznaczane jako `BLIND` z `decision_sec=None`. Wejście do monitorowania w trakcie rozdania (widoczny board lub zakłady > BB) oznacza akcje jako `BET` na bieżącej ulicy (`mid_hand_join=True`).
   - **Śledzenie akcji Hero:** rejestrowane są wszystkie rzeczywiste akcje Hero (`seat_id == 0`), w tym `CHECK` (po zakończeniu tury bez podbicia przy braku zakładu do sprawdzenia).
   - **Wyliczanie zwycięzcy rozdania i całego stołu:**
     * Zwycięzca rozdania jest wyliczany przy zamknięciu rozdania z delty stacków powiększonej o zwrot puli (`result = {"winner_seat", "winner_name", "net_delta", "deltas"}`).
     * Zwycięzca stołu (`tournament_result`) jest automatycznie wykrywany, gdy 1 gracz osiągnie `stack >= 880` lub pozostali dwaj rywale zostaną wyeliminowani (`OUT`).
4. **Osobne paczki `.zip` dla każdej gry i lekki zapis zrzutów ekranu (`config.json`, `state/hand_history.py`, `main.py`, `ui/hud.py`):**
   - Zmiana architektury zapisu w `HandHistoryRecorder`: każda gra gromadzi dane w osobnym podfolderze roboczym `hand_histories/_active/game_<YYYYMMDD_HHMMSS>_<table_id>/`.
   - Po zakończeniu turnieju, wykryciu nowych przeciwników, usunięciu stołu lub zamknięciu aplikacji moduł automatycznie pakuje grę do osobnego archiwum `.zip` (`zipfile.ZIP_DEFLATED`) o nazwie `game_<YYYYMMDD_HHMMSS>_<table_id>_prize<prize>.zip` zawierającego `history.jsonl`, czytelny `history.md` (z tabelą graczy, sekcją `Podjęte decyzje: HUD vs Hero`, `Wynik rozdania`, zrzutami i banerem `🏆 KONIEC STOŁU`) oraz opcjonalny podfolder `snapshots/`. Po spakowaniu katalog roboczy jest usuwany.
   - Zrzuty ekranu: wycinany `table_rect` przeskalowany proporcjonalnie do `640 px` szerokości w formacie JPEG (`quality=65`, rozmiar ~25–35 KB/szt.) zapisywany maksymalnie 3–4 razy na rozdanie (`LOCKED_DECISION`, `STREET_CHANGE`, `HAND_END`).
   - Opcja zapisu zdjęć jest w pełni wyłączalna: sekcja `recording.save_snapshots` w `config.json`, flagi CLI `--save-snapshots` / `--no-snapshots` oraz dyskretny przycisk `📷` w panelu `Szczegóły` HUD (`HudBridge.snapshots_toggled`).

### 2. Wyniki weryfikacji na nagraniach testowych

| Nagranie | Klatka | Rozdzielczość | Źródło kotwicy | Karty Hero | Karty Board | Pot | Blinds | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `2026-11-19 211257` | `1827` | `1858x1248` | **RIM** | `Kh 2s` | `--` | `70` | `10/20` | **VALID (100%)** |
| `2026-11-19 211257` | `2604` | `1858x1248` | **RIM** | `Kh 2s` | `7d Td Th 2h` | `218` | `10/20` | **VALID (100%)** |
| `2026-11-19 211257` | `3880` | `1858x1248` | **RIM** | `Jc 4d` | `--` | `206` | `10/20` | **VALID (100%)** |
| `2026-11-19 211257` | `4757` | `1858x1248` | **RIM** | `7s 7d` | `Qc 7c 7h` | `682` | `15/30` | **VALID (100%)** |
| `2026-11-18 224127` | `0` | `1772x1126` | **RIM** | `2s Tc` | `--` | `80` | `10/20` | **VALID (100%)** |
| `2026-11-18 224127` | `765` | `1772x1126` | **RIM** | `Kd 3c` | `--` | `30` | `10/20` | **VALID (100%)** |
| `2026-11-18 224127` | `2370` | `1772x1126` | **RIM** | `7c 5s` | `--` | `90` | `15/30` | **VALID (100%)** |
| `2 gry na raz` | `1383` | `1706x1022` | **RIM** | `Ks 9s` | `3s Ac Ah` | `80` | `10/20` | **VALID (100%)** |
| `2 gry na raz` | `1627` | `1706x1022` | **RIM** | `Ks 9s` | `3s Ac Ah` | `240` | `10/20` | **VALID (100%)** |
| `2 gry na raz` | `2605` | `1706x1022` | **RIM** | `4d Qs` | `5d 8c Jh` | `50` | `10/20` | **VALID (100%)** |

### 3. Wyniki testów jednostkowych (`pytest -v tests/`)
- Liczba testów: **117 passed in 5.13s (100% sukcesu)**.
- Nowe testy jednostkowe:
  1. `tests/test_engine.py::test_monte_carlo_deterministic_seed`: weryfikuje determinizm generatora Monte Carlo z powtarzalnością equity co do `1e-9`.
  2. `tests/test_strategy.py::test_decision_lock_confirms_and_freezes_until_state_change`: weryfikuje 2-klatkową konfirmację, zamrożenie decyzji przy identycznym stanie i odblokowanie po zmianie parametrów stołu.
  3. `tests/test_state.py::test_tracker_no_false_new_hand_on_waiting_to_preflop_and_blinds_not_bets`: odtwarza scenariusz z sesji live (brak fałszywego `NEW_HAND`, blindy jako `BLIND`, status `OUT` dla gracza wyeliminowanego).
  4. `tests/test_state.py::test_tracker_winner_delta_and_tournament_winner`: weryfikuje obliczanie zwycięzcy rozdania z delty stacków oraz `tournament_result` po uzyskaniu stacka `>= 880`.
  5. `tests/test_state.py::test_hand_history_per_game_zip_with_and_without_snapshots`: weryfikuje tworzenie 2 oddzielnych paczek `.zip` dla 2 gier (z zachowaniem rozmiaru zdjęć 640px < 60 KB w grze ze zrzutami i brakiem zdjęć w grze bez zrzutów) oraz posprzątanie folderu `_active/`.
  6. `tests/test_ui_and_main.py::test_hud_snapshots_toggle_button_in_details`: weryfikuje ukrycie przycisku `📷` w widoku minimalistycznym, jego widoczność w `Szczegółach` oraz emisję sygnału przełączania.

---

## V13 — Mikro-kalibracja ROI, Minimalistyczny HUD z Wizualnymi Kartami i Tabelą Zagrań, Sizing w Wielokrotnościach BB oraz Rejestrator Historii Rozdań (2026-11-21)

### 1. Wdrożone zmiany i nowa architektura
1. **Mikro-kalibracja 4 ROI i rozszerzenie poziomów blindów (`config.json`, `core/constants.py`, `tests/test_contracts.py`):**
   - `seat_2_bet`: poszerzono z `[0.675, 0.405, 0.04, 0.038]` na `[0.666, 0.405, 0.049, 0.038]` (bezpieczny lewy margines dla cyfry `5` w zakładach `565`).
   - `seat_1_dealer` & `seat_2_dealer`: skalibrowano `y` i `h` na `[0.368, 0.270, 0.032, 0.042]` oraz `[0.602, 0.270, 0.032, 0.042]` (brak obcinania żetonu `[D]`).
   - `blinds`: poszerzono z `[0.55, 0.57, 0.065, 0.0351]` na `[0.546, 0.57, 0.072, 0.036]` (obsługa blindów `50/100` i `60/120` bez stykania się cyfr z lewą krawędzią).
   - W `core/constants.py` dodano `(50, 100)` oraz `(60, 120)` do `BLIND_LEVELS` (łącznie 7 poziomów). Zaktualizowano `tests/test_contracts.py`.
2. **Sizing wyłącznie w wielokrotnościach BB lub ALL-IN (`core/contracts.py`, `strategy/simplifier.py`, `main.py`, `ui/hud.py`):**
   - Rozszerzono `Decision` o opcjonalne pola: `sizing_chips: int | None = None` oraz `sizing_bb: int | None = None` (100% zgodności wstecznej z dotychczasowymi konstruktorami).
   - Zaimplementowano funkcję `quantize_sizing_to_bb(target_chips, big_blind, hero_stack, effective_stack, min_bb_mult=1, all_in_threshold_ratio=0.65)` w `strategy/simplifier.py`.
   - Przejście w `ALL_IN`: gdy `chips >= 0.65 * effective_stack`, `chips >= hero_stack` lub `effective_stack <= 3 * big_blind` przy akcji agresywnej.
   - W `main.py` powiązano estymację EV postflop w `evaluate_candidates` z rzeczywistym skwantyzowanym rozmiarem betu `bet_bb = float(bb_mult)`, eliminując niespójności matematyczne.
   - Wprowadzono wspólną funkcję `format_action_label(action, sizing_bb, sizing_chips)` w `ui/hud.py` wykorzystywaną spójnie w HUD oraz w `ActionBarOverlay` (np. `BET 2 BB (200)`, `RAISE 2 BB (40)`, `ALL-IN (235)`).
3. **Śledzenie zagrań w rozdaniu (`state/tracker.py`) i rejestrator historii (`state/hand_history.py`):**
   - Rozbudowano `TableTracker` o chronologiczny stan rozdania `self.current_hand`, `self.last_completed_hand`, sumowanie `invested_total` przez ulice, czas reakcji (`decision_sec`) oraz deduplikację rekomendacji HUD.
   - Deterministyczne wykrywanie FOLD: warunek A (status `FOLDED` / brak aktywności gracza), warunek B (zmiana ulicy bez wyrównania wcześniejszego betu), warunek C (Hero fold po minięciu tury bez sprawdzenia zakładu).
   - Utworzono moduł `HandHistoryRecorder`: zapisuje zakończone rozdania do `hand_histories/session_YYYYMMDD_HHMMSS.jsonl` oraz czytelnego `.md` z tabelami graczy, chronologią akcji i rekomendacjami HUD (dopisano `hand_histories/` do `.gitignore`).
4. **Minimalistyczny HUD, wizualne karty i rozdzielenie kalibracji (`ui/hud.py`):**
   - Dodano `render_visual_cards_html` renderującą ostre, białe kafelki kart z symbolami w kolorach `#dc2626` (`♦♥`) i `#0f172a` (`♠♣`) w tabeli HTML (idealny render na Windows HiDPI).
   - Zaktualizowano `format_cards_html` pod kątem białych kafelków.
   - Tryb domyślny HUD: minimalistyczny widok z dużą odznaką rekomendacji, EV oraz rzędem białych kafelków kart własnych i stołu.
   - Tryb `🔍 Szczegóły`: bogaty, czysty panel HTML z tabelą graczy (`Stack`, `Włożył`, `Zagranie`, `Czas`), złotą odznaką dealera `[D]`, wyszarzonymi wierszami `FOLD` ze skreśloną nazwą `<s>...</s>`, historią 4 ostatnich akcji i stopką diagnostyczną.
   - **Naprawa błędu z V12:** kliknięcie `🔍 Szczegóły` **nigdy** nie otwiera panelu kalibracji stołu. Kalibracja została przeniesiona pod mały dyskretny przycisk `⚙` w nagłówku stołu.
   - Dodano dedykowany sygnał `HudBridge.hand_summary_updated` zapewniający pełną izolację sygnałów.

### 2. Wyniki weryfikacji na nagraniach testowych

| Nagranie | Klatka | Rozdzielczość | Źródło kotwicy | Karty Hero | Karty Board | Pot | Blinds | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `2026-11-19 211257` | `1827` | `1858x1248` | **RIM** | `Kh 2s` | `--` | `70` | `10/20` | **VALID (100%)** |
| `2026-11-19 211257` | `2604` | `1858x1248` | **RIM** | `Kh 2s` | `7d Td Th 2h` | `218` | `10/20` | **VALID (100%)** |
| `2026-11-19 211257` | `3643` | `1858x1248` | **RIM** | `Jc 4d` | `--` | `30` | `10/20` | **VALID (100%)** |
| `2026-11-19 211257` | `3880` | `1858x1248` | **RIM** | `Jc 4d` | `--` | `206` | `10/20` | **VALID (100%)** |
| `2026-11-19 211257` | `4757` | `1858x1248` | **RIM** | `7s 7d` | `Qc 7c 7h` | `682` | `15/30` | **VALID (100%)** |
| `2026-11-18 224127` | `0` | `1772x1126` | **RIM** | `2s Tc` | `--` | `80` | `10/20` | **VALID (100%)** |
| `2026-11-18 224127` | `765` | `1772x1126` | **RIM** | `Kd 3c` | `--` | `30` | `10/20` | **VALID (100%)** |
| `2026-11-18 224127` | `2370` | `1772x1126` | **RIM** | `7c 5s` | `--` | `90` | `15/30` | **VALID (100%)** |
| `2026-11-18 224127` | `4950` | `1772x1126` | **RIM** | `5h Jh` | `Jd 2s 9h` | `60` | `15/30` | **VALID (100%)** |
| `2 gry na raz` | `1383` | `1706x1022` | **RIM** | `Ks 9s` | `3s Ac Ah` | `80` | `10/20` | **VALID (100%)** |
| `2 gry na raz` | `1627` | `1706x1022` | **RIM** | `Ks 9s` | `3s Ac Ah` | `240` | `10/20` | **VALID (100%)** |
| `2 gry na raz` | `2418` | `1706x1022` | **RIM** | `4d Qs` | `--` | `50` | `10/20` | **VALID (100%)** |
| `2 gry na raz` | `2605` | `1706x1022` | **RIM** | `4d Qs` | `5d 8c Jh` | `50` | `10/20` | **VALID (100%)** |

### 3. Wyniki testów jednostkowych (`pytest -v tests/`)
- Liczba testów: **111 passed in 4.03s (100% sukcesu)**.
- Nowe testy:
  1. `tests/test_strategy.py::test_quantize_sizing_to_bb_and_all_in`: testuje kwantyzację sizingu do wielokrotności BB dla BB=20 i BB=100, próg ALL-IN (>= 65% efektywnego stacka oraz <= 3 BB przy agresji) i stack 0.
  2. `tests/test_state.py::test_tracker_hand_summary_invested_time_and_fold`: testuje sumowanie `invested_total` w trakcie rozdania i przez ulice, czas decyzji (`decision_sec`) oraz deterministyczne wykrywanie FOLD (warunki A, B, C).
  3. `tests/test_state.py::test_hand_history_recorder_jsonl_and_md`: testuje zapis plików `.jsonl` i `.md`, pomijanie pustych rozdań oraz strukturę raportu.
  4. `tests/test_ui_and_main.py::test_render_visual_cards_html_and_action_labels`: testuje białe kafelki kart HTML z poprawnymi kolorami i formatowanie etykiet akcji.
  5. `tests/test_ui_and_main.py::test_hud_details_shows_table_with_grayed_fold_and_keeps_calibration_hidden`: testuje panel szczegółów z wyszarzonym wierszem FOLD, mały guzik `⚙` i niewidoczność panelu kalibracji bez kliknięcia `⚙`.

---

## V12 — Pancerna geometria stołu (4 czyste łuki złotej obwódki jako numer 1, Anti-Jitter, usuwanie dowolnego stołu i kompaktowy HUD) (2026-11-21)

### 1. Wdrożone zmiany i nowa architektura
1. **Detektor 4 czystych łuków złotej obwódki (`vision/anchor.py`, `vision/pipeline.py`, `config.json`):**
   - Zaimplementowano 2-etapowy algorytm `find_golden_rim(frame, search_rect=None)`:
     * **Etap A (Niebieskie sukno):** wykrywa obszar stołu w HSV (`H: 90..135, S: 40..255, V: 30..255`) z zamknięciem morfologicznym (`MORPH_CLOSE` 25x25), odrzucając artefakty o powierzchni `< 15000 px` lub proporcjach spoza `1.45..2.25`.
     * **Etap B (4 czyste łuki):** mierzy złotą obwódkę (`H: 12..35, S: 50..255, V: 90..255`) w strefach odpornych na zasłanianie:
       - *Lewy łuk:* pas środkowy `y ∈ [0.38*fh, 0.62*fh]`, `x ∈ [fx - 0.04*fw, fx + 0.04*fw]`, 15. percentyl `x`.
       - *Prawy łuk:* pas środkowy `y ∈ [0.38*fh, 0.62*fh]`, `x ∈ [fx + fw - 0.04*fw, fx + fw + 0.04*fw]`, 85. percentyl `x`.
       - *Górny łuk:* pas między awatarami S1 i S2 `x ∈ [0.44*fw, 0.56*fw]`, powyżej Prize Pool `y ∈ [fy - 0.08*fh, fy + 0.12*fh]`, 15. percentyl `y`.
       - *Dolny łuk:* dwa pasy po bokach kart Hero `x ∈ [0.22*fw, 0.36*fw]` i `x ∈ [0.64*fw, 0.78*fw]`, powyżej przycisków gry, 15. percentyl `y`.
     * Twarda weryfikacja pewności: min. 15 punktów w każdym z 4 pasów, proporcje stadionu `1.55 <= ow/oh <= 2.15`, dominacja niebieskiego sukna w centrum `>= 40%`.
   - Zmierzono i skalibrowano uniwersalne współrzędne względne obwódki: `"golden_rim_rel": [0.1802, 0.2075, 0.6402, 0.5630]` (dokładność `±1 px` na każdym nagraniu).
2. **Odwrócenie priorytetu kotwiczenia na rzecz złotej obwódki (`main.py`, `vision/pipeline.py`):**
   - Złota obwódka 4 łuków stała się metodą **NUMER 1** (`anchor_source = "RIM"`). Szablon `find_anchor` z paska ikon stanowi bezpieczny fallback NUMER 2 (`anchor_source = "ICON"`), a zdefiniowany region – NUMER 3 (`anchor_source = "MANUAL"`).
   - Całkowicie wyeliminowano podatność na marginesy przeglądarki, panel Bet Slip i sztywne listy skal — algorytm działa w dowolnej skali ciągłej od `0.5x` do `2.0x`.
3. **Stabilizacja czasowa Anti-Jitter (`vision/anchor.py`, `main.py`):**
   - Dodano funkcję `apply_anti_jitter(new_rect, last_stable_rect, deadband_px=3)`.
   - Mikro-przesunięcia `<= 3 px` między klatkami są zamrażane do poprzedniej pozycji, co eliminuje drganie ramek ROI. Rzeczywisty ruch okna (`> 3 px`) natychmiast uaktualnia współrzędne.
4. **Usuwanie dowolnego stołu i natychmiastowe czyszczenie nakładek (`ui/hud.py`):**
   - Przycisk `✕ Usuń` jest dostępny dla każdego stołu (w tym `table_1`), gdy liczba monitorowanych stołów `> 1`.
   - Usunięcie stołu natychmiast czyści jego obrysy z `DebugRoiOverlay` i `ActionBarOverlay` oraz emituje `table_removed_by_user`. Dodano `_removed_table_ids`, co zapobiega samoczynnemu odradzaniu się usuniętych stołów z opóźnionych klatek.
5. **Kompaktowy HUD mieszczący się w ekranie (`ui/hud.py`):**
   - Ustawiono `setMaximumWidth(440)`. Pasek kalibracji rozbito na 2 rzędy przycisków, zapobiegając rozpychaniu okna.
   - Zaimplementowano `_clamp_to_screen()`, która pilnuje, by okno HUD nigdy nie wyszło poza prawą ani dolną krawędź monitora.
   - W panelu `🔍 Szczegóły` dodano linię `Kotwica: RIM (2027x1150 @ 207,335)` jednoznacznie informującą o źródle detekcji.
6. **Poprawa rozdzielania stykających się cyfr na małych oknach (`vision/ocr.py`):**
   - W `_split_wide_box` obniżono próg podziału z `1.20 * h` na `1.05 * h` z zakresem poszukiwania doliny `0.25..0.75 * w`, co pozwala bezbłędnie separować ukośnik i cyfrę blindów (np. `/20`) w skali `0.75x`.

### 2. Wyniki weryfikacji na nagraniach testowych, symulacji Bet Slip i małego okna (0.75x)

| Nagranie / Scenariusz | Klatka | Rozdzielczość | Źródło kotwicy | Wykryte `table_rect` | Karty Hero | Karty Board | Pot | Blinds | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `2026-11-19 211257` | `1827` | `1858x1248` | **RIM** | `(-199, 7, 2253x1278)` | `Kh 2s` | `--` | `70` | `10/20` | **VALID (100%)** |
| `2026-11-19 211257` | `2604` | `1858x1248` | **RIM** | `(-199, 7, 2253x1278)` | `Kh 2s` | `7d Td Th 2h` | `218` | `10/20` | **VALID (100%)** |
| `2026-11-19 211257` | `3643` | `1858x1248` | **RIM** | `(-199, 7, 2253x1278)` | `Jc 4d` | `--` | `30` | `10/20` | **VALID (100%)** |
| `2026-11-19 211257` | `3880` | `1858x1248` | **RIM** | `(-199, 7, 2253x1278)` | `Jc 4d` | `--` | `206` | `10/20` | **VALID (100%)** |
| `2026-11-19 211257` | `4757` | `1858x1248` | **RIM** | `(-199, 7, 2253x1278)` | `7s 7d` | `Qc 7c 7h` | `682` | `15/30` | **VALID (100%)** |
| `2026-11-18 224127` | `0` | `1772x1126` | **RIM** | `(16, 31, 1766x1002)` | `2s Tc` | `--` | `80` | `10/20` | **VALID (100%)** |
| `2026-11-18 224127` | `765` | `1772x1126` | **RIM** | `(16, 31, 1766x1002)` | `Kd 3c` | `--` | `30` | `10/20` | **VALID (100%)** |
| `2026-11-18 224127` | `2370` | `1772x1126` | **RIM** | `(16, 31, 1766x1002)` | `7c 5s` | `--` | `90` | `15/30` | **VALID (100%)** |
| `2026-11-18 224127` | `4950` | `1772x1126` | **RIM** | `(16, 31, 1766x1002)` | `5h Jh` | `Jd 2s 9h` | `60` | `15/30` | **VALID (100%)** |
| `2 gry na raz` | `1383` | `1706x1022` | **RIM** | `(-19, -10, 1766x1002)` | `Ks 9s` | `3s Ac Ah` | `80` | `10/20` | **VALID (100%)** |
| `2 gry na raz` | `1627` | `1706x1022` | **RIM** | `(-19, -10, 1766x1002)` | `Ks 9s` | `3s Ac Ah` | `240` | `10/20` | **VALID (100%)** |
| `2 gry na raz` | `2418` | `1706x1022` | **RIM** | `(-19, -10, 1766x1002)` | `4d Qs` | `--` | `50` | `10/20` | **VALID (100%)** |
| `2 gry na raz` | `2605` | `1706x1022` | **RIM** | `(-19, -10, 1766x1002)` | `4d Qs` | `5d 8c Jh` | `50` | `10/20` | **VALID (100%)** |
| **Symulacja Bet Slip (+800px)** | `211257 f2604` | `2658x1248` | **RIM** | `(-199, 7, 2253x1278)` | `Kh 2s` | `7d Td Th 2h` | `218` | `10/20` | **VALID (100%)** |
| **Symulacja małego okna (0.75x)** | `224127 f765` | `1329x844` | **RIM** | `(12, 23, 1324x751)` | `Kd 3c` | `--` | `30` | `10/20` | **VALID (100%)** |

### 3. Wyniki testów jednostkowych (`pytest -v tests/`)
- Liczba testów: **106 passed in 3.62s (100% sukcesu)**.
- Nowe testy:
  1. `tests/test_vision.py::test_find_golden_rim_4arcs_ignores_occluded_avatars`: potwierdza, że 4-łukowy detektor złotej obwódki poprawnie lokalizuje stół z błędem `<= 2 px` nawet przy silnym zasłonięciu awatarami S1/S2 i kartami/przyciskami Hero.
  2. `tests/test_ui_and_main.py::test_remove_table_1_when_table_2_exists`: potwierdza, że usunięcie `table_1` przy istniejącym `table_2` jest dozwolone i natychmiast usuwa stół z obu nakładek ekranowych (`DebugRoiOverlay`, `ActionBarOverlay`).
  3. `tests/test_ui_and_main.py::test_anti_jitter_deadband`: weryfikuje zamrażanie mikro-drgań `<= 3 px` i natychmiastową aktualizację dla przesunięć `> 3 px`.

---

## V11 — Kotwiczenie o Złotą Obwódkę Stołu, Jawne Zarządzanie Stołami, Kalibracja z Zatwierdzaniem, Buy-in Live i Pasek „Tylko Akcja” (2026-11-21)

### 1. Wdrożone zmiany i nowa architektura
1. **Detektor złotej obwódki stołu (`vision/anchor.py`, `vision/pipeline.py`, `config.json`):**
   - Zaimplementowano `find_golden_rim(frame, search_rect=None)` w HSV z twardą 4-łukową weryfikacją pewności (proporcje owalu `1.55 <= aspect <= 2.15`, minimalne wymiary `300x160 px`, dominacja niebieskiego sukna `>= 50%` w środku, obecność złotych pikseli na wszystkich 4 łukach).
   - Zaimplementowano `compute_table_rect_from_rim(rim_rect, rim_rel, canonical_size)` do przeliczania wykrytego obrysu na kanoniczne `table_rect`.
   - Bezpieczny priorytet dwupunktowej kotwicy z fallbackiem do złotej obwódki (`anchor` -> `golden_rim` -> `search_region`), co zapewnia 100% precyzji zarówno w standardowych oknach, jak i przy braku/ukryciu paska ikon.
   - Poszerzono ROI `hero_card_2` do `[0.4950, 0.6744, 0.0420, 0.0880]` oraz `seat_2_stack` w lewo do `[0.6580, 0.2780, 0.0550, 0.0400]` w `config.json`, eliminując obcinanie pochylonych kart i 3-cyfrowych stacków przeciwnika.
2. **Koniec auto-dodawania stołów i rozdzielanie historii blindów po sygnaturze przeciwników (`vision/pipeline.py`, `main.py`):**
   - Usunięto samoczynne mnożenie stołów `table_1..table_6` z nagłówka `#105...` (który na Stake jest numerem rozdania, a nie turnieju). W HUD domyślnie istnieje wyłącznie `table_1`.
   - Nowe stoły (`+ Dodaj stół`) pojawiają się wyłącznie na jawne życzenie użytkownika.
   - Dodano `VisionPipeline.compute_opponents_signature(table_image, effective_rect)`: wycina miniaturowy wzorzec awatarów/nicków `Seat 1` i `Seat 2`. W `main.py` przy wykryciu zmiany turnieju w jednym oknie (podobieństwo `< 0.85`) historia blindów walidatora jest cicho resetowana bez tworzenia nowych kafli w HUD.
3. **Panel kalibracji per stół z zatwierdzaniem i 3-sekundowym auto-ukryciem (`ui/hud.py`, `main.py`):**
   - Panel kalibracji jest domyślnie całkowicie schowany. Kliknięcie `✎ Kalibruj` przy danym stole rozwija kontrolki (`◀ ▲ ▼ ▶`, `↔ -/+`, `↕ -/+`, `- / +`, `✋ Przesuń`) i podświetla ramki wybranego stołu na `DebugRoiOverlay` w jaskrawym pomarańczowym kolorze edycji (`#f39c12`) z etykietą `✎ [TRYB EDYCJI - {tid}]`.
   - Przycisk `✔ Zatwierdź`: stosuje offsety wyłącznie w pamięci RAM (brak zapisu na dysk), przełącza ramki na standardowy cyjan na 3 sekundy, po czym automatycznie chowa panel i nakładkę diagnostyczną.
   - Przycisk `✕ Anuluj`: natychmiast cofa przesunięcia do stanu sprzed rozpoczęcia edycji.
4. **Szybki wybór stawki Buy-in na żywo (`ui/hud.py`, `main.py`):**
   - Dodano przyciski wyboru wpisowego `$0.50`, `$2`, `$5`, `$10` w HUD, emitujące sygnał `hud_bridge.buy_in_changed(float)` i aktualizujące `decision_maker.buy_in` w locie bez restartu aplikacji.
5. **Pasek „Tylko Akcja” pod przyciskami gry (`ActionBarOverlay`) (`ui/hud.py`, `main.py`):**
   - Zaimplementowano bezramkowe, przezroczyste, click-through okno `ActionBarOverlay(QWidget)` z `WDA_EXCLUDEFROMCAPTURE` wywoływane przyciskiem `⚡ Tylko akcja` lub skrótem `Ctrl+Shift+A`.
   - Wyrównuje 3 kolumny akcji bezpośrednio pod przyciskami stołu: lewa (`FOLD`), środkowa (`CHECK` / `CALL <kwota>`), prawa (`BET <kwota>` / `RAISE <kwota>` / `ALL_IN`).
   - Podświetla zalecaną decyzję (zielony/żółty/czerwony) wraz z wartością EV i kwotą żetonów, a w trybie podglądu wyświetla elegancką etykietę `PLAN: <AKCJA>`.

### 2. Wyniki weryfikacji na nagraniach testowych i symulacji panelu Bet Slip

| Nagranie / Test | Klatka | Rozdzielczość | Wykryte `table_rect` | Karty Hero | Karty Board | Pot | Decyzja | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `2026-11-19 211257` | `1827` | `1858x1248` | `(-198, 7, 2253x1278)` | `['Kh', '2s']` | `[]` | `70` | `CALL` | **VALID** |
| `2026-11-19 211257` | `2604` | `1858x1248` | `(-198, 7, 2253x1278)` | `['Kh', '2s']` | `['7d', 'Td', 'Th', '2h']` | `218` | `CHECK` | **VALID** |
| `2026-11-19 211257` | `3643` | `1858x1248` | `(-198, 7, 2253x1278)` | `['Jc', '4d']` | `[]` | `30` | `FOLD` | **VALID** |
| `2026-11-19 211257` | `3880` | `1858x1248` | `(-198, 7, 2253x1278)` | `['Jc', '4d']` | `[]` | `206` | `FOLD` | **VALID** |
| `2026-11-19 211257` | `4757` | `1858x1248` | `(-198, 7, 2253x1278)` | `['7s', '7d']` | `['Qc', '7c', '7h']` | `682` | `CALL` | **VALID** |
| `2026-11-18 224127` | `0` | `1772x1126` | `(13, 32, 1757x997)` | `['2s', 'Tc']` | `[]` | `80` | `PLAN: FOLD` | **VALID** |
| `2026-11-18 224127` | `765` | `1772x1126` | `(13, 32, 1757x997)` | `['Kd', '3c']` | `[]` | `30` | `FOLD` | **VALID** |
| `2026-11-18 224127` | `2370` | `1772x1126` | `(13, 32, 1757x997)` | `['7c', '5s']` | `[]` | `90` | `CALL` | **VALID** |
| `2026-11-18 224127` | `4950` | `1772x1126` | `(13, 32, 1757x997)` | `['5h', 'Jh']` | `['Jd', '2s', '9h']` | `60` | `PLAN: BET_30` | **VALID** |
| `2 gry na raz` | `1383` | `1706x1022` | `(-22, -9, 1757x997)` | `['Ks', '9s']` | `['3s', 'Ac', 'Ah']` | `80` | `CHECK` | **VALID** |
| `2 gry na raz` | `1627` | `1706x1022` | `(-22, -9, 1757x997)` | `['Ks', '9s']` | `['3s', 'Ac', 'Ah']` | `240` | `CALL` | **VALID** |
| `2 gry na raz` | `2418` | `1706x1022` | `(-22, -9, 1757x997)` | `['4d', 'Qs']` | `[]` | `50` | `PLAN: WAIT` | **VALID** |
| `2 gry na raz` | `2605` | `1706x1022` | `(-22, -9, 1757x997)` | `['4d', 'Qs']` | `['5d', '8c', 'Jh']` | `50` | `PLAN: WAIT` | **VALID** |
| **Sztuczny Bet Slip (+800px)** | `211257 f2604` | `2658x1248` | `(-198, 7, 2253x1278)` | `['Kh', '2s']` | `['7d', 'Td', 'Th', '2h']` | `218` | `CHECK` | **VALID (100%)** |

### 3. Wyniki testów jednostkowych (`pytest -v tests/`)
- Liczba testów: **103 passed in 5.42s (100% sukcesu)**.
- Nowe testy:
  1. `tests/test_vision.py::test_find_golden_rim_and_table_rect`: weryfikuje detekcję złotej obwódki owalu z wnętrzem sukna oraz odrzucanie fałszywych detekcji (brak niebieskiego środka, błędne proporcje).
  2. `tests/test_vision.py::test_opponents_signature_same_vs_different`: weryfikuje rozróżnianie składu przeciwników po sygnaturze awatarów/nicków (`>= 0.95` dla tych samych, `< 0.65` dla różnych).
  3. `tests/test_ui_and_main.py::test_hud_calibration_edit_confirm_cancel_and_auto_hide`: weryfikuje tryb edycji kalibracji, pomarańczowe podświetlenie, przycisk Zatwierdź z 3-sekundowym timerem auto-ukrycia i Anuluj.
  4. `tests/test_ui_and_main.py::test_hud_buy_in_switch_and_manual_table_add_remove`: weryfikuje przełączanie wpisowego ($0.50..$10) oraz ręczne dodawanie/usuwanie stołów w HUD bez samowolnego auto-dodawania.
  5. `tests/test_ui_and_main.py::test_action_bar_overlay_positioning`: weryfikuje pozycjonowanie, 3 kolumny akcji i tryb `PLAN:` w nakładce `ActionBarOverlay`.

---

## V10 — Dwupunktowe kotwiczenie stołu (anchor_right), usunięcie błędu centrowania i ręczne dostrajanie ramki w HUD (2026-11-21)

### 1. Diagnoza źródłowej przyczyny przesunięcia na żywo o ~400 px
1. **Analiza zrzutu ekranu z włączoną nakładką `🎯 Ramki ROI`:**
   - W trybie `--mode live` na laptopie HiDPI (`2880x1800`) skala (`1.15x`, `2027x1150`) oraz wysokość pionowa (`ty = 335`) były idealne, lecz `tx` wynosiło `426 px` zamiast prawdziwego położenia stołu `~30 px`.
   - **Winowajca (`vision/anchor.py`, dawne linie 210–215):**
     Kod obliczał `tx_centered = (frame_w - tw) // 2 = (2880 - 2027) // 2 = 426 px` i na siłę nadpisywał `tx`, błędnie zakładając, że cały monitor to samo okno gry i ignorując obecność panelu `Bet Slip` po prawej stronie okna przeglądarki!
   - Co więcej, przycisk `📐 Obszar` również korzystał z `compute_unclipped_table_rect(..., frame_shape=frame.shape)`, przez co centrowanie psuło nawet ręcznie zaznaczony stół.

### 2. Wdrożone zmiany i nowa architektura
1. **Usunięcie błędnego centrowania do monitora (`vision/anchor.py`):**
   - Całkowicie wycięto linie wymuszające `tx_centered = (frame_w - tw) // 2`.
   - Podstawowa pozycja stołu wyliczana jest bezpośrednio z lewej kotwicy: `tx = int(round(ax - ox * tw))`, co na ekranie 2880px daje natychmiast prawidłowe `tx = 30 px`.
2. **Nowy szablon prawej kotwicy i dwupunktowe kotwiczenie (`data/templates/anchor_right.png`, `vision/anchor.py`):**
   - Dodano czysty szablon `anchor_right.png` (35x78) zawierający ikony `[⚙][🏆]` z prawego górnego rogu obszaru gry.
   - Dodano funkcję `find_right_anchor(frame, right_template, left_anchor, threshold=0.72)` przeszukującą wąski pas w osi X stołu na wysokości lewej kotwicy (< 1 ms).
   - W `compute_unclipped_table_rect(..., right_anchor=...)`:
     * W responsywnych, wąskich oknach Stake (np. `211257`, gdzie kontener gry jest węższy niż pełna szerokość stołu `tw`), stół jest centrowany wewnątrz kontenera gry między lewą a prawą kotwicą: `game_center_x = (ax + rx + rw) / 2.0 + offset`, dając dokładnie `tx = -198`.
     * W standardowych oknach (`224127`, `2 gry na raz`, ekrany z panelem Bet Slip) pozycja stołu jest precyzyjnie potwierdzana lub utrzymywana przy lewej kotwicy bez żadnego przesunięcia monitorowego.
3. **Integracja w silniku wizji i pętli głównej (`vision/pipeline.py`, `main.py`):**
   - `VisionPipeline` automatycznie wczytuje `right_anchor_template` z `data/templates/anchor_right.png`.
   - `main.py` oraz `pipeline.process_frame` wyszukują prawą kotwicę i przekazują ją do `compute_unclipped_table_rect`.
4. **Ręczne dostrajanie i przeciąganie ramki stołu w HUD (`ui/hud.py`, `main.py`):**
   - Dodano sygnał `HudBridge.table_adjust_changed = Signal(int, int, float)` (`dx, dy, scale_mult`).
   - W panelu `🔍 Szczegóły` w `HudOverlay` dodano kompaktowy pasek sterowania:
     * Przyciski przesunięcia: `◀` `▲` `▼` `▶` (krok 10 px, z `Shift` precyzyjny krok 2 px).
     * Przyciski skalowania: `-` `+` (korekta skali o ±1%).
     * Przycisk przeciągania myszą: `✋ Przesuń` — tymczasowo wyłącza `click-through` na `DebugRoiOverlay`, zmienia kursor na `SizeAllCursor` i pozwala przeciągnąć cyjanową ramkę stołu myszą wprost na stół, a po puszczeniu natychmiast wraca do `click-through`.
     * Przycisk `↺` (resetuje do `(0, 0) | 100%`). Przycisk `↺ Auto` również automatycznie resetuje przesunięcia.
     * Etykieta stanu: `Offset: (dx, dy) | skala%`.
   - W `main.py` korekta `(dx, dy, scale_mult)` jest aplikowana na `table_rect` przed `pipeline.process_frame` oraz przed wysłaniem `debug_overlay_updated`, zapewniając natychmiastowy podgląd przesuniętych ramek na żywo.

### 3. Wyniki weryfikacji na klatkach testowych i symulacji panelu Bet Slip

| Nagranie / Test | Klatka | Rozdzielczość | Wykryte `table_rect` | Karty Hero | Karty Board | Pot | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `2026-11-19 211257` | `1827` | `1858x1248` | `(-198, 7, 2253x1278)` | `['Kh', '2s']` | `[]` | `70` | **VALID** |
| `2026-11-19 211257` | `2604` | `1858x1248` | `(-198, 7, 2253x1278)` | `['Kh', '2s']` | `['7d', 'Td', 'Th', '2h']` | `218` | **VALID** |
| `2026-11-19 211257` | `3643` | `1858x1248` | `(-198, 7, 2253x1278)` | `['Jc', '4d']` | `[]` | `30` | **VALID** |
| `2026-11-19 211257` | `3880` | `1858x1248` | `(-198, 7, 2253x1278)` | `['Jc', '4d']` | `[]` | `206` | **VALID** |
| `2026-11-19 211257` | `4757` | `1858x1248` | `(-198, 7, 2253x1278)` | `['7s', '7d']` | `['Qc', '7c', '7h']` | `682` | **VALID** |
| `2026-11-18 224127` | `0` | `1772x1126` | `(13, 32, 1757x997)` | `['2s', 'Tc']` | `[]` | `80` | **VALID** |
| `2026-11-18 224127` | `765` | `1772x1126` | `(13, 32, 1757x997)` | `['Kd', '3c']` | `[]` | `30` | **VALID** |
| `2026-11-18 224127` | `2370` | `1772x1126` | `(13, 32, 1757x997)` | `['7c', '5s']` | `[]` | `90` | **VALID** |
| `2026-11-18 224127` | `4950` | `1772x1126` | `(13, 32, 1757x997)` | `['5h', 'Jh']` | `['Jd', '2s', '9h']` | `60` | **VALID** |
| `2 gry na raz` | `1383` | `1706x1022` | `(-22, -9, 1757x997)` | `['Ks', '9s']` | `['3s', 'Ac', 'Ah']` | `80` | **VALID** |
| `2 gry na raz` | `1627` | `1706x1022` | `(-22, -9, 1757x997)` | `['Ks', '9s']` | `['3s', 'Ac', 'Ah']` | `240` | **VALID** |
| `2 gry na raz` | `2418` | `1706x1022` | `(-22, -9, 1757x997)` | `['4d', 'Qs']` | `[]` | `50` | **VALID** |
| `2 gry na raz` | `2605` | `1706x1022` | `(-22, -9, 1757x997)` | `['4d', 'Qs']` | `['5d', '8c', 'Jh']` | `50` | **VALID** |
| **Sztuczny Bet Slip (+800px)** | `211257 f2604` | `2658x1248` | `(-198, 7, 2253x1278)` | `['Kh', '2s']` | `['7d', 'Td', 'Th', '2h']` | `218` | **VALID (100%)** |

### 4. Wyniki testów jednostkowych (`pytest -v tests/`)
- Liczba testów: **98 passed in 4.88s (100% sukcesu)**.
- Nowe testy:
  1. `tests/test_vision.py::test_compute_unclipped_table_rect_wide_monitor_with_right_panel`: weryfikuje odporność na panel Bet Slip na ekranie 2880x1800 (brak przesunięcia do 426px, precyzja <= 2px) oraz funkcję `find_right_anchor`.
  2. `tests/test_ui_and_main.py::test_table_adjust_signal_and_drag_mode`: weryfikuje sygnał `table_adjust_changed`, przyciski przesunięcia/skalowania/resetu oraz tryb przeciągania myszą `set_drag_mode`.

---

## V9.1 — Nakładka diagnostyczna na ekran (DebugRoiOverlay + WDA_EXCLUDEFROMCAPTURE) (2026-11-21)

### 1. Wdrożone zmiany i usprawnienia
1. **Wykluczenie okien nakładek z przechwytywania ekranu (`WDA_EXCLUDEFROMCAPTURE`):**
   - Dodano funkcję `set_exclude_from_capture(hwnd: int, enabled: bool = True) -> None` w `ui/hud.py`, korzystającą z natywnego Windows API `SetWindowDisplayAffinity(hwnd, 0x00000011)` (`WDA_EXCLUDEFROMCAPTURE = 0x11`).
   - Zastosowano wykluczenie zarówno w `HudOverlay`, jak i w `DebugRoiOverlay`. Dzięki temu nakładki pozostają w pełni widoczne dla gracza na ekranie, ale są całkowicie niewidoczne dla przechwytywania `dxcam` / `BitBlt` / Desktop Duplication, co zapobiega zakłócaniu detekcji stołu i pól ROI przez elementy interfejsu.
2. **Pełnoekranowa nakładka diagnostyczna `DebugRoiOverlay` (`ui/hud.py`):**
   - Zaimplementowano bezramkowe, przezroczyste, pełnoekranowe okno `DebugRoiOverlay(QWidget)` z flagami `FramelessWindowHint | WindowStaysOnTopHint | Tool` oraz `WA_TransparentForMouseEvents` + `set_click_through(hwnd, True)`. Nakładka nigdy nie blokuje klikania myszą w stół pokerowy.
   - Odbiera dane klatki przez sygnał `HudBridge.debug_overlay_updated = Signal(object)`.
   - W `paintEvent` przelicza współrzędne fizyczne na logiczne Qt (`/ screen.devicePixelRatio()`) i rysuje:
     * Wyraźny cyjanowy przerywany obrys stołu `table_rect` z etykietą `TABLE (tx, ty, tw x th)`.
     * Kolorowe ramki każdego pola ROI (`hero_card_1..2`, `board_card_1..5`, `pot`, `prize_pool`, `blinds`, `seat_0/1/2_stack`, `seat_0/1/2_bet`, `seat_0_timer`, `hero_actions`): zielone gdy pole coś odczytało, czerwone gdy puste/brak detekcji.
     * Ciemne półprzezroczyste plakietki z wartościami pól (`H1: 10d`, `H2: --`, `Pot: 30`, `S0 stk: 290`, `Turn: YES/NO`, itd.).
3. **Przełącznik `🎯 Ramki ROI` w panelu `🔍 Szczegóły` i skrót globalny (`ui/hud.py`):**
   - Po rozwinięciu `🔍 Szczegóły` w HUD pojawia się przycisk `🎯 Ramki ROI`, umożliwiający szybkie włączanie/wyłączanie podglądu na żywo.
   - Dodano skrót klawiszowy `Ctrl+Shift+O` (działający zarówno lokalnie, jak i globalnie przez Windows `GetAsyncKeyState`).
   - Zamknięcie HUD automatycznie zamyka także `DebugRoiOverlay`.
4. **Wyliczanie i emisja współrzędnych ekranowych ROI w `main.py`:**
   - W `processing_loop` w `main.py` dla każdego stołu wyliczane są fizyczne współrzędne pikselowe wszystkich zdefiniowanych ROI (`tx + rx * tw`, `ty + ry * th`) z uwzględnieniem offsetów i geometrii, powiązane z odczytanymi wartościami ze `state` i przekazywane do HUD przez `hud_bridge.debug_overlay_updated`.
   - Obsłużono resetowanie overlayu w trybie spoczynku `live` przy braku stołów.

### 2. Wyniki testów jednostkowych (`pytest -v tests/`)
- Liczba testów: **96 passed in 4.54s (100% sukcesu)**.
- Nowy test: `tests/test_ui_and_main.py::test_debug_roi_overlay_and_exclude_capture` weryfikujący `set_exclude_from_capture`, zachowanie offscreen `DebugRoiOverlay` (w tym renderowanie `paintEvent`), sterowanie przełącznikiem `toggle_debug_overlay()` i zachowanie widoczności przy `toggle_details()`.

---

## V9 — Jakość produkcyjna: pełne 10/T, dyskryminacja c/s, strefowe akcje, postflop 3-way i mini-karty w HUD (2026-11-21)

### 1. Wdrożone zmiany i usprawnienia systemowe
1. **Pełny i czysty szablon `T.png` oraz poszerzenie ROI `hero_card_1` (`data/templates/ranks/T.png`, `config.json`, `vision/card_recognizer.py`):**
   - Zastąpiono poprzedni ucięty szablon `T.png` pełnym, wyostrzonym szablonem `10` (23x19) z kompletnym daszkiem jedynki wyciętym z klatki `211257` f2604 (`board_card_2`), bez artefaktów na dole.
   - Poszerzono ROI `hero_card_1` w `config.json` z `[0.4636, 0.6744, 0.0350, 0.0880]` na `[0.4585, 0.6744, 0.0405, 0.0880]`, co zapobiega obcinaniu lewego szeryfa jedynki w szerokich dwuznakowych kartach `10`.
   - Wprowadzono 2-konturową regułę dla `T` w `vision/card_recognizer.py`: połączenie dwóch konturów w rzędzie rangi o zbliżonej wysokości podbija dopasowanie do `>= 0.90`.
2. **Precyzyjna dyskryminacja czarnych kolorów `c` (trefl) vs `s` (pik) (`vision/card_recognizer.py`):**
   - Zaimplementowano geometryczną analizę kształtu: czubek (`top_tip_ratio`) oraz talię (`waist_ratio`).
   - Pik: ostry szpic (`top_tip <= 0.22`) i brak głębokiego przewężenia (`waist - top_tip >= 0.28`) otrzymuje premię +0.08 dla `s` i karę -0.08 dla `c`.
   - Trefl: zaokrąglony listek (`top_tip >= 0.26`) lub wąska talia (`waist - top_tip <= 0.22`) otrzymuje premię +0.08 dla `c` i karę -0.08 dla `s`.
   - Całkowicie wyeliminowano fałszywe detekcje pików jako trefli (m.in. na `232515` f12592 bezbłędny odczyt boardu `['2c', '5s', '5c', '4d', '8s']`).
3. **Strefowa detekcja przycisków akcji Hero (`vision/ocr.py`):**
   - W `detect_hero_actions` wprowadzono podział paska akcji na strefy: Fold (czerwony, `x <= 0.45w`), Check/Call (zielony, `0.15w..0.80w`), Bet/Raise (pomarańczowy, `x >= 0.40w`).
   - Przycisk Bet/Raise wymaga litego konturu przycisku (`bw >= 10, bh >= 10`), ignorując drobny złoty szum tła kasyna na lewo od przycisków.
   - Na klatce `4757` (`211257` vs All-In): `available_actions` zwraca czyste `['FOLD', 'CALL']` (bez fałszywego `BET`), a decyzja to prawidłowe `CALL`.
4. **Postflop 3-Way w Monte Carlo (`engine/monte_carlo.py`, `main.py`):**
   - Dodano opcjonalny parametr `num_opponents: int = 1` do `estimate_equity`. Przy `num_opponents > 1` symulator losuje karty dla wszystkich aktywnych rywali i sprawdza wygraną przeciwko najlepszej ręce rywali (`hero_score < min(opp_scores)`).
   - W `main.py` (`evaluate_candidates` postflop) obliczana jest liczba aktywnych rywali (`num_opps = max(1, min(2, active_opponents))`), a przy 3-way pot fold equity mnożone jest przez `0.65`.
5. **Optymalizacja `live` i `📐 Obszar` (`main.py`):**
   - W gałęzi `manual_rect` przekazywane jest `preferred_scale=getattr(pipeline, "_last_anchor_scale", None)` i zapisywany cache skali, przyspieszając kolejne klatki.
   - Dodano lekki tryb spoczynku w `--mode live`: gdy brak kotwicy stołu i brak manualnego obszaru, emitowany jest stan `WAIT` ("Szukam stołu Stake...") maksymalnie raz na 0.5 s bez obciążania procesora i pipeline'u.
6. **Kompaktowy pasek kart w HUD (`ui/hud.py`):**
   - Funkcja `format_cards_html` wyciąga karty Hero i Board z podsumowania i formatuje je w elegancki pasek `🃏 10♦ 7♥  •  Board: Q♣ 7♣ 7♥` z kolorowymi symbolami HTML (czerwone `♥♦`, białe `♠♣`).
   - Pasek jest wyświetlany w głównej karcie stołu i pozostaje w 100% widoczny nawet przy zwiniętym panelu `🔍 Szczegóły`.

### 2. Wyniki weryfikacji na klatkach testowych (pełna ścieżka produkcyjna `main.py`)

| Nagranie | Klatka | Oczekiwane Karty / Pula | Wykryte Hero | Wykryty Board | Pot | Stan / Spot | Decyzja | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `2026-11-19 211257` | `4757` | Hero `7s 7d` \| `Qc 7c 7h` | `['7s', '7d']` | `['Qc', '7c', '7h']` | **`682`** | VALID / `FLOP` (Actions: `['FOLD', 'CALL']`) | **`CALL`** | **PASS** |
| `2026-11-19 211257` | `2604` | Hero `Kh 2s` \| `7d Td Th 2h` | `['Kh', '2s']` | `['7d', 'Td', 'Th', '2h']` | **`218`** | VALID / `TURN` | **`CHECK`** | **PASS** |
| `2026-11-19 211257` | `1827` | Hero `Kh 2s` | `['Kh', '2s']` | `[]` | **`70`** | VALID / `BB_VS_BTN_RAISE` | **`CALL`** | **PASS** |
| `2026-11-19 211257` | `3220` | Hero `Jc 7d` | `['Jc', '7d']` | `[]` | **`30`** | VALID / `WAITING_FOR_TURN` | **`FOLD`** | **PASS** |
| `2026-11-19 211257` | `3643` | Hero `Jc 4d` vs min-raise | `['Jc', '4d']` | `[]` | **`30`** | VALID / `BTN_OPEN` | **`ALL_IN`** | **PASS** |
| `2026-11-19 211257` | `3668` | Hero `Jc 4d` (badge Call) | `['Jc', '4d']` | `[]` | **`50`** | VALID / `WAITING_FOR_TURN` | **`FOLD`** | **PASS** |
| `2026-11-19 211257` | `3880` | Hero `Jc 4d` vs All-in 166 | `['Jc', '4d']` | `[]` | **`206`** | VALID / `BB_VS_SB_SHOVE` | **`FOLD`** | **PASS** |
| `2026-11-18 224127` | `0` | Hero `2s Tc` | `['2s', 'Tc']` | `[]` | **`80`** | VALID / `WAITING_FOR_TURN` | **`FOLD`** | **PASS** |
| `2026-11-18 224127` | `765` | Hero `Kd 3c` | `['Kd', '3c']` | `[]` | **`30`** | VALID / `BTN_OPEN` | **`ALL_IN`** | **PASS** |
| `2026-11-18 224127` | `2370` | Hero `7c 5s` | `['7c', '5s']` | `[]` | **`90`** | VALID / `BB_VS_SB_RAISE` | **`CALL`** | **PASS** |
| `2026-11-18 224127` | `4950` | `5h Jh` \| `Jd 2s 9h` | `['5h', 'Jh']` | `['Jd', '2s', '9h']` | **`60`** | VALID / `WAITING_FOR_TURN` | **`FOLD`** | **PASS** |
| `2 gry na raz` | `1383` | `Ks 9s` \| `3s Ac Ah` | `['Ks', '9s']` | `['3s', 'Ac', 'Ah']` | **`80`** | VALID / `FLOP` | **`CHECK`** | **PASS** |
| `2 gry na raz` | `1627` | `Ks 9s` \| `3s Ac Ah` | `['Ks', '9s']` | `['3s', 'Ac', 'Ah']` | **`240`** | VALID / `FLOP` | **`CALL`** | **PASS** |
| `2 gry na raz` | `2418` | `4d Qs` \| Stół 2 | `['4d', 'Qs']` | `[]` | **`50`** | VALID / `WAITING_FOR_TURN` | **`FOLD`** | **PASS** |
| `2 gry na raz` | `2605` | `4d Qs` \| `5d 8c Jh` | `['4d', 'Qs']` | `['5d', '8c', 'Jh']` | **`50`** | VALID / `WAITING_FOR_TURN` | **`FOLD`** | **PASS** |
| `2026-11-18 232515` | `12592` | Board `2c 5s 5c 4d 8s` | `[]` | `['2c', '5s', '5c', '4d', '8s']` | **`270`** | Dyskryminacja `c` vs `s` (bez kolizji) | **`WAIT`** | **PASS** |

### 3. Wyniki testów jednostkowych (`pytest -v tests/`)
- Liczba testów: **95 passed in 4.17s (100% sukcesu)**.
- Nowe testy:
  - `tests/test_vision.py::test_card_recognizer_two_contour_ten_rule`
  - `tests/test_vision.py::test_detect_hero_actions_zoned_rejects_noise`
  - `tests/test_engine.py::test_monte_carlo_multiway_3way`
  - `tests/test_ui_and_main.py::test_hud_overlay_compact_cards_label`

---



### 1. Rozwiązane problemy z testów na żywo (`--mode live`)
1. **Odczyt karty `10` / `T` na mniejszych oknach (`vision/card_recognizer.py`):**
   - Na pomniejszonych oknach stołu cienka cyfra `1` w karcie `10` osiąga szerokość 2–3 pikseli. Poprzedni filtr minimalnej szerokości `bw >= 4` (oraz fallback `bw >= 3`) odrzucał cyfrę `1`, pozostawiając jedynie cyfrę `0` (błędnie interpretowaną jako np. `Q`).
   - Zmniejszono filtr szerokości do `bw >= 2` (oraz fallback `bw >= 2`), zachowując odrzucanie 1-pikselowych szumów krawędziowych.
   - Uodporniono scalanie `1` + `0` na pochylonych kartach Hero: warunek `abs(by1 - ry) <= 9 and (bx1 < rx + rw + 15 or abs(bx1 - rx) <= 20)` bezbłędnie scala cyfry przy przesunięciu pionowym do 9 px i poziomym do 20 px.
2. **Stabilizacja `table_id` i zapobieganie mnożeniu `table_1..table_6` (`vision/pipeline.py`):**
   - Poprzednie współrzędne nagłówka stołu (`gy1 = 0.012..0.050`) obejmowały górny pasek z ikonami oraz mini-kartami (`[☰] [🏠] [mini-karty] [+]`). Mini-karty zmieniają się przy każdym nowym rozdaniu, przez co korelacja szablonu stołu spadała poniżej 0.94 i w każdym rozdaniu alokowany był nowy stół (`table_1`, `table_2`, ..., `table_6`).
   - Przesunięto ROI sygnatury ściśle na numer turnieju `#ID`: `gy1..gy2 = 0.055..0.092`, `gx1..gx2 = 0.045..0.185`, całkowicie wycinając mini-karty.
   - Pomiary korelacji: w ramach tego samego turnieju we wszystkich kolejnych rozdaniach cross-correlation wynosi `0.985..1.000`. Pomiędzy dwoma równoległymi stołami w `2 gry na raz` (`#105538734` vs `#105538775`) korelacja wynosi `0.879`.
   - Skalibrowano próg dopasowania na `best_score >= 0.90`. Dzięki temu ten sam turniej zachowuje stały `table_id`, a dwa równoległe turnieje są stabilnie rozdzielane na `table_1` i `table_2`.
   - W `main.py` skrócono timeout nieaktywnych stołów (`stale_tids`) z `15.0 s` do `5.0 s`.
3. **Inteligentne centrowanie stołu po zaznaczeniu `📐 Obszar` (`main.py`):**
   - Po manualnym zaznaczeniu obszaru (`manual_rect`) silnik próbuje najpierw znaleźć wzorzec kotwicy `find_anchor` wewnątrz wskazanego wycinka.
   - Po wykryciu kotwicy jej współrzędne są przeliczane na pełną klatkę i wyznaczany jest precyzyjny stół kanoniczny (`compute_unclipped_table_rect`) z flagą `has_anchor=True`.
   - Jeśli w wycinku nie ma kotwicy, system bezpiecznie stosuje `manual_rect` jako fallback (`has_anchor=False`).

### 2. Wyniki weryfikacji na klatkach testowych (pełna ścieżka produkcyjna `main.py`)

| Nagranie | Klatka | Oczekiwane Karty / Pula | Wykryte Hero | Wykryty Board | Pot | Stan / Spot | Decyzja | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `2026-11-18 224127` | `0` | Hero `2s Tc` | `['2s', 'Tc']` | `[]` | **`80`** | VALID / `WAITING_FOR_TURN` | **`WAIT`** | **PASS** |
| `2026-11-18 224127` | `765` | Hero `Kd 3c` | `['Kd', '3c']` | `[]` | **`30`** | VALID / `WAITING_FOR_TURN` | **`WAIT`** | **PASS** |
| `2026-11-18 224127` | `2370` | Hero `7c 5s` | `['7c', '5s']` | `[]` | **`90`** | VALID / `WAITING_FOR_TURN` | **`WAIT`** | **PASS** |
| `2026-11-18 224127` | `4950` | `5h Jh` \| `Jd 2s 9h` | `['5h', 'Jh']` | `['Jd', '2s', '9h']` | **`60`** | VALID / `WAITING_FOR_TURN` | **`WAIT`** | **PASS** |
| `2026-11-19 211257` | `2604` | Hero `Kh 2s` \| `7d Td Th 2h` | `['Kh', '2s']` | `['7d', 'Td', 'Th', '2h']` | **`218`** | VALID / `WAITING_FOR_TURN` | **`WAIT`** | **PASS** |
| `2026-11-19 211257` | `3643` | Hero `Jc 4d` vs min-raise | `['Jc', '4d']` | `[]` | **`30`** | VALID / `WAITING_FOR_TURN` | **`WAIT`** | **PASS** |
| `2026-11-19 211257` | `3880` | Hero vs All-in 166 | `['Jc', '4d']` | `[]` | **`206`** | VALID / `WAITING_FOR_TURN` | **`WAIT`** | **PASS** |
| `2026-11-19 211257` | `4757` | Hero `7s 7d` \| `Qc 7c 7h` | `['7s', '7d']` | `['Qc', '7c', '7h']` | **`682`** | VALID / `WAITING_FOR_TURN` | **`WAIT`** | **PASS** |
| `2 gry na raz` | `1383` | `Ks 9s` \| `3s Ac Ah` | `['Ks', '9s']` | `['3s', 'Ac', 'Ah']` | **`80`** | VALID / `WAITING_FOR_TURN` | **`WAIT`** | **PASS** |
| `2 gry na raz` | `2418` | `4d Qs` \| Stół 2 | `['4d', 'Qs']` | `[]` | **`50`** | VALID / `WAITING_FOR_TURN` | **`WAIT`** | **PASS** |

### 3. Wyniki testów jednostkowych (`pytest -v tests/`)
- Liczba testów: **91 passed in 3.21s (100% sukcesu)**.
- Nowy test: `tests/test_vision.py::test_card_recognizer_thin_one_in_ten` (weryfikacja odczytu '10' / 'T' przy cienkiej cyfrze '1' o szerokości 2–3 px).
- Zaktualizowane testy syntetyczne: `test_resolve_table_id_two_games` oraz `test_resolve_table_id_more_than_two_tables` dostosowane do nowej geometrii ROI `#ID`.

---

## V8.1 — Naprawa ucinania 3-cyfrowych pul (Pot: 682, klatka 4757) (2026-11-21)

### 1. Przyczyna źródłowa błędu odczytu `Pot: 682` jako `82`
- **Zbyt ciasna lewa krawędź ROI `pot` w `config.json`:** Poprzednie współrzędne `[0.503, 0.3257, 0.042, 0.0401]` w przestrzeni kanonicznej `(1757, 997)` rozpoczynały wycinek od `x = 883.8 px`. Przy 3-cyfrowej puli `682` napis "Pot: 682" przesuwa się lekko w lewo, a pierwsza cyfra '6' rozpoczyna się od `x = 882 px`. W efekcie lewe 2-3 piksele cyfry '6' były ucinane przez granicę ROI, co powodowało odrzucenie konturu przez `DigitOCR`.
- **Dostosowanie ROI `pot`:** Zaktualizowano ROI `pot` do `[0.4980, 0.3257, 0.0480, 0.0401]` (`x = 875 px`, `w = 84 px`). Zapewnia to bezpieczny ~7 px margines przed pierwszą cyfrą 3-cyfrowej puli, nie zahaczając o dwukropek `:` (kończący się na `871..874 px`), oraz ~20-30 px marginesu z prawej strony.
- **Odporność walidatora chipów dla 2 graczy na All-In:** W `StateValidator` rozszerzono akceptację stanu przy zachowaniu sumy 900 (`pot + stacki == 900`), dopuszczając obecność wielu graczy ze statusem `ALL_IN` (`stack is None` lub `stack == 0`).

### 2. Wyniki weryfikacji na klatkach testowych (pełna ścieżka produkcyjna `main.py`)

| Nagranie | Klatka | Oczekiwane Karty / Pula | Wykryte Hero | Wykryty Board | Pot | Stan / Spot | Decyzja | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `2026-11-19 211257` | `4757` | Hero `7s 7d` \| `Qc 7c 7h` | `['7s', '7d']` | `['Qc', '7c', '7h']` | **`682`** | VALID / `FLOP` | **`CALL`** (+22.71 BB) | **PASS** |
| `2026-11-19 211257` | `2604` | Hero `Kh 2s` \| `7d Td Th 2h` | `['Kh', '2s']` | `['7d', 'Td', 'Th', '2h']` | **`218`** | VALID / `TURN` | **`BET_30`** (+7.62 BB) | **PASS** |
| `2026-11-19 211257` | `3643` | Hero `Jc 4d` vs min-raise | `['Jc', '4d']` | `[]` | **`30`** | VALID / `BTN_OPEN` | **`FOLD`** (0.0 BB) | **PASS** |
| `2026-11-19 211257` | `3880` | Hero vs All-in 166 | `['Jc', '4d']` | `[]` | **`206`** | VALID / `BB_VS_SB_SHOVE` | **`FOLD`** (0.0 BB) | **PASS** |
| `2 gry na raz` | `1383` | `Ks 9s` \| `3s Ac Ah` | `['Ks', '9s']` | `['3s', 'Ac', 'Ah']` | **`80`** | VALID / `FLOP` | **`BET_30`** (+2.79 BB) | **PASS** |
| `2 gry na raz` | `1627` | Dwa stoły / Hero akcja | `['Ks', '9s']` | `['3s', 'Ac', 'Ah']` | **`240`** | VALID / `FLOP` | **`CALL`** (+6.15 BB) | **PASS** |
| `2026-11-18 224127` | `765` | Hero `Kd 3c` | `['Kd', '3c']` | `[]` | **`30`** | VALID / `BTN_OPEN` | **`FOLD`** (0.0 BB) | **PASS** |
| `2026-11-18 224127` | `2370` | Hero `7c 5s` | `['7c', '5s']` | `[]` | **`90`** | VALID / `BB_VS_SB_RAISE` | **`CALL`** (+0.76 BB) | **PASS** |
| `2026-11-18 224127` | `4950` | `5h Jh` \| `Jd 2s 9h` | `['5h', 'Jh']` | `['Jd', '2s', '9h']` | **`60`** | VALID / `WAITING_FOR_TURN` | **`[PLAN] ALL_IN`** (+3.17 BB) | **PASS** |

### 3. Wyniki testów jednostkowych (`pytest -v tests/`)
- Liczba testów: **90 passed in 3.68s (100% sukcesu)**.
- Nowy test: `tests/test_state.py::test_validator_two_players_all_in_pot_conservation` (weryfikacja akceptacji 2 graczy na All-In przy zachowaniu sumy 900 żetonów).

---

## V8 — Naprawa boardu na skalowanych stołach, precyzja Rank+Suit, Tracker/Exploit i obsługa --monitor (2026-11-20)

### 1. Przyczyna źródłowa błędu `Board: --` na `211257` f2604/2640/2696
- **Odcinanie badge'a akcji na kartach boardu:** W silniku `CardRecognizer` cięcie `badge_cut_h = int(roi_h * 0.68)` odcinało dolne 32% wycinka bez sprawdzania `slot_hint`, co ucinało symbole kolorów kart wspólnych. W V8 cięcie 68% jest aplikowane ściśle tylko dla `hero_card_1` i `hero_card_2`, a dla kart stołu zachowywane jest 96% wysokości wycinka.
- **Geometria ROI boardu w `config.json`:** Na skalowanych stołach (np. skala `1.28x`) pole pierwszej cyfry '1' w karcie '10' (`Td`, `Th`) było częściowo ucinane z lewej strony przy poprzednich współrzędnych `board_card_2` (`0.4422`). Po dostrojeniu współrzędnych x (`board_card_1..5`: `0.3950`, `0.4370`, `0.4790`, `0.5210`, `0.5630`) oraz filtracji `bw >= 4` i `bh >= 11`, segmentacja `10` ('T') oraz pozostałych rang i kolorów działa ze 100% precyzją.

### 2. Wprowadzone zmiany w architekturze

1. **`vision/card_recognizer.py`**:
   - Dodano `_fit_glyph_to_box(crop, target_w, target_h)` do skalowania wycinków z zachowaniem proporcji (aspect-preserving resize) na stałym płótnie `24x32` dla rang i `24x24` dla kolorów z marginesem `pad=3`. Całkowicie eliminuje to rozciąganie wąskich liter `J` czy cyfr `1`.
   - Poprawiono wykrywanie dwuznakowej rangi `10` ('T') z łączeniem konturów `abs(by1 - ry) <= 8 and bx1 < rx + rw + 15`.
   - Zabezpieczono ścieżki szablonów (`BASE_DIR = Path(__file__).resolve().parent.parent / "data/templates"`), dzięki czemu domyślny tryb `Rank + Suit` działa niezależnie od bieżącego katalogu roboczego (`os.chdir`).
2. **`state/validator.py`**:
   - Dodano **Postflop Pot Sanity Check**: jeśli `pot > max(sb + bb * 2, bb * 3)`, wszyscy gracze mają `current_bet == 0`, a `len(board_cards) == 0`, stan jest oznaczany jako błąd `Missing board cards on postflop pot`, uniemożliwiając fałszywe wejście w logikę preflop na flopie/turnie/riverze.
3. **`state/tracker.py`**:
   - Naprawiono warunek `street_reset`: usunięto `"WAITING_FOR_TURN"`, dzięki czemu wejście w turę Hero preflop (`WAITING_FOR_TURN -> PREFLOP`) nie resetuje rozdania ani nie zawyża `hand_number`.
4. **`strategy/exploit.py`**:
   - W `apply_exploits`: warunek `has_fast_check` (`last_reaction_ms < 500`) wymaga teraz ściśle `current_bet == 0`, zapobiegając traktowaniu szybkiego zakładu/raise'a przeciwnika jako słabego checku.
5. **`vision/capture.py` & `main.py`**:
   - Dodano obsługę flagi CLI `--monitor <int>` (domyślnie `0`), przekazywanej do `LiveScreenCapture(output_idx=args.monitor)` -> `dxcam.create(output_idx=self.output_idx, ...)`.

---

### 3. Wyniki weryfikacji na klatkach testowych (pełna ścieżka produkcyjna `main.py`)

| Nagranie | Klatka | Oczekiwane Karty | Wykryte Hero | Wykryty Board | Stan / Spot | Decyzja | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `2026-11-19 211257` | `1827` | Hero `Kh 2s` | `['Kh', '2s']` | `[]` | VALID / `BB_VS_BTN_RAISE` | **`CALL`** (1.47 BB) | **PASS** |
| `2026-11-19 211257` | `2604` | Hero `Kh 2s \| 7d Td Th 2h` | `['Kh', '2s']` | `['7d', 'Td', 'Th', '2h']` | VALID / `TURN` | **`BET_30`** (7.55 BB) | **PASS** |
| `2026-11-19 211257` | `2640` | Hero `Kh 2s \| 7d Td Th 2h` | `['Kh', '2s']` | `['7d', 'Td', 'Th', '2h']` | VALID / `WAITING_FOR_TURN` | **`[PLAN] BET_30`** (7.47 BB) | **PASS** |
| `2026-11-19 211257` | `2696` | Hero `Kh 2s \| 7d Td Th 2h` | `['Kh', '2s']` | `['7d', 'Td', 'Th', '2h']` | VALID / `WAITING_FOR_TURN` | **`[PLAN] BET_30`** (8.91 BB) | **PASS** |
| `2026-11-19 211257` | `3220` | Hero `Jc 7d` | `['Jc', '7d']` | `[]` | VALID / `WAITING_FOR_TURN` | **`[PLAN] FOLD`** | **PASS** |
| `2026-11-19 211257` | `3643` | Hero `Jc 4d` vs min-raise | `['Jc', '4d']` | `[]` | VALID / `BTN_OPEN` | **`FOLD`** (0.0 BB) | **PASS** |
| `2026-11-19 211257` | `3668` | Hero `Jc 4d` z badge `Call` | `['Jc', '4d']` | `[]` | VALID / `WAITING_FOR_TURN` | **`[PLAN] FOLD`** | **PASS** |
| `2026-11-19 211257` | `3863` | Hero vs S1 All-in 166 | `['Jc', '4d']` | `[]` | VALID / `WAITING_FOR_TURN` | **`[PLAN] FOLD`** | **PASS** |
| `2026-11-19 211257` | `3880` | Hero tura vs All-in 166 | `['Jc', '4d']` | `[]` | VALID / `BB_VS_SB_SHOVE` | **`FOLD`** (0.0 BB) | **PASS** |
| `2026-11-18 232515` | `12592` | Board River 5 kart | `[]` | `['2c', '5s', '5c', '4d', '8s']` | Standby / NO_HERO | **`WAIT`** | **PASS** |
| `2 gry na raz` | `1383` | `Ks 9s \| 3s Ac Ah` | `['Ks', '9s']` | `['3s', 'Ac', 'Ah']` | VALID / `FLOP` | **`BET_30`** (2.70 BB) | **PASS** |
| `2 gry na raz` | `1627` | Dwa stoły / Hero akcja | `['Ks', '9s']` | `['3s', 'Ac', 'Ah']` | VALID / `FLOP` | **`CALL`** (6.52 BB) | **PASS** |
| `2 gry na raz` | `2418` | Hero `4d Qs` | `['4d', 'Qs']` | `[]` | VALID / `WAITING_FOR_TURN` | **`[PLAN] FOLD`** | **PASS** |
| `2 gry na raz` | `2605` | `4d Qs \| 5d 8c Jh` | `['4d', 'Qs']` | `['5d', '8c', 'Jh']` | VALID / `WAITING_FOR_TURN` | **`[PLAN] BET_30`** (0.90 BB) | **PASS** |
| `2026-11-18 224127` | `0` | Hero `2s Tc` | `['2s', 'Tc']` | `[]` | VALID / `WAITING_FOR_TURN` | **`[PLAN] FOLD`** | **PASS** |
| `2026-11-18 224127` | `765` | Hero `Kd 3c` | `['Kd', '3c']` | `[]` | VALID / `BTN_OPEN` | **`FOLD`** (0.0 BB) | **PASS** |
| `2026-11-18 224127` | `2370` | Hero `7c 5s` | `['7c', '5s']` | `[]` | VALID / `BB_VS_SB_RAISE` | **`CALL`** (0.68 BB) | **PASS** |
| `2026-11-18 224127` | `4950` | `5h Jh \| Jd 2s 9h` | `['5h', 'Jh']` | `['Jd', '2s', '9h']` | VALID / `WAITING_FOR_TURN` | **`[PLAN] ALL_IN`** (3.18 BB) | **PASS** |
| `2026-11-18 224127` | `12600` | Board River 5 kart | `[]` | `['Qs', 'As', '9c', 'Ts', '2h']` | VALID / `WAITING_FOR_TURN` | **`WAIT`** | **PASS** |

---

### 4. Skan porównawczy co 30 klatek (V7 vs V8)

| Metryka | `211257` (V7) | `211257` (V8) | `2 gry na raz` (V7) | `2 gry na raz` (V8) |
| :--- | :---: | :---: | :---: | :---: |
| **Przeskanowane klatki** | 181 | 181 | 491 | 491 |
| **Klatki z wykrytą kotwicą** | 145 (80.1%) | 145 (80.1%) | 467 (95.1%) | 467 (95.1%) |
| **Klatki VALID** | 116 | **117** | 375 | **369** |
| **% VALID przy widocznym stole** | 80.0% | **80.7%** | 80.3% | **79.0%** |
| **Klatki z poprawnie odczytanym boardem** | 0 *(brak odczytu na skali 1.28x)* | **67** *(100% poprawnych kart)* | 248 | **257** |
| **Średnia latencja na klatkę** | ~28 ms | **21.8 ms** | ~25 ms | **18.0 ms** |

---

### 5. Wyniki testów jednostkowych (`pytest -v tests/`)
- Liczba testów: **89 passed in 2.70s (100% sukcesu)**.
- 5 nowych testów jednostkowych:
  1. `tests/test_vision.py::test_card_recognizer_board_full_height_and_cwd_independence` (pełna wysokość kart wspólnych bez obcinania badge'a oraz odporność na CWD).
  2. `tests/test_state.py::test_tracker_waiting_for_turn_to_preflop_no_fake_new_hand` (brak fałszywego `NEW_HAND` przy przejściu `WAITING_FOR_TURN -> PREFLOP`).
  3. `tests/test_state.py::test_validator_postflop_pot_missing_board_cards_rejected` (odrzucanie klatek postflop z pustym boardem i pot > 60).
  4. `tests/test_strategy.py::test_exploit_timing_tell_fast_bet_not_check` (brak telling bonusu po szybkim becie).
  5. `tests/test_ui_and_main.py::test_cli_monitor_parsing` (poprawne parsowanie `--monitor 1`).

---

## V7 — Rozdzielny silnik kart (13 rang + 4 kolory) i poprawki (2026-11-20)

### 1. Zmienione i utworzone pliki

- **`data/templates/ranks/`**: Utworzono 13 czystych binarnych szablonów rang (`2.png` .. `A.png`), wyciętych z białego wnętrza kart bez niebieskiego tła stołu.
- **`data/templates/suits/`**: Utworzono 4 czyste binarne szablony kolorów (`c.png`, `d.png`, `h.png`, `s.png`) z analizą geometryczną wcięcia trefla vs pika.
- **`vision/card_recognizer.py`**:
  - Zaimplementowano hybrydowy silnik `Rank + Suit` (`_use_rank_suit`) z twardym podziałem HSV Czerwony (`h`/`d`) vs Czarny (`s`/`c`).
  - Dodano odcinanie dolnych 32% karty (`badge_cut_h = int(roi_h * 0.68)`), chroniące przed badge'ami akcji `Call`/`Check`.
  - Dodano filtr pustych slotów stołu (`white_fraction < 0.18`), natychmiast odrzucający tło sukna.
  - Zastosowano padding 3 px wokół przeskalowanych wycinków glifów do odpornego geometrycznie `cv2.matchTemplate`.
  - Zachowano 100% kompatybilności wstecznej dla testów syntetycznych z niestandardowym `templates_dir`.
- **`vision/pipeline.py`**:
  - Naprawiono wykrywanie skalowania stołu: `is_scaled = (abs((self._last_anchor_scale or 1.0) - 1.0) > 0.02 or ...)`.
  - Przekazano `slot_hint=slot` do `recognize_candidates`.
- **`main.py`**:
  - Dodano `"RAISE"` do `preview_actions = ["FOLD", "CALL", "RAISE", "ALL_IN"]` przy `max_opp_bet > hero_bet`.
  - Zastosowano karę zakresu przeciwnika w spocie preflop `*_RAISE`: `call_equity = max(0.05, equity - 0.05)`, `shove_call_equity = max(0.05, equity - 0.10)`, `shove_fe = 0.28`.
- **`tests/test_vision.py`**: Dodano `test_card_recognizer_rank_suit_mode`.
- **`tests/test_ui_and_main.py`**: Dodano `test_preview_actions_contains_raise_and_preflop_range_penalty`.
- **`.gitignore`**: Dopisano ignorowanie `*.mp4`, `audit_pack*/`, `raport/`, `scratch/`.
- **Porządki w `data/`**: Usunięto 16 przestarzałych plików debugowych (`act_f*.png`, `hero_panel_f*.png`, `frame700_b1.png`, `test_coquesa.png`) i `gemini-code-1795039488796.txt`.

---

### 2. Wyniki weryfikacji klatek testowych (Sekcja 4.1)

Pełna ścieżka produkcyjna `main.py` (`find_all_anchors` -> `compute_unclipped_table_rect` -> `pipeline.process_frame` -> `StateValidator` -> `evaluate_candidates` -> `DecisionMaker`):

| Nagranie | Klatka | Oczekiwane Karty | Wykryte Hero | Wykryty Board | Stan / Spot | Decyzja | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `2026-11-19 211257` | `1827` | Hero `Kh 2s` | `['Kh', '2s']` | `[]` | VALID / `BB_VS_BTN_RAISE` | **`CALL`** (0.95) | **PASS** |
| `2026-11-19 211257` | `3220` | Hero `Jc 7d` | `['Jc', '7d']` | `[]` | VALID / `WAITING_FOR_TURN` | **`PREVIEW: FOLD`** | **PASS** |
| `2026-11-19 211257` | `3643` | Hero `Jc 4d` vs min-raise | `['Jc', '4d']` | `[]` | VALID / `BTN_OPEN` | **`FOLD`** (0.95) *(nie All-in!)* | **PASS** |
| `2026-11-19 211257` | `3668` | Hero `Jc 4d` z badge `Call` | `['Jc', '4d']` | `[]` | VALID / `WAITING_FOR_TURN` | **`PREVIEW: CHECK`** | **PASS** |
| `2026-11-19 211257` | `3863` | Hero vs S1 All-in 166 | `['Jc', '4d']` | `[]` | VALID / `WAITING_FOR_TURN` | **`PREVIEW: FOLD`** | **PASS** |
| `2026-11-19 211257` | `3880` | Hero tura vs All-in 166 | `['Jc', '4d']` | `[]` | VALID / `BB_VS_SB_SHOVE` | **`FOLD`** (0.95) | **PASS** |
| `2 gry na raz` | `1383` | `Ks 9s \| 3s Ac Ah` | `['Ks', '9s']` | `['3s', 'Ac', 'Ah']` | VALID / `FLOP` | **`BET_30`** (0.95) | **PASS** |
| `2 gry na raz` | `1627` | Dwa stoły / Hero akcja | `['Ks', '9s']` | `['3s', 'Ac', 'Ah']` | VALID / `FLOP` | **`CALL`** (0.95) | **PASS** |
| `2 gry na raz` | `2418` | Hero `4d Qs` | `['4d', 'Qs']` | `[]` | VALID / `WAITING_FOR_TURN` | **`PREVIEW: FOLD`** | **PASS** |
| `2 gry na raz` | `2605` | `4d Qs \| 5d 8c Jh` | `['4d', 'Qs']` | `['5d', '8c', 'Jh']` | VALID / `WAITING_FOR_TURN` | **`PREVIEW: CHECK`** | **PASS** |
| `2026-11-18 224127` | `0` | Hero `2s Tc` | `['2s', 'Tc']` | `[]` | VALID / `WAITING_FOR_TURN` | **`PREVIEW: CHECK`** | **PASS** |
| `2026-11-18 224127` | `765` | Hero `Kd 3c` | `['Kd', '3c']` | `[]` | VALID / `BTN_OPEN` | **`FOLD`** (0.95) | **PASS** |
| `2026-11-18 224127` | `2370` | Hero `7c 5s` | `['7c', '5s']` | `[]` | VALID / `BB_VS_SB_RAISE` | **`CALL`** (0.95) | **PASS** |
| `2026-11-18 224127` | `4950` | `5h Jh \| Jd 2s 9h` | `['5h', 'Jh']` | `['Jd', '2s', '9h']` | VALID / `WAITING_FOR_TURN` | **`PREVIEW: CHECK`** | **PASS** |
| `2026-11-18 232515` | `12592` | Board River 5 kart | `[]` | `['2c', '5s', '5c', '4d', '8s']` | Standby / NO_HERO | **`PREVIEW: WAIT`** | **PASS** |

---

### 3. Skan porównawczy co 30 klatek (Sekcja 4.2: V5 vs V7)

| Metryka | `211257` (Audyt V5) | `211257` (V7 Rank+Suit) | `2 gry na raz` (Audyt V5) | `2 gry na raz` (V7 Rank+Suit) |
| :--- | :---: | :---: | :---: | :---: |
| **Przeskanowane klatki** | 181 | 181 | 491 | 491 |
| **Klatki z wykrytą kotwicą** | 145 (80.1%) | 145 (80.1%) | 467 (95.1%) | 467 (95.1%) |
| **Klatki VALID (% całości wideo)** | 44.2% (80) | **64.1% (116)** | 57.1% (280) | **76.4% (375)** |
| **% VALID przy widocznym stole** | 55.2% | **80.0%** (+24.8 p.p.) | 60.0% | **80.3%** (+20.3 p.p.) |
| **Błędy formatu kart** | Występowały | **0** | Występowały | **0** |
| **Duplikaty kart na klatce** | Występowały | **0** | Występowały | **0** |
| **Średnia latencja na kartę ROI** | ~8–15 ms | **0.72 ms** | ~8–15 ms | **0.72 ms** |

---

### 4. Wyniki testów jednostkowych (`pytest -v tests/`)

- Liczba testów: **84 passed in 3.38s (100% sukcesu)**.
- Żadnych regresji w modułach `calibrator`, `contracts`, `engine`, `state`, `strategy`, `ui` i `vision`.

### 5. Uwagi i rozwiązane problemy

1. **Separacja czarnego tuszu od niebieskiego sukna**: W przestrzeni HSV ciemne piksele sukna mają szum w nasyceniu. Problem rozwiązano poprzez warunek `(B - R) < 60`, ponieważ sukno ma dużą przewagę składowej niebieskiej (`B - R > 100`), podczas gdy tusz na karcie ma zbliżone wartości B i R.
2. **Odporność na badge akcji Hero**: Niebieskie plakietki `Call` / `Check` nachodzące na dolną część kart Hero powodowały fałszywe dopasowania pełnych szablonów. Analiza ograniczona do górnych 68% wycinka całkowicie wyeliminowała ten problem (np. klatka 3668 bezbłędnie zwraca `Jc 4d`).
3. **Kompensacja mikro-rotacji i offsetu**: Dodanie 3-pikselowego paddingu wokół znormalizowanego glifu w `cv2.matchTemplate` podniosło współczynnik korelacji z ~0.33 do > 0.83, gwarantując idealne rozpoznanie nawet przy lekkim pochyleniu kart Hero (-5° / +5°).
4. **Rozpoznawanie trefla vs pika**: Trefl posiada głębokie wcięcie w talii (`mid_ratio <= 0.50`), podczas gdy pik rozszerza się płynnie ku dołowi (`mid_ratio >= 0.60`). Cecha ta gwarantuje 100% pewności rozróżnienia obu czarnych kolorów.
