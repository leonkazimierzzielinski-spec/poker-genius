# Plan Jakości Produkcyjnej V9 — Perfekcyjne `T/10` i `c/s`, Strefowe Przyciski Akcji, Postflop 3-Way, Mini-Karty w HUD i Optymalizacja Live (`poker_assistant`)

Dokument powstał po pełnym audycie technicznym commita `32e8d56` (V8.2) — w tym analizie pikselowej wszystkich 13 szablonów rang, 4 szablonów kolorów, 10 cyfr oraz logiki `vision/`, `engine/`, `main.py` i `ui/hud.py`.

---

## 1. Zestawienie Wszystkich 7 Ulepszeń Systemowych (Plan Ogólny)

| Nr | Obszar / Pliki | Wykryta słabość lub luka | Systemowe rozwiązanie V9 |
|---|---|---|---|
| **1** | **Pewny odczyt `10` (`T`) na każdym slocie** (`data/templates/ranks/T.png`, `config.json`, `vision/card_recognizer.py`) | `T.png` jest ucięty z lewej (`19x23` bez daszka jedynki), a `hero_card_1` (`x=0.4636`) leży bardzo blisko lewej krawędzi karty dla szerokiej dwuznakowej `10`. | Wyciąć czysty, pełny `T.png`; poszerzyć `hero_card_1` w lewo (`x=0.4585, w=0.0405`); wykorzystać regułę 2 konturów (`suit_idx == 2` w górnym rzędzie — żadna inna karta w talii poza `10` nie ma 2 znaków obok siebie!). |
| **2** | **Bezkolizyjne rozróżnianie `c` (trefl) vs `s` (pik)** (`vision/card_recognizer.py`) | W V8 usunięto analizę kształtu, a korelacja samych szablonów `c.png` vs `s.png` wynosi aż **`0.8819`** (stąd pomyłki typu `2s -> 2c` na `232515` f12592). | Dodać precyzyjną cechę kształtu czubka i talii dla czarnych kolorów: pik ma ostry, wąski szpic w górnych 15% wysokości i brak wcięcia w środku; trefl ma szeroki, zaokrąglony górny listek i wyraźne wcięcie w talii (`35–55%` wysokości). |
| **3** | **Strefowa detekcja przycisków `Fold / Call / Raise`** (`vision/ocr.py`) | Na klatce `4757` (tylko `Fold` i `Call 64`, bez `Raise`) `detect_hero_actions` raportowało `['FOLD', 'CALL', 'BET']`, bo `mask_orange` łapało pojedyncze złote piksele tła kasyna. | Podzielić `actions_roi` na 3 strefy poziome (lewa `0–36%`: czerwony `FOLD`, środek `32–68%`: zielony `CHECK/CALL`, prawa `64–100%`: pomarańczowy `BET/RAISE`) z progiem odpornym na szum tła (np. `>= 120 px` na kanonicznej skali). |
| **4** | **Postflop Multiway (3-Way vs Heads-Up)** (`engine/monte_carlo.py`, `main.py`) | `MonteCarloCalculator.estimate_equity` zawsze symuluje grę 1v1, nawet gdy na flopie jest 2 aktywnych rywali (zawyża to equity jednej pary i fold equity w 3-way pocie). | Dodać opcjonalny parametr `num_opponents: int = 1` do `estimate_equity(...)` (losuje `2 * num_opponents` kart i sprawdza `hero_score < min(opp_scores)`) oraz w `main.py` przekazywać realną liczbę aktywnych rywali (`1` lub `2`) + obniżyć `fold_equity` w 3-way (`* 0.65`). |
| **5** | **Szybki cache skali w trybie `📐 Obszar`** (`main.py`) | W V8.2 gałąź `manual_rect` wywołuje `find_anchor` bez `preferred_scale` i bez zapisu `_last_anchor_scale`, co przy skalowanym oknie powoduje wolny skan wieloskalowy na każdej klatce. | Przekazywać `preferred_scale=pipeline._last_anchor_scale` do `find_anchor` w gałęzi `manual_rect` oraz zapisywać `pipeline._last_anchor_scale = aw / tpl_w`. |
| **6** | **Oszczędny tryb spoczynku gdy brak stołu w `live`** (`main.py`) | Gdy w `--mode live` okno stołu jest zminimalizowane lub zakryte (`anchors == []` i `manual_rect is None`), `main.py` przetwarza cały pulpit jako fałszywe `table_1`, marnując CPU. | Gdy `args.mode == "live"` (lub `is_live=True`) oraz `anchors == []` i `manual_rect is None`, pomiń ciężki `VisionPipeline` i wyślij lekki stan `WAIT` z powodem `"Szukam stołu Stake..."`. (W trybie offline / testach syntetycznych bez kotwicy zachowaj dotychczasowy fallback!). |
| **7** | **Kolorowy pasek rozpoznanych kart w kompaktowym HUD** (`ui/hud.py`, `main.py`) | Przy zwiniętych `🔍 Szczegóły` użytkownik nie widzi, jakie karty odczytał system — musi trzymać rozwinięty duży czarny panel. | Dodać jedną kompaktową linijkę bezpośrednio pod nagłówkiem karty stołu w HUD: np. `🃏 10♦ 7♥  •  Board: Q♣ 7♣ 7♥` (z czerwonym kolorem dla `♥♦` i białym dla `♠♣`), zawsze widoczną także przy zwiniętych szczegółach! |

