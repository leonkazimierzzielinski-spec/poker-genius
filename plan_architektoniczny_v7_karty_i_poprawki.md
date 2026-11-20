# Plan Architektoniczny V7 — Rozdzielny Silnik Kart (13 Rang + 4 Kolory) i Poprawki Po Przeglądzie Repo (`poker_assistant`)

Dokument powstał po pełnym przeglądzie aktualnego repozytorium `poker-genius` (w tym analizie statystycznej i wizualnej wszystkich 61 szablonów kart w `data/templates/cards/`).

---

## 1. Główna Diagnoza (Dlaczego na `211257` nadal pojawiało się `NO_HERO_CARDS`)

Audyt wszystkich 61 plików `.png` w `data/templates/cards/` ujawnił źródłową przyczynę problemu z rozpoznawaniem kart:

1. **49 z 61 szablonów kart jest zabrudzonych pikselami spoza karty** (niebieskie tło stołu w narożniku, zielone ramki debugowe, pomarańczowe paski):
   - `Kc.png` (`55x80`): **58.5%** nie-kartowych pikseli,
   - `2c.png`: **28.7%**, `As.png`: **26.3%**, `4c.png` (`55x80`): **24.7%**, `Js.png`: **24.5%**,
   - **`7d.png`**: **18.7%** (zawiera zieloną linię po lewej i pomarańczowy napis na dole — dokładnie dlatego na klatce `3220` system rozpoznał `Jc`, a odrzucił `7d`!),
   - `Kh.png` i `2d.png`: stary rozmiar **`32x50`** zamiast `50x75` (dlatego na klatce `1827` odrzuciło `Kh`),
   - `4d.png` vs `4d_hero.png`: `4d.png` ma ciemnoniebieski trójkąt stołu po lewej (lewa karta Hero), więc przy porównaniu z prawą kartą Hero (`4d_hero.png`, białe tło po lewej) uzyskał wynik zaledwie **0.44**!
2. **Skalowalność starego podejścia (`52 szablony`):**
   Na Stake karta może pojawić się w **3 różnych geometriach**:
   - lewa karta Hero (`hero_card_1` — lekko pochylona w lewo, ciemny stół po lewej),
   - prawa karta Hero (`hero_card_2` — lekko pochylona w prawo, biała karta po lewej),
   - karta na Boardzie (`board_card_1..5` — pionowa `0°`).
   Utrzymywanie `52 × 3 = 156` osobnych obrazków `50x75` z tłem stołu jest kruche i powoduje błędy na każdej nowej karcie.

### Docelowe rozwiązanie optymalne: Klasyfikator Rozdzielny `Ranga (13) + Kolor (4)`
Każda z 52 kart w talii to wyłącznie kombinacja:
- **1 z 13 Rang (`2, 3, 4, 5, 6, 7, 8, 9, T, J, Q, K, A`)** w górnej strefie białej powierzchni karty,
- **1 z 4 Kolorów (`c, d, h, s`)** dokładnie pod rangą, przy czym **Czerwony (`h, d`) vs Czarny (`s, c`)** jest w 100% rozłączny w przestrzeni HSV!

Zalety takiego podejścia:
- Potrzeba tylko **13 czystych binarnych szablonów rang** i **4 czyste binarne szablony kolorów** (17 mikro-szablonów zamiast 156 obrazków!).
- Działa od razu dla **wszystkich 52 kart na każdym slocie** (nawet dla kart, których nigdy wcześniej nie było w nagraniu!).
- Izoluje **wyłącznie białe wnętrze karty** i **górne ~70% wysokości**, więc całkowicie ignoruje niebieski stół po bokach, kąt krawędzi oraz niebieski badge `Call`/`Check`/`Fold` na dole kart Hero (`f3668`).
- Przyspiesza rozpoznawanie kart ~3–5× (mniej operacji `matchTemplate`, mniejsze matryce).

---

## 2. Pozostałe 3 Błędy Znalezione w Przeglądzie Repozytorium

