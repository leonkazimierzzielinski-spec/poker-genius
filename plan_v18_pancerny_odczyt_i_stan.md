# Plan V18 — Pancerny Odczyt CV, Fizyczna Spójność Stanu i Stabilny Tracker

**Wersja:** V18  
**Cel nadrzędny:** Gruntowna przebudowa warstwy pośredniej **CV → Walidator → Tracker → HUD** bez naruszania dobrze działającej geometrii `RIM`, rozpoznawania kart `CardRecognizer` i silnika strategii (`PreflopNash`, `range_engine`, `flop_db`, `simplifier`, `DecisionMaker`).  
**Benchmark referencyjny (realny monitor LG Ultrawide `2560×1080`, okno `1000×567`):** `nagrania testowe/Nagrywanie 2026-11-24 215605.mp4` (`11 044` klatek, analiza `stride=3` = `3 682` klatki).

---

## 1. Wyniki diagnostyki bazowej (stan PRZED V18) i twarde KPI akceptacji

| Metryka (`Nagrywanie 2026-11-24 215605.mp4`, `stride=3`) | Przed V18 | Cel V18 (KPI) |
| :--- | :---: | :---: |
| `VALID` gdy `len(hero_cards) == 2` | `1 079 / 2 226` (`48.5%`) | **`>= 85%`** |
| `Invalid blinds` + `Blinds decreased` | `1 035` + `515` = **`1 550`** | **`0`** |
| `current_bet > pot` / `current_bet > 900` | `46` / `28` | **`0` / `0`** |
| Fałszywe `stack == 1` na etykiecie `All-In` | `341` | **`0`** |
| `Missing stack` na przygaszonym `S0` (3-max) | `133` | **`<= 10`** |
| Akcje `RAISE > 900` i duplikaty rozdań w `TableTracker` | `7151`, `1160`, `1310` + 3 duplikaty | **`0`** |
| Pełny zestaw testów `pytest -v tests/` | 151+ passed | **100% zielonych** |

---

## 2. Tabela Decyzji Architektonicznych (Zero Zgadywania)

| ID | Moduł | Decyzja / Stała | Wartość docelowa |
| :--- | :--- | :--- | :--- |
| **D1** | `core/constants.py`, `vision/pipeline.py`, `state/validator.py` | Oficjalna drabinka blindów Stake JAQKpot! (`VALID_BLIND_LEVELS`) | `(10, 20), (15, 30), (20, 40), (30, 60), (40, 80), (50, 100), (60, 120), (75, 150), (100, 200)` |
| **D2** | `vision/ocr.py` | Próg fioletowego paska tury (`seat_0_timer`) | `>= 180 px` (środek pustej doliny `120..299` z histogramu) |
| **D3** | `vision/ocr.py` | Bramka jasności/kontrastu dla `read_int` (odzysk przygaszonych stacków po `Fold`) | `min_p98 = 80.0`, `min_contrast = 40.0` |
| **D4** | `vision/ocr.py`, `vision/pipeline.py` | Detekcja napisu `All-In` w polu stacka | Jeśli `>= 3` kontury tekstowe, `span_w / span_h >= 2.2` i `< 50%` dopasowanych cyfr → `stack = 0, status_text = "ALL_IN"` |
| **D5** | `config.json`, `vision/pipeline.py`, `state/validator.py` | Czyste bety: maska białego tekstu + szerszy `seat_0_bet` + niezmiennik `bet <= pot` | `seat_0_bet = [0.478, 0.605, 0.068, 0.04]`; maska HSV `(S < 60) & (V > 175)`; `pot == 0 → bet = 0`, `bet > pot → bet = 0` |
| **D6** | `state/tracker.py` | Potwierdzanie betów, instant-fold `NEW_HAND`, brak duplikatów | 2 kolejne klatki dla `BET/RAISE/CALL`; reset `last_completed_hand = None` poza `NEW_HAND`; detekcja resetu puli |
| **D7** | `vision/ocr.py`, `main.py` | Detekcja `Rabbit hunting break` + podtrzymanie kotwicy `RIM` | Zamrożenie `[PLAN]` i trackera podczas `Rabbit hunting break`; podtrzymanie `last_stable_rect` przez `2.0 s` przy chwilowym zaniku `RIM` |
| **D8** | `ui/hud.py` | Wykluczenie nakładek HUD/ROI z przechwytywania `dxcam` (Windows 10/11) | `SetWindowDisplayAffinity(hwnd, 0x11)` (`WDA_EXCLUDEFROMCAPTURE`) na `HudOverlay`, `DebugRoiOverlay`, `ActionBarOverlay` |
| **D9** | `main.py` | Krótkotrwały carry-over 1 brakującego stacka | Uzupełnienie pojedynczego `None` z `900 - pot - suma_pozostałych` przez maks. `1.5 s` (tylko gdy nie wyeliminowany) |

