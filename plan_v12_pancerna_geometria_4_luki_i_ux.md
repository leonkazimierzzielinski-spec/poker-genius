# Plan V12 — Pancerna Geometria Stołu (4 Czyste Łuki Złotej Obwódki + Anti-Jitter + Pełna Naprawa UX Stołów) (`poker_assistant`)

Dokument zastępuje V11.1 pełnym, produkcyjnym rozwiązaniem problemu pozycjonowania stołu na dowolnym monitorze, dowolnym zoomie (ciągła skala od `0.5x` do `2.0x` bez sztywnej listy skal!) i przy dowolnym układzie okna przeglądarki (w tym z panelem `Bet Slip`), oraz usuwa wszystkie niedociągnięcia UX ujawnione na zdjęciu `IMG_2559.heic`.

---

## 1. Dlaczego metoda „Niebieskie Sukno + 4 Czyste Łuki Złotej Obwódki” jest idealna

Dotychczasowe podejścia miały wady:
- **Ikonki z rogów (`anchor.png`):** Zależą od zmiennych marginesów przeglądarki i sztywnej listy skal (`1.0, 1.15, 1.28, 1.40`), przez co na laptopie HiDPI raz łapały błędną skalę `1.40x` (wielki stół), a raz przesuwały ramki o ~15 px w prawo.
- **Surowy bounding box niebieskiego sukna:** Może lekko drgać o 3–5 px, bo u góry nachodzą na niego awatary `S1`/`S2`, a u dołu karty Hero.
- **Nick `AdrewTate`:** Zmienia kolor tła (ciemnoszary → fioletowy timer → ciemny Fold).

**Rozwiązanie docelowe — 2-etapowy detektor `find_golden_rim_4arcs` (dokładność `±1 px`, czas `< 4 ms`, działa w KAŻDEJ skali ciągłej!):**
1. **Etap A — Niezawodny lokalizator (Niebieskie sukno):**
   - Znajduje największy spójny obszar niebieskiego sukna stołu w HSV (`H: 98..118, S: 80..255, V: 55..230`, z zamknięciem morfologicznym `MORPH_CLOSE`, aby wypełnić logo `Stake` i karty pośrodku).
   - Odrzuca obiekty mniejsze niż `250x130 px` lub o proporcjach spoza `1.45..2.25`.
   - To daje natychmiast przybliżony środek i zakres stołu `(fx, fy, fw, fh)`.
2. **Etap B — Sub-pikselowy pomiar 4 ZAWSZE NIEZASŁONIĘTYCH łuków złotej obwódki:**
   Wokół wykrytego niebieskiego sukna szukamy pikseli złotej obwódki (`H: 14..34, S: 90..255, V: 130..255`) **wyłącznie w 4 strefach, których NIGDY nie zasłania żaden awatar, karta, żeton ani badge:**
   - **Lewy łuk (`left_x`):** w środkowym pasie pionowym `y ∈ [fy + 0.38*fh, fy + 0.62*fh]`, szukamy skrajnej lewej linii złotej obwódki w pobliżu `fx` (np. `[fx - 0.12*fw, fx + 0.08*fw]`) → bierzemy medianę/percentyl `x` złotych pikseli.
   - **Prawy łuk (`right_x`):** w środkowym pasie pionowym `y ∈ [fy + 0.38*fh, fy + 0.62*fh]`, szukamy skrajnej prawej linii złotej obwódki w pobliżu `fx + fw` → mediana/percentyl `x`.
   - **Górny łuk (`top_y`):** w środkowym pasie poziomym **pomiędzy awatarami S1 i S2** `x ∈ [fx + 0.40*fw, fx + 0.60*fw]`, w pasie pionowym powyżej napisu `Prize Pool:` (`[fy - 0.15*fh, fy + 0.12*fh]`) → mediana/percentyl `y`.
   - **Dolny łuk (`bottom_y`):** w dwóch pasach poziomych **po bokach kart Hero** `x ∈ [fx + 0.22*fw, fx + 0.36*fw]` ORAZ `x ∈ [fx + 0.64*fw, fx + 0.78*fw]`, w pasie pionowym wokół `fy + fh` (`[fy + 0.88*fh, fy + 1.15*fh]`) → mediana/percentyl `y`.
