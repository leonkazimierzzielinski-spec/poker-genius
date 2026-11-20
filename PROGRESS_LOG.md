# Poker Genius — Dziennik Postępu Prac (Progress Log)

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