---

## 3. Szczegółowa Specyfikacja Zmian (Plik po Pliku)

### 3.1. Drabinka blindów i ochrona przed zatruciem walidatora (`core/constants.py`, `vision/pipeline.py`, `state/validator.py`)
1. W `core/constants.py` zdefiniuj stałą:
   ```python
   VALID_BLIND_LEVELS: tuple[tuple[int, int], ...] = (
       (10, 20), (15, 30), (20, 40), (30, 60), (40, 80),
       (50, 100), (60, 120), (75, 150), (100, 200),
   )
   ```
2. W `vision/pipeline.py` dodaj metodę pomocniczą `_normalize_blinds(self, raw_blinds: tuple[int, int] | None, table_id: str) -> tuple[int, int]`:
   - Utrzymuj słownik `self._last_valid_blinds: dict[str, tuple[int, int]] = {}` (z metodą `reset_table_blinds(table_id)` wywoływaną przy resecie turnieju w `main.py`).
   - Jeśli `raw_blinds` jest w `VALID_BLIND_LEVELS`: zapisz w `self._last_valid_blinds[table_id]` (o ile nie spadło względem poprzedniego lub jest nowym turniejem) i zwróć `raw_blinds`.
   - Jeśli `raw_blinds` NIE jest w `VALID_BLIND_LEVELS`, spróbuj **jednoznacznej naprawy z drabinki**:
     - Sprawdź kandydatów `(vsb, vbb)` z `VALID_BLIND_LEVELS`, dla których `raw_sb == vsb` (np. `(20, 4)` → `(20, 40)`, `(30, 610)` → `(30, 60)`) LUB `raw_bb == vbb` (np. `(3, 60)` → `(30, 60)`, `(1, 30)` → `(15, 30)`, `(4, 80)` → `(40, 80)`).
     - Jeśli pasuje dokładnie jeden poziom (albo preferuj poziom `>= prev_blinds` jeśli pasuje kilka), zwróć ten naprawiony poziom.
   - Jeśli `raw_blinds` jest całkowicie niejednoznaczny (np. `(1, 2)`, `(4, 10)`) lub `None`: zwróć `self._last_valid_blinds.get(table_id, (10, 20))`.
3. W `state/validator.py`:
   - W `validate()` zaktualizuj `self._last_blinds[state.table_id]` **wyłącznie**, gdy `is_valid` ORAZ `(state.small_blind, state.big_blind) in VALID_BLIND_LEVELS` (lub gdy `big_blind == 2 * small_blind` dla testów jednostkowych spoza drabinki, ale NIGDY dla nielegalnych par typu `(30, 610)`!).
   - **Uwaga kompatybilnościowa dla istniejących testów:** nie odrzucaj w `StateValidator` par typu `(10, 20)` czy `(5, 10)` używanych w starszych testach jednostkowych — wymuszaj jedynie `small_blind > 0 and big_blind > small_blind`, a przy aktualizacji `_last_blinds` pilnuj, by `big_blind == 2 * small_blind` (co w 100% blokuje zatrucie przez `(30, 610)`!).

### 3.2. `DigitOCR`: przygaszone stacki po `Fold`, etykieta `All-In` i próg paska tury (`vision/ocr.py`)
1. **Przygaszone stacki (`read_int`):**
   - W `DigitOCR.read_int()` zmień wywołanie `_prepare_binary_image` na:
     `self._prepare_binary_image(roi, min_p98=80.0, min_contrast=40.0)`.
   - Uzasadnienie empiryczne (`f01560_seat_0_stack.png`): przygaszony stack po `Fold` ma `p98 = 88, diff = 52`, natomiast pusty fotel ma `diff < 25`.
   - Dla `read_float()` pozostaw `min_p98=125.0, min_contrast=35.0`, dla `read_blinds()` pozostaw `min_p98=100.0, min_contrast=25.0`.