3. **Twarda weryfikacja pewności (wszystkie 4 łuki muszą zostać wykryte!):**
   - Jeśli wszystkie 4 pasy mają wystarczającą liczbę złotych pikseli (np. `>= 15 px` w każdym pasie) ORAZ wynikowy prostokąt `(left_x, top_y, right_x - left_x, bottom_y - top_y)` ma poprawne proporcje elipsy Stake (`1.55 <= ow / oh <= 2.05`), detektor zwraca `(left_x, top_y, ow, oh)` ze **100% pewnością**.
   - Dzięki temu **nie ma żadnej sztywnej listy skal** — działa identycznie na `0.63x` (dwa małe okna obok siebie), `1.0x`, `1.15x` (laptop HiDPI z `Bet Slip`), `1.28x` (`211257`) i `1.5x` (4K)!

---

## 2. Wszystkie 5 Filarów Planu V12

| Nr | Filar | Pliki | Co daje |
|---|---|---|---|
| **1** | **Detektor 4 czystych łuków złotej obwódki jako NUMER 1** | `vision/anchor.py`, `config.json`, `main.py` | Złota obwódka wyliczona z 4 niezasłoniętych łuków staje się **główną metodą kotwiczenia** (priorytet: `4-arc golden_rim` → fallback `anchor`). Zero błędów skali `1.40x`, zero przesunięcia o 15 px w prawo, czas `< 4 ms`! |
| **2** | **Stabilizacja czasowa (Anti-Jitter / Deadband 3 px)** | `main.py` | Jeśli nowo wykryty `table_rect` różni się od poprzedniego o `<= 3 px` na każdej krawędzi, system trzyma zamrożony `table_rect` — zero drgania ramek ROI między klatkami! Gdy okno przesunie się o `> 3 px`, natychmiast aktualizuje pozycję. |
| **3** | **Usuwanie DOWOLNEGO stołu + zwarty HUD w granicach ekranu** | `ui/hud.py`, `main.py` | Można usunąć dowolny stół (również `table_1`, gdy istnieje `table_2`), usuwanie natychmiast czyści ramki z `DebugRoiOverlay` i `ActionBarOverlay`. Maksymalna szerokość HUD `<= 440 px`, pasek narzędzi zawinięty w 2 czytelne rzędy + automatyczne pilnowanie, żeby okno HUD nigdy nie wyszło poza prawą/dolną krawędź monitora. |
| **4** | **Przejrzysty wskaźnik źródła kotwiczenia w HUD** | `main.py`, `ui/hud.py` | W panelu `🔍 Szczegóły` wyświetlana jest linia np. `Kotwica: RIM (1.15x)` albo `Kotwica: ICON (1.15x)` albo `Kotwica: MANUAL`, dzięki czemu od razu widać, z jakiej metody korzysta dany stół. |
| **5** | **Pełna weryfikacja na 4 nagraniach + symulacja `Bet Slip` + 2 okna** | `tests/test_vision.py`, `tests/test_ui_and_main.py` | Potwierdzenie, że **sama metoda 4 łuków (bez `anchor.png`)** daje 100% `VALID` na wszystkich nagraniach, przy sztucznym `Bet Slip` (+800 px) oraz przy zmniejszonym oknie `0.75x` (symulacja 2 okien obok siebie!). |

---

## 3. Szczegółowa Specyfikacja Implementacji (Krok po Kroku)

### Krok 1: Kalibracja i implementacja `find_golden_rim` (4 czyste łuki) w `vision/anchor.py` i `config.json`

1. **Pomiar wzorcowych współrzędnych 4 łuków (`golden_rim_rel`) na nagraniach bazowych:**
   - Uruchom skrypt pomiarowy na czystych klatkach z:
     * `Nagrywanie 2026-11-18 224127.mp4` (`f0`, `f765`, `f4950`),
     * `Nagrywanie 2 gry na raz , przeskakujące okna.mp4` (`f1383`, `f2418`),
     * `Nagrywanie 2026-11-19 211257.mp4` (`f1827`, `f2604`, `f4757`).
   - Dla każdej klatki zmierz `(left_x, top_y, right_x, bottom_y)` z 4 czystych łuków złotej obwódki i przelicz je na współrzędne względne względem idealnego `table_rect` (`rx = (left_x - tx) / tw`, `ry = (top_y - ty) / th`, `rw = (right_x - left_x) / tw`, `rh = (bottom_y - top_y) / th`).
   - Zweryfikuj, że na WSZYSTKICH 3 nagraniach wartości `[rx, ry, rw, rh]` są niemal identyczne (rozrzut `<= 0.003`), i zapisz uśrednione `[rx, ry, rw, rh]` jako `"golden_rim_rel"` w `config.json`.