---

## 2. Szczegółowa Specyfikacja Implementacji (Krok po Kroku)

### Krok 1: Naprawa `T` (`10`) oraz rozróżniania `c` vs `s` (`data/templates/ranks/T.png`, `config.json`, `vision/card_recognizer.py`)

1. **Poszerzenie `hero_card_1` w `config.json`:**
   - Zaktualizuj `hero_card_1` z `[0.4636, 0.6744, 0.0350, 0.0880]` na `[0.4585, 0.6744, 0.0405, 0.0880]` (zweryfikuj na `224127`, `211257`, `2 gry na raz`, czy nie zachodzi na drugą kartę i poprawia margines lewej jedynki w `10`).
2. **Nowy, czysty szablon `data/templates/ranks/T.png`:**
   - Wytnij pełną, nieuciętą dwuznakową rangę `10` (z wyraźną pełną jedynką `1` i zerem `0`, bez artefaktu `..##` na dole!) z `211257` f2604 (`Td`/`Th`) lub `224127` f0 (`Tc`) i zapisz jako `data/templates/ranks/T.png`.
3. **Reguła 2-konturowa dla `T` (`10`) w `vision/card_recognizer.py`:**
   - W `_recognize_rank_suit_candidates`: gdy `suit_idx == 2` (czyli w górnym rzędzie połączono 2 osobne kontury obok siebie: `(bx0, by0, bw0, bh0)` i `(bx1, by1, bw1, bh1)`):
     - Posortuj te dwa kontury od lewej do prawej (`left_b, right_b`).
     - Jeśli oba mają zbliżoną wysokość (`min(left_b[3], right_b[3]) >= 0.65 * max(left_b[3], right_b[3])`), lewy jest węższy lub zbliżony (`left_b[2] <= right_b[2] * 1.05`) i łączna szerokość `rw >= 0.78 * rh`:
       - Uznaj to za silny sygnał dwuznakowej rangi `10`: podbij `rank_scores["T"] = max(rank_scores.get("T", 0.0), 0.90)`.
   - Dodatkowo: gdyby `1` i `0` na bardzo małym oknie skleiły się w 1 kontur, czysty pełny szablon `T.png` zapewni wysokie dopasowanie bezpośrednio w `matchTemplate`.
4. **Przywrócenie precyzyjnej dyskryminacji `c` vs `s` w `vision/card_recognizer.py`:**
   - Dla `color_group == "BLACK"` i poprawnego `suit_crop` (`sh >= 8, sw >= 8`):
     - Oblicz dwie proste, niezależne od rozmiaru cechy na binarnym `suit_crop`:
       1. `top_tip_ratio`: średnia szerokość tuszu w górnych 15% wysokości (`:max(2, int(sh * 0.16))`) podzielona przez maksymalną szerokość `tot_w` (pik ma ostry czubek → mały `top_tip_ratio`, trefl ma okrągły górny listek → szerszy).
       2. `waist_ratio`: minimalna szerokość tuszu w pasie `30%..55%` wysokości podzielona przez `tot_w` (trefl ma wyraźne przewężenie między górnym a dolnymi listkami!).
     - Zmierzyć rzeczywiste wartości `top_tip_ratio` i `waist_ratio` na klatkach z `224127`, `211257`, `2 gry na raz` i `232515` (w tym `12592`: `2s`, `5s`, `8c`, `8s`) i dodać wyważony bonus/karę (np. `±0.08`), żeby `c` i `s` nigdy się nie myliły!

