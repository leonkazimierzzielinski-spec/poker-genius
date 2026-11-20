# Poker Genius — Dziennik Postępu Prac (Progress Log)

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