| Nr | Plik i miejsce | Znaleziony błąd | Naprawa |
|---|---|---|---|
| **E1** | `main.py` (linie 954–958) | W trybie podglądu `[PLAN]`, gdy `max_opp_bet > hero_bet` (np. Hero na `BTN_OPEN` lub `SB_OPEN` przed flopem), `preview_actions` wynosi `["FOLD", "CALL", "ALL_IN"]` — **brakuje `"RAISE"`**, więc `StrategySimplifier` blokuje `MIN_RAISE` i zamienia plan na `FOLD`/`ALL_IN`! | Zmienić `preview_actions` dla `max_opp_bet > hero_bet` na `["FOLD", "CALL", "RAISE", "ALL_IN"]`. |
| **E2** | `main.py` (linie 324–342) | W `evaluate_candidates` dla `BB_VS_BTN_RAISE` / `BB_VS_SB_RAISE` / `SB_VS_BTN_RAISE` nadal używane jest surowe `equity` bez kary za mocniejszy zakres otwierającego rywala (podczas gdy postflop ma już realistyczną karę). | Dodać łagodną karę zakresu: `call_equity = max(0.05, equity - 0.05)`, `shove_call_equity = max(0.05, equity - 0.10)`, `shove_fe = 0.28`. |
| **E3** | `vision/pipeline.py` (linie 286–292) | Gdy `table_rect is None`, warunek `is_scaled = (effective_rect[2], effective_rect[3]) != (CW, CH)` jest zawsze `False` (bo `effective_rect` już wcześniej ustawiono na `(0, 0, CW, CH)`). | Sprawdzać `is_scaled = abs((self._last_anchor_scale or 1.0) - 1.0) > 0.02` lub wymiar przed rzutowaniem. |

---

## 3. Szczegółowy Plan Wdrożenia (Krok po Kroku)

### Krok 1: Ekstrakcja 13 czystych szablonów rang i 4 czystych szablonów kolorów
Utwórz dwa foldery:
- `data/templates/ranks/` (`2.png`, `3.png`, `4.png`, `5.png`, `6.png`, `7.png`, `8.png`, `9.png`, `T.png`, `J.png`, `Q.png`, `K.png`, `A.png`)
- `data/templates/suits/` (`c.png`, `d.png`, `h.png`, `s.png`)

**Jak wyciąć je czysto (bez tła stołu i artefaktów):**
1. Wytnij je z najczystszych klatek prostych kart boardu (oraz w razie brakującej rangi — z wyprostowanych kart Hero) z nagrań `Nagrywanie 2026-11-18 224127.mp4`, `Nagrywanie 2 gry na raz...` i `Nagrywanie 2026-11-19 211257.mp4` (albo z czystych wzorców w `data/templates/cards/`, gdzie brak tła stołu).
2. Dla każdego symbolu zastosuj ten sam deterministyczny preprocessing co w runtime:
   - Maska białej powierzchni karty (jasne tło: `V > 170` i `S < 60` w HSV) → znajdź największy spójny biały obszar (wnętrze karty), aby odrzucić niebieski stół i ramki!
   - Wewnątrz maski białej karty wyodrębnij piksele „tuszu” (czarne: `V < 120, S < 90`; czerwone: `S > 90, V > 80, (H <= 12 lub H >= 165)`).
   - **Górna strefa (ranga):** połącz bliskie kontury w poziomie (ważne dla **`10` (`T`)**, które składa się z dwóch znaków `1` i `0` obok siebie!), wytnij ścisły bounding box (trimmed) i zapisz jako binarny obraz `uint8` (białe znaki `255` na czarnym tle `0`).
   - **Dolna strefa pod rangą (kolor/suit):** znajdź główny kontur symbolu koloru (odrzucając ewentualny duży centralny symbol karty z prawego dolnego rogu — bierzemy symbol leżący w tej samej kolumnie `x` co ranga, tuż pod jej dolną krawędzią `y`!), wytnij ścisły bounding box i zapisz jako binarny obraz `uint8` (`255` na `0`).
3. Zweryfikuj w skrypcie, że wszystkie 13 plików w `data/templates/ranks/` i 4 pliki w `data/templates/suits/` istnieją, są niepuste, mają sensowne proporcje i wysoką separację w macierzy podobieństwa (np. `c` vs `s` oraz `h` vs `d` łatwo się odróżniają).

---

### Krok 2: Nowy, hybrydowy `CardRecognizer` (`vision/card_recognizer.py`)

Zachowaj **100% kompatybilności wstecznej** dla wszystkich istniejących testów jednostkowych (`tests/test_vision.py::test_card_recognizer_match_and_threshold` oraz `test_card_recognizer_collision_resolution`), które podają własny `templates_dir` ze sztucznymi kolorowymi kartami `50x75`!