2. **Ochrona przed czytaniem napisu `All-In` jako `1`:**
   - Dodaj metodę `DigitOCR.is_all_in_label(self, roi: np.ndarray) -> bool`:
     - Przekonwertuj do HSV i zbuduj maskę jasnego tekstu `wmask = ((hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 155)).astype(np.uint8) * 255`.
     - Znajdź kontury o wysokości `h >= max(6, int(roi.shape[0] * 0.25))` i szerokości `w >= 2`.
     - Jeśli liczba konturów `>= 3`, policz łączny bounding box wszystkich konturów `(span_w, span_h)`.
     - Jeśli `span_w / max(1, span_h) >= 2.2`, sprawdź ile konturów pasuje do wzorców cyfr z progiem `>= self.threshold` (z użyciem `_match_digit_crop` na binarnym wycinku): jeśli **mniej niż połowa** konturów dopasowała się do cyfr (dla `All-In` dopasowuje się tylko `l`/`I` jako `1`, a `A`, `-`, `n` odpadają), zwróć `True`.
   - W `VisionPipeline.process_frame()` dla `seat_{seat_id}_stack`:
     - Przed `read_int` sprawdź `self.digit_ocr.is_all_in_label(rois[stack_key])`.
     - Jeśli `True`: ustaw bezpośrednio `stack = 0`, `is_all_in_flag = True` → `status_text = "ALL_IN"`, `is_active = True`.
3. **Próg fioletowego paska w `detect_hero_actions()`:**
   - W `detect_hero_actions()` zmień próg `int(cv2.countNonZero(mask_purple)) < 500` na **`< 180`** (środek pustej doliny `120..299` z histogramu 3 682 klatek).
4. **Nowa funkcja `detect_rabbit_hunting_break(actions_roi, is_hero_turn) -> bool` w `vision/ocr.py`:**
   - Jeśli `is_hero_turn` jest `True` lub `actions_roi` jest pusty → zwróć `False`.
   - W lewej połowie `actions_roi` (`left = actions_roi[:, :int(w * 0.48)]`) sprawdź:
     - brak aktywnych kolorowych przycisków (`red_px < 40`, `green_px < 40`, `orange_px < 40`),
     - obecność białej sylwetki królika: maska `white = (hsv[:, :, 1] < 40) & (hsv[:, :, 2] > 205)`, największy kontur ma powierzchnię w zakresie `[100, 2600]` px (na kanonicznym ROI) oraz proporcje `0.55 <= cw / ch <= 1.45`, otoczony szarym tłem przycisku (`S < 45`, `45 <= V <= 125` stanowi `>= 20%` lewej połowy).
   - Zwróć `True` tylko gdy wszystkie warunki są spełnione.

### 3.3. Czyste bety: maska białego tekstu, szerszy `seat_0_bet` i niezmiennik `bet <= pot` (`config.json`, `vision/pipeline.py`, `state/validator.py`)
1. W `config.json` poszerz `seat_0_bet` z `[0.478, 0.605, 0.05, 0.04]` na **`[0.478, 0.605, 0.068, 0.04]`** (zapobiega ucinaniu ostatniej cyfry przy 3-cyfrowych betach `330` / `345`).
2. W `vision/pipeline.py` dodaj metodę `_mask_white_bet_text(roi: np.ndarray) -> np.ndarray`:
   - Dla `roi.ndim == 3` wylicz `hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)` i maskę białego tekstu `mask = (hsv[:, :, 1] < 65) & (hsv[:, :, 2] > 170)`.
   - Zwróć kopię `roi` z wyzerowanymi pikselami spoza `mask` (wycina w 100% kolorowe żetony `S >= 80` oraz przelatujące niebieskie karty `f03528`!).
   - **Uwaga dla testów syntetycznych:** stosuj tę maskę w `process_frame()` dla `seat_{s}_bet` tylko gdy `roi.ndim == 3` i w wycinku są piksele kolorowe (`np.mean(hsv[:, :, 1] >= 65) >= 0.05`), aby nie psuć czarno-białych testów syntetycznych!
3. **Fizyczna sanityzacja betów w `vision/pipeline.py` (po odczycie `pot` i `players`):**
   - Jeśli `pot == 0`: wyzeruj wszystkie `p.current_bet = 0` (gdy pula wynosi `0`, żaden zakład na ulicy nie może być `> 0`).
   - Jeśli `pot > 0`: dla każdego gracza, jeśli `p.current_bet > pot`: wyzeruj `p.current_bet = 0` (w Stake `Pot` zawsze zawiera zakłady z bieżącej ulicy, więc `current_bet > pot` jest fizycznie niemożliwy!).