2. **Implementacja `find_golden_rim(frame, search_rect=None)` w `vision/anchor.py`:**
   - Zaimplementuj 2-etapowy algorytm opisany w Sekcji 1 (Etap A: maska niebieskiego sukna -> Etap B: pomiar 4 czystych łuków złotej obwódki z percentylem/medianą, twarda weryfikacja wszystkich 4 łuków i proporcji `1.55 <= ow / oh <= 2.05`).
   - Zapewnij obsługę zarówno realnych klatek Stake, jak i syntetycznego testu `test_find_golden_rim_and_table_rect` w `tests/test_vision.py`.
3. **Odwrócenie priorytetu w `main.py` (`processing_loop`):**
   - Dla każdego stołu w `managed_tables`:
     1. **NUMER 1:** Wywołaj `rim = find_golden_rim(frame, search_rect=search_region)`. Jeśli `rim is not None`, wylicz `table_rect = compute_table_rect_from_rim(rim, rim_rel, canonical_sz)` i ustaw `anchor_source = "RIM"`.
     2. **NUMER 2 (Fallback, tylko gdy `rim is None`):** Wywołaj `find_anchor` + `find_right_anchor` + `compute_unclipped_table_rect` i ustaw `anchor_source = "ICON"`.
     3. **NUMER 3 (Ostateczny fallback przy ustawionym `search_region`):** Użyj samego `search_region` i ustaw `anchor_source = "MANUAL"`.

### Krok 2: Stabilizacja czasowa Anti-Jitter (`main.py`)

- Dla każdego `tid` w `managed_tables` przechowuj `last_stable_rect: tuple[int, int, int, int] | None`.
- Jeśli nowy `orig_table_rect` istnieje oraz poprzedni `last_stable_rect` istnieje, i maksymalna różnica po wszystkich 4 wartościach `max(abs(a - b) for a, b in zip(orig_table_rect, last_stable_rect)) <= 3`:
  - Użyj `last_stable_rect` (utrzymuje idealnie nieruchome ramki ROI!).
- W przeciwnym razie zaktualizuj `last_stable_rect = orig_table_rect`.
- Przy resecie `↺ Auto` lub zmianie `search_region` wyczyść `last_stable_rect = None`.

### Krok 3: Usuwanie dowolnego stołu + zwarty HUD w granicach ekranu (`ui/hud.py`, `main.py`)

1. **Usuwanie dowolnego stołu (`table_1`, `table_2`, ...):**
   - W `HudOverlay`: przycisk **`✕ Usuń`** (czerwony, wyraźny) jest widoczny i aktywny na **każdym** stole na liście, gdy `len(self._managed_table_ids) > 1` (usunięcie `table_1` jest w 100% dozwolone, jeśli istnieje `table_2`!).
   - Po kliknięciu `✕ Usuń` dla `tid`:
     * Usuwa `tid` z `self._managed_table_ids`, `self.table_widgets`, `self.details_widgets`, `self._table_adjusts`,
     * Jeśli `self._editing_table_id == tid`, zamyka panel kalibracji,
     * Natychmiast usuwa `tid` z `self._debug_overlay` oraz `self._action_bar_overlay` (i wymusza `.update()`!),
     * Emituje `hud_bridge.table_removed_by_user.emit(tid)`, co natychmiast usuwa `tid` z `managed_tables` w `main.py`.