**Zasada działania w `CardRecognizer`:**
1. W `__init__(self, templates_dir="data/templates/cards", threshold=0.92, ranks_dir="data/templates/ranks", suits_dir="data/templates/suits")`:
   - Jeśli `templates_dir` jest domyślne (`data/templates/cards`) i istnieją oba katalogi `ranks_dir` oraz `suits_dir` z kompletem 13 rang + 4 kolorów, załaduj `self.rank_templates: dict[str, np.ndarray]` i `self.suit_templates: dict[str, np.ndarray]` oraz włącz tryb `self._use_rank_suit = True`.
   - Jeśli podano niestandardowe `templates_dir` (np. `tmp_path` w teście jednostkowym) lub brak `ranks_dir`/`suits_dir`, działaj w dotychczasowym trybie `template_items` (100% kompatybilności z testami!).
2. **Metoda `_recognize_rank_suit_candidates(self, card_roi: np.ndarray, slot_hint: str | None = None, top_k: int = 3) -> list[tuple[str, float]]`:**
   - **Krok A — Odrzucenie pustego slotu (brak karty):**
     Sprawdź w górnych 70% wycinka `card_roi`, czy istnieje wystarczająca powierzchnia białego wnętrza karty (`V > 170, S < 60`, np. `>= 18%` pikseli wycinka). Jeśli nie ma białej karty (puste niebieskie sukno stołu na boardzie), natychmiast zwróć `[]`!
   - **Krok B — Wyprostowanie kąta dla kart Hero (jeśli `slot_hint` to `"hero_card_1"` lub `"hero_card_2"`):**
     Sprawdź w eksperymencie na `211257` (`1827`, `3220`, `3643`) i `224127` (`765`, `2370`), czy lekki obrót (`+5°..+7°` dla `hero_card_1`, `-5°..-7°` dla `hero_card_2`) dodatkowo poprawia dopasowanie binarnych rang i kolorów — użyj kąta dającego najwyższy margines.
   - **Krok C — Klasyfikacja koloru Czerwony vs Czarny (HSV):**
     W górnych 68% wycinka (odcinając ewentualny dolny badge `Call`/`Check`/`Fold`!) znajdź piksele tuszu czerwonego (`S > 85, V > 75, H <= 12 lub H >= 165`) i czarnego (`V < 125, S < 95` wewnątrz białego wnętrza karty).
     - Jeśli dominuje tusz czerwony → dozwolone kolory to **wyłącznie `("h", "d")`**!
     - Jeśli dominuje tusz czarny → dozwolone kolory to **wyłącznie `("s", "c")`**!
     - Jeśli brak wyraźnego tuszu → zwróć `[]`.
   - **Krok D — Segmentacja rangi (góra) i symbolu koloru (pod rangą):**
     Na binarnej masce tuszu (ograniczonej do lewych ~65% szerokości karty, żeby nie łapać wielkiego symbolu ze środka karty!):
     - Znajdź kontur(y) rangi w górnym pasie (`y` w górnej połowie wykrytego obszaru karty); dla `T` (`10`) scal dwa sąsiednie kontury o zbliżonej wysokości `y` i odstępie poziomym `<= 6 px`.
     - Znajdź kontur symbolu koloru bezpośrednio pod rangą (`y_suit > y_rank_bottom - 2`, wyrównany w `x` do rangi).
   - **Krok E — Dopasowanie rangi i koloru:**
     - Dopasuj przycięty obraz rangi do wszystkich 13 szablonów w `self.rank_templates` (skalując do rozmiaru szablonu za pomocą `cv2.INTER_AREA` + `cv2.TM_CCOEFF_NORMED`) → uzyskaj listę `(rank, rank_score)`.
     - Dopasuj przycięty obraz koloru wyłącznie do 2 dozwolonych szablonów w `self.suit_templates` (`h`/`d` lub `s`/`c`) → uzyskaj `(suit, suit_score)`.
     - Łączny score kandydata: np. `combined = 0.65 * rank_score + 0.35 * suit_score` (przy minimalnym progu `rank_score >= 0.68` i `suit_score >= 0.65` oraz `combined >= rank_suit_threshold`, skalibrowanym na 5 nagraniach tak, żeby było 0 fałszywych trafień na pustych slotach).
     - Zwróć `top_k` kombinacji `(f"{rank}{suit}", combined)` posortowanych malejąco.
3. **Przekazywanie `slot_hint` z `vision/pipeline.py`:**
   - W `VisionPipeline.process_frame` przekaż `slot_hint=slot` (np. `"hero_card_1"`, `"hero_card_2"`, `"board_card_1"`) do `recognize_candidates(slot_roi, top_k=3, slot_hint=slot)` (z domyślnym `slot_hint: str | None = None`, żeby nie łamać sygnatury w testach!).
   - Zachowaj rozwiązywanie kolizji duplikatów (`used_cards`) w `VisionPipeline`.