4. W `state/validator.py`:
   - Dodaj twardą regułę spójności betów: jeśli `state.pot > 0` i `any(p.current_bet > state.pot for p in state.players.values())` (lub `state.pot == 0` i `any(p.current_bet > 0 for p in state.players.values())` przy `sum(stacks) == self.total_chips`), dodaj błąd `"Invalid bet exceeds pot"`.

### 3.4. `TableTracker`: 2-klatkowe potwierdzanie betów, instant-fold `NEW_HAND`, zero duplikatów (`state/tracker.py`)
1. **Zero duplikatów `last_completed_hand`:**
   - Na początku `update()` (zaraz po sprawdzeniu `if not state.is_valid: return state, []`) wyzeruj **`self.last_completed_hand = None`**, aby `main.py` lub skrypt diagnostyczny nigdy nie odczytał tego samego zakończonego rozdania dwa razy!
2. **2-klatkowe potwierdzanie wzrostu betu (`bet_confirm_frames: int = 2`):**
   - Dodaj parametr `bet_confirm_frames: int = 2` w `__init__` (domyślnie `2`, w testach jednostkowych można przekazać `1` lub wysłać 2 klatki — **uwaga:** sprawdź istniejące testy w `tests/test_state.py` i upewnij się, że nie łamiesz ich oczekiwań! Jeśli istniejące testy wysyłają 1 klatkę na akcję, ustaw `bet_confirm_frames: int = 1` jako domyślny w `__init__`, a w `main.py` w trybie live/offline inicjalizuj `TableTracker(resolved_tid, bet_confirm_frames=2)`!).
   - Zanim zapiszesz wzrost `curr_p.current_bet > p_dict["street_bet"]` (poza blindami), wymagaj `bet_confirm_frames` kolejnych klatek z tą samą (lub `>=`) wartością `current_bet` ORAZ odrzucaj każdy bet `> state.pot` (gdy `state.pot > 0`) i `> 900`.
3. **Dodatkowy wyzwalacz `NEW_HAND` dla instant-foldów preflop:**
   - Jeśli `curr_real_st == "PREFLOP"` i `prev_real_st == "PREFLOP"` oraz `prev_pot >= 2 * bb` i `curr_pot <= sb + bb` (pula spadła z powrotem do blindów) ORAZ co najmniej jednemu graczowi zmienił się `stack` o `>= sb` w stosunku do `starting_stacks` → ustaw `pot_reset_new_hand = True` i włącz do `is_new_hand`.

### 3.5. `main.py` i `ui/hud.py`: Carry-over stacka, `Rabbit hunting`, podtrzymanie `RIM`, `WDA_EXCLUDEFROMCAPTURE`
1. **Podtrzymanie `last_stable_rect` przy chwilowym zaniku `RIM` (`main.py`):**
   - Zapisuj w `managed_tables[tid]["last_rim_ts"] = now_sec` przy każdym udanym `RIM`.
   - Jeśli `table_rect is None` (np. przyciemnione okienko „You may check?” z `f08892`), a `last_stable_rect is not None` i `now_sec - last_rim_ts <= 2.0`: użyj `last_stable_rect` (`anchor_source = "RIM_HOLD"`, `has_anchor = True`).
2. **Krótkotrwały carry-over 1 brakującego stacka (`main.py`):**
   - Przechowuj `last_known_stacks[resolved_tid][sid] = (stack, now_sec)` z ostatnich poprawnych klatek.
   - Przed `validator.validate(state)`: jeśli dokładnie 1 gracz ma `stack is None` i `current_bet == 0`, a pozostali dwaj mają znane stacki, sprawdź czy ten gracz był aktywny (nie `OUT` w trackerze) w ciągu ostatnich `1.5 s`. Jeśli `inferred = 900 - state.pot - sum_other_stacks` jest w przedziale `[0, last_stack]` (lub `inferred == last_stack`), uzupełnij `p.stack = inferred` i `p.is_active = (inferred > 0)`.