---

### Krok 2: Strefowa detekcja przycisków w `vision/ocr.py` (`detect_hero_actions`)

W `vision/ocr.py` (`detect_hero_actions`):
- Zachowaj pełną kompatybilność z syntetycznymi testami jednostkowymi (`test_detect_hero_actions` i `test_detect_hero_actions_with_purple_timer` — sprawdź najpierw w `tests/test_vision.py`, w których miejscach test rysuje czerwony/zielony/pomarańczowy prostokąt!).
- Jeśli `actions_roi` ma standardowe proporcje paska akcji (szeroki prostokąt, `w >= 2 * h`):
  - **FOLD (czerwony):** szukaj w lewej części (`x: 0 .. int(w * 0.45)`),
  - **CHECK/CALL (zielony):** szukaj w środkowej/prawej części (`x: int(w * 0.25) .. int(w * 0.80)`),
  - **BET/RAISE (pomarańczowy/złoty):** szukaj wyłącznie w prawej części (`x: int(w * 0.58) .. w`), z wyższym progiem `min_bet_pixels = max(60, int(zone_pixels * 0.015))` (przycisk `Raise`/`Bet` ma > 1000 pomarańczowych pikseli, podczas gdy szum z tła kasyna to kilkadziesiąt pikseli!).
- Zweryfikuj na klatce `4757` (`211257` — tylko `Fold` i `Call 64`), że `available_actions` zwraca dokładnie **`['FOLD', 'CALL']`** (bez fałszywego `'BET'`!), a na `3643`, `3880`, `2604` nadal zwraca `['FOLD', 'CALL', 'BET']` / `['FOLD', 'CHECK', 'BET']`.

---

### Krok 3: Obsługa Multiway (3-Way) w Monte Carlo (`engine/monte_carlo.py` + `main.py`)

1. **W `engine/monte_carlo.py` (`estimate_equity`):**
   - Dodaj opcjonalny parametr `num_opponents: int = 1` (domyślnie `1` — 100% kompatybilności wstecznej!).
   - Gdy `num_opponents <= 1`: obecna szybka logika 1v1 bez zmian.
   - Gdy `num_opponents > 1`: w każdej iteracji losuj `missing_board_count + 2 * num_opponents` kart z `deck`, policz `hero_score` oraz `opp_scores = [evaluate_cards(v1, v2, *full_board) for ...]`:
     - Jeśli `hero_score < min(opp_scores)`: `wins += 1.0`,
     - Jeśli `hero_score == min(opp_scores)`: `wins += 1.0 / (1 + opp_scores.count(hero_score))`.
2. **W `main.py` (`evaluate_candidates` — postflop):**
   - Policz `active_opponents = sum(1 for sid, p in players.items() if sid != 0 and getattr(p, "is_active", True) and getattr(p, "status_text", "") not in ("FOLDED", "SIT_OUT", "ELIMINATED"))`.
   - Ogranicz `num_opps = max(1, min(2, active_opponents))`.
   - Przekaż `num_opponents=num_opps` do `mc_calc.estimate_equity(...)`.
   - W puli 3-osobowej (`num_opps == 2`) pomnóż zakładane `fold_equity` (`bet_fe`, `shove_fe`) przez `0.65` (dwóch rywali trudniej wyblefować niż jednego).

---

### Krok 4: Optymalizacja `live` i `📐 Obszar` (`main.py`)

1. **Cache skali w `manual_rect` (`main.py`, okolice linii 826):**
   - Wywołuj `find_anchor(sub_frame, pipeline.anchor_template, threshold=pipeline.anchor_threshold, preferred_scale=getattr(pipeline, "_last_anchor_scale", None))` i po znalezieniu aktualizuj `pipeline._last_anchor_scale = aw / tpl_w`.
2. **Tryb spoczynku przy braku stołu w `--mode live` (`main.py`):**
   - Przekaż flagę `is_live: bool = False` do `processing_loop`.
   - Gdy `is_live and manual_rect is None and not anchors`: pomiń wywołanie `pipeline.process_frame` na całym pulpicie, wyemituj do HUD lekki `Decision(table_id="table_1", action="WAIT", ev_bb=None, confidence=1.0, profile_used="STANDARD_EXPLOIT", reason="Szukam stołu Stake...")` (maksymalnie raz na 0.5 s) i przejdź do kolejnej klatki.