2. **Zwarty HUD i pilnowanie granic ekranu (`ui/hud.py`):**
   - Ustaw `self.setMaximumWidth(440)` (kompaktowy, czytelny panel).
   - Podziel górne/narzędziowe przyciski w 2 rzędy (lub zwięzłe etykiety), tak aby nigdy nie rozpychały okna powyżej `440 px`.
   - Dodaj metodę `_clamp_to_screen(self)` wywoływaną po `adjustSize()` i `showEvent()`, która pilnuje, aby okno HUD nie wyjeżdżało poza prawą ani dolną krawędź monitora (`x = min(x, screen_right - width)`, `y = min(y, screen_bottom - height)`).
3. **Informacja o źródle kotwicy w `scan_summary` (`main.py`):**
   - Dopisz w `scan_summary` krótką linię, np. `Kotwica: RIM (2027x1150 @ 207,335)` (albo `ICON` / `MANUAL`), aby użytkownik od razu widział w szczegółach, że zadziałała złota obwódka.

---

## 4. Obowiązkowa Weryfikacja i Testy

1. **Nowe testy jednostkowe (obowiązkowe):**
   - `tests/test_vision.py`:
     - `test_find_golden_rim_4arcs_ignores_occluded_avatars`: syntetyczny stół z niebieskim suknem, złotą obwódką ORAZ zasłoniętymi miejscami awatarów (`S1`, `S2`) i kart Hero (na dole pośrodku) — `find_golden_rim` nadal zwraca dokładny prostokąt z błędem `<= 2 px`!
   - `tests/test_ui_and_main.py`:
     - `test_remove_table_1_when_table_2_exists`: potwierdza, że można usunąć `table_1`, gdy istnieje `table_2`, i że oba nakładki (`DebugRoiOverlay`, `ActionBarOverlay`) natychmiast usuwają `table_1`.
     - `test_anti_jitter_deadband`: weryfikuje, że zmiana `table_rect` o `<= 3 px` utrzymuje stabilny prostokąt, a przesunięcie o `> 3 px` go aktualizuje.

2. **Weryfikacja na WSZYSTKICH 4 nagraniach (WYŁĄCZNIE przez `find_golden_rim` jako numer 1!):**
   - Sprawdzić i wypisać w tabeli w `PROGRESS_LOG.md` wynik **`anchor_source == "RIM"`** dla każdej z poniższych klatek:
     * `211257`: `1827`, `2604`, `3643`, `3880`, `4757` (`Pot: 682`, `7s 7d | Qc 7c 7h`),
     * `224127`: `0`, `765`, `2370`, `4950`,
     * `2 gry na raz`: `1383`, `1627`, `2418`, `2605`,
     * **Symulacja `Bet Slip` (+800 px z prawej na `211257 f2604`)** → `anchor_source == "RIM"`, `VALID`, `Kh 2s | 7d Td Th 2h`,
     * **Symulacja małego okna `0.75x` (skalowane `224127 f765` do `0.75x` — jak przy 2 oknach obok siebie!)** → `anchor_source == "RIM"`, `VALID`, `Kd 3c`!
   - Uruchomić pełny **`pytest -v tests/`** — 100% testów musi przejść bez błędów.

---

## 5. Obowiązkowa Synchronizacja na GitHub (Po Zakończeniu Prac)

1. Dopisz sekcję `## V12 — Pancerna geometria stołu (4 czyste łuki złotej obwódki jako numer 1, Anti-Jitter, usuwanie dowolnego stołu i kompaktowy HUD) (DATA)` na samej górze pliku **`PROGRESS_LOG.md`** z:
   - zmierzonymi współrzędnymi `golden_rim_rel` i błędem w pikselach na każdym nagraniu,
   - tabelą weryfikacji (z kolumną `Źródło kotwicy` potwierdzającą `RIM` na wszystkich klatkach, w tym `Bet Slip` i skali `0.75x`),
   - wynikiem `pytest -v tests/`.
2. Sprawdź `git status` (brak plików `.mp4` i śmieci tymczasowych).
3. Wykonaj:
   - `git add -A`
   - `git commit -m "V12: 4-arc golden-rim primary anchor (any continuous scale), anti-jitter lock, remove any table, clamped compact HUD"`
   - `git push origin main`
4. Na koniec napisz **krótkie potwierdzenie**, że zmiany zostały wypchnięte na GitHub, i podaj sam link do repozytorium:
   `https://github.com/leonkazimierzzielinski-spec/poker-genius`