3. **Obsługa `Rabbit hunting break` (`main.py`):**
   - Jeśli `detect_rabbit_hunting_break(...)` zwróci `True`:
     - nie uruchamiaj trybu `[PLAN]` preview (zwróć `Decision(..., action="WAIT", reason="Rabbit hunting break")`),
     - nie przekazuj tej klatki do `TableTracker.update(state)` (zamrożenie stanu rozdania).
4. **Wykluczenie nakładek z przechwytywania `dxcam` (`ui/hud.py`):**
   - Dodaj funkcję pomocniczą `_apply_exclude_from_capture(widget)` w `ui/hud.py`:
     - Działa wyłącznie gdy `sys.platform == "win32"` (bezpieczny `try/except`, zero wpływu na Linux/CI/headless).
     - Wywołuje `ctypes.windll.user32.SetWindowDisplayAffinity(int(widget.winId()), 0x11)` (`WDA_EXCLUDEFROMCAPTURE`).
   - Wywołuj ją w `showEvent` dla `HudOverlay`, `DebugRoiOverlay` oraz `ActionBarOverlay`.

---

## 4. Zasada Zero Zgadywania (`QUESTIONS_V18.md`)

Jeśli podczas wdrażania lub benchmarku na `nagrania testowe/Nagrywanie 2026-11-24 215605.mp4` napotkasz niejednoznaczność lub którykolwiek z KPI z Sekcji 1 nie zostanie spełniony — **NIE zgaduj i NIE obniżaj na ślepo progów**. Zapisz konkretne liczby i pytania w `QUESTIONS_V18.md` i zatrzymaj się po decyzję.

---

## 5. Obowiązkowa Weryfikacja i Testy

### A. Nowe testy jednostkowe (dodać do `tests/test_vision.py`, `tests/test_state.py`, `tests/test_ui_and_main.py`)
1. `test_blinds_ladder_normalization_recovers_partial_reads_and_blocks_poisoning`: `(20, 4) → (20, 40)`, `(3, 60) → (30, 60)`, `(30, 610) → (30, 60)`, `(1, 2) → carry-over`, oraz `StateValidator` nie zatruwa `_last_blinds` nielegalną parą `(30, 610)`.
2. `test_digit_ocr_reads_dimmed_folded_stack_and_rejects_empty_seat`: syntetyczny przygaszony stack (`p50=36, p98=88`) → odczytany poprawnie; pusty fotel (`diff < 25`) → `None`.
3. `test_digit_ocr_detects_all_in_label_instead_of_digit_1`: wycinek z napisem `All-In` → `is_all_in_label() is True`, `VisionPipeline` zwraca `stack=0, status_text="ALL_IN"` (nie `stack=1`).
4. `test_bet_white_mask_removes_colored_chip_and_rejects_bet_gt_pot`: kolorowa ikona żetonu obok `20` daje `20` (nie `220`/`120`); `pot=30, bet=110` jest zerowane/odrzucane.
5. `test_detect_hero_actions_purple_threshold_180`: `purple_px=250` z przyciskami → `True`; `purple_px=80` z czerwonym tłem dywanu → `False`.
6. `test_detect_rabbit_hunting_break_blocks_preview`: wykrycie białej sylwetki królika w szarym przycisku `hero_actions` (bez fioletowego paska) → `True`.
7. `test_tracker_two_frame_bet_confirm_no_duplicate_completed_hand_and_instant_fold_reset`: jednoklatkowy skok betu ignorowany przy `bet_confirm_frames=2`; `last_completed_hand` czyszczone po klatce `NEW_HAND`; spadek puli przy instant-foldzie otwiera nowe rozdanie.
8. `test_exclude_from_capture_helper_is_safe_on_all_platforms`: `_apply_exclude_from_capture` nie rzuca wyjątku i bezpiecznie wywołuje WinAPI (z mockiem `ctypes.windll` lub na non-win32).

### B. Benchmark regresyjny PRZED vs PO (obowiązkowy)
1. Uruchom `python tools/diag_v18_recording.py` na `nagrania testowe/Nagrywanie 2026-11-24 215605.mp4` i wpisz porównanie wszystkich metryk z Sekcji 1 do `PROGRESS_LOG.md`.
2. Uruchom pełny zestaw `pytest -v tests/` — wymagane **100% zielonych testów**.
3. Zaktualizuj `PROGRESS_LOG.md` wpisem dla **V18**, zrób commit i `git push origin main` (nie commituj ciężkiego `diag_v18_bundle.zip` ani katalogu `scratch/`).