---

### Krok 3: 3 Poprawki z Przeglądu Kodu (`main.py` + `vision/pipeline.py`)

1. **`main.py` (tryb `[PLAN]` — brak `RAISE` w `preview_actions`):**
   - W `processing_loop` (okolice linii 954):
     ```python
     if max_opp_bet > hero_bet:
         preview_actions = ["FOLD", "CALL", "RAISE", "ALL_IN"]
     else:
         preview_actions = ["CHECK", "BET_30", "ALL_IN"]
     ```
2. **`main.py` (`evaluate_candidates` dla `*_RAISE` preflop):**
   - W gałęzi `spot in ("BB_VS_BTN_RAISE", "BB_VS_SB_RAISE", "SB_VS_BTN_RAISE")`:
     zastosuj `call_equity = max(0.05, equity - 0.05)`, `shove_call_equity = max(0.05, equity - 0.10)`, `shove_fe = 0.28`.
3. **`vision/pipeline.py` (poprawka `is_scaled`):**
   - Ustaw `is_scaled = abs((self._last_anchor_scale or 1.0) - 1.0) > 0.02` lub sprawdzaj wymiary `table_rect` przed rzutowaniem.

---

### Krok 4: Sprzątanie repozytorium (bez ruszania `nagrania testowe/`)
- Usuń stare pliki debugowe z `data/` (`act_f*.png`, `hero_panel_f*.png`, `frame700_b1.png`, `test_coquesa.png`) oraz stary plik `gemini-code-1795039488796.txt` z katalogu głównego (o ile żaden test się do nich nie odwołuje — sprawdź `grep`em przed usunięciem!).
- Zaktualizuj `.gitignore`, dopisując `raport/`, `audit_pack*.zip`, `scratch/`.

---

## 4. Kryteria Odbioru i Obowiązkowa Weryfikacja na Wszystkich 5 Nagraniach

Po wdrożeniu wszystkich 4 kroków agent musi:

1. **Zweryfikować klatki ze zgłoszenia użytkownika oraz kluczowe klatki regresyjne (przez pełną ścieżkę `main.py`):**
   - **`211257` klatka `1827`:** `Hero: ['Kh', '2s']`, `VALID`, `Hero Turn: True`, `Decision != WAIT`, latencja `< 150 ms`.
   - **`211257` klatka `3220`:** `Hero: ['Jc', '7d']`, `VALID`, podgląd **`[PLAN]`** (NIE `WAIT` / `Invalid card count`!).
   - **`211257` klatka `3643`:** `Hero: ['Jc', '4d']`, `VALID`, `BTN_OPEN`, `FOLD`.
   - **`211257` klatka `3668` (z niebieskim badge `Call` na kartach!):** `Hero: ['Jc', '4d']`, `VALID` (odzyskane mimo badge `Call`!).
   - **`211257` klatka `3863`:** `Hero: ['Jc', '4d']`, `VALID`, `S1: stack=0, ALL_IN`, **`[PLAN] FOLD`**.
   - **`211257` klatka `3880`:** `Hero: ['Jc', '4d']`, `VALID`, `BB_VS_SB_SHOVE`, **`FOLD`**.
   - **`2 gry na raz`:** `1383` (`Ks 9s | 3s Ac Ah`), `1627` (`Ks 9s | 3s Ac Ah | bet 40`), `2418` (`4d Qs`), `2605` (`4d Qs | 5d 8c Jh`).
   - **`224127`:** `0` (`2s Tc`), `765` (`Kd 3c`), `2370` (`7c 5s`), `4950` (`5h Jh | Jd 2s 9h`).
   - **`232515`:** `12592` (`2s 5s 8c Jd 8s`, brak duplikatów).

2. **Wykonać pełny skan porównawczy co 30 klatek na `211257` oraz `Nagrywanie 2 gry na raz...` i podać tabelę PRZED (z V5) vs PO (V7):**
   - `% VALID` (oczekiwany duży wzrost, np. z 44% i 57% w okolice **75–85%+**!),
   - liczba błędów `Invalid card count` (oczekiwany radykalny spadek!),
   - średnia latencja na klatkę (oczekiwane **`< 120 ms`**!).

3. **Dopisać testy jednostkowe i uruchomić pełny `pytest -v tests/`:**
   - Test dla rozdzielnego rozpoznawania `Rank + Suit` w `tests/test_vision.py`,
   - Test dla `preview_actions` z `MIN_RAISE` w `tests/test_ui_and_main.py`,
   - `pytest -v tests/` musi przejść w **100%** bez błędów.
