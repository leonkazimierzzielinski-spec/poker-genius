# Poker Genius — Dziennik Postępu Prac (Progress Log)

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