---

### Krok 5: Kompaktowy pasek kart w HUD (`ui/hud.py` + `main.py`)

1. W `main.py`:
   - Sformatuj krótką etykietę kart bezpośrednio w pierwszej linii lub jako osobny parametr/tag (bez łamania sygnatury `on_decision_updated(decision, latency_ms, scan_summary)`!):
   - `ui/hud.py` (`on_decision_updated`) może bardzo czysto wyciągnąć linię `Hero: ... | Board: ...` bezpośrednio z `scan_summary` (który już dostaje!), zamienić kody kart (`Td`, `7h`, `Qc`, `7s`) na czytelne kolorowe symbole HTML:
     - `h` → `<span style="color:#ff5c5c;">♥</span>`, `d` → `<span style="color:#ff5c5c;">♦</span>`,
     - `s` → `<span style="color:#e2e8f0;">♠</span>`, `c` → `<span style="color:#e2e8f0;">♣</span>`,
     - `T` → `10`,
   - i wyświetlić ten zgrabny pasek **`🃏 10♦ 7♥  |  Q♣ 7♣ 7♥`** zawsze na głównej karcie stołu w HUD — nawet gdy panel `🔍 Szczegóły` jest zwinięty!

---

## 3. Obowiązkowa Weryfikacja i Testy

1. **Nowe testy jednostkowe (obowiązkowe):**
   - `tests/test_vision.py`:
     - test dla 2-konturowej lewej karty `10♦` (`Td`) z pełnym szablonem `T.png`,
     - test dla strefowego `detect_hero_actions` (brak fałszywego `BET` przy złotych pikselach w lewej/środkowej części lub niskim szumie tła).
   - `tests/test_engine.py`:
     - test `MonteCarloCalculator.estimate_equity(..., num_opponents=2)` sprawdzający, że equity `AA` lub `AK` przeciwko 2 rywalom jest niższe niż przeciwko 1 rywalowi i mieści się w realistycznym przedziale.
   - `tests/test_ui_and_main.py`:
     - test renderowania kolorowego paska kart (`10♦ 7♥`) w kompaktowym widoku `HudOverlay` (gdy `show_details == False`).

2. **Weryfikacja na wszystkich nagraniach (pełna ścieżka `main.py`):**
   - **`211257`:**
     - `4757`: `Hero: ['7s', '7d']`, `Board: ['Qc', '7c', '7h']`, `Pot: 682`, **`Actions: ['FOLD', 'CALL']`** (bez fałszywego `BET`!), `VALID`, `CALL`,
     - `2604` (`Kh 2s | 7d Td Th 2h`), `1827` (`Kh 2s`), `3220` (`Jc 7d`), `3643` (`Jc 4d`), `3668` (`Jc 4d` z badge `Call`), `3880` (`Jc 4d` vs All-In `166`).
   - **`224127`:** `0` (`2s Tc`), `765` (`Kd 3c`), `2370` (`7c 5s`), `4950` (`5h Jh | Jd 2s 9h`).
   - **`2 gry na raz`:** `1383` (`Ks 9s | 3s Ac Ah`), `1627`, `2418` (`4d Qs`), `2605` (`4d Qs | 5d 8c Jh`).
   - **`232515`:** `12592` — sprawdzić poprawę rozróżniania `c` vs `s` na boardzie!
   - Uruchomić pełny **`pytest -v tests/`** — 100% testów musi przejść.

---

## 4. Obowiązkowa Synchronizacja na GitHub (Po Zakończeniu Prac)

1. Dopisz nową sekcję `## V9 — Jakość produkcyjna: pełne 10/T, dyskryminacja c/s, strefowe akcje, postflop 3-way i mini-karty w HUD (DATA)` na samej górze pliku **`PROGRESS_LOG.md`** z podsumowaniem zmian, tabelą weryfikacji klatek i wynikiem `pytest`.
2. Sprawdź `git status` (brak plików `.mp4` i śmieci tymczasowych).
3. Wykonaj:
   - `git add -A`
   - `git commit -m "V9: full T/10 & c/s recognition, zoned action buttons, 3-way Monte Carlo, compact HUD cards, live idle mode"`
   - `git push origin main`
4. Na koniec napisz **krótkie potwierdzenie**, że zmiany zostały wypchnięte na GitHub, i podaj sam link do repozytorium:
   `https://github.com/leonkazimierzzielinski-spec/poker-genius`
