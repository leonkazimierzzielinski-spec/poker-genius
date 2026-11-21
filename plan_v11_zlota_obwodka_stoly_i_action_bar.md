# Plan Architektoniczny V11 — Kotwiczenie o Złotą Obwódkę Stołu, Jawne Zarządzanie Stołami, Kalibracja z Zatwierdzaniem, Buy-in Live i Tryb „Tylko Akcja” (`poker_assistant`)

Dokument jest kompletną specyfikacją wdrożeniową dla agentów w Antigravity na podstawie 10 decyzji użytkownika oraz analizy zdjęć z trybu `--mode live`.

## 1. Zestawienie Wszystkich Wymagań V11 (6 Filarów)

| Nr | Filar | Wymaganie docelowe | 
| ----- | ----- | ----- | 
| **1** | **Pewne kotwiczenie o złotą/pomarańczową obwódkę stołu (`vision/anchor.py`, `vision/pipeline.py`)** | Wykrywanie złotej elipsy stołu w HSV z twardą weryfikacją pewności (proporcje, ciągłość krawędzi, rozmiar) — wyznacza dokładny środek `(cx, cy)` oraz niezależną skalę `scale_x` i `scale_y` co do 1–2 px, z bezpiecznym fallbackiem do kotwicy. Do tego lekkie poszerzenie `hero_card_2` w prawo i `seat_2_stack` w lewo, żeby `9♠` i `280` nigdy nie były ucinane. | 
| **2** | **Koniec auto-dodawania stołów + śledzenie blindów po przeciwnikach (`vision/pipeline.py`, `main.py`)** | `#105...` w lewym górnym rogu Stake to numer **rozdania** (zmienia się w każdym rozdaniu!), a nie numer turnieju! Usuwamy auto-mnożenie `table_1..table_6` w HUD: domyślnie jest wyłącznie `Stół 1`, a kolejne stoły (`Stół 2`, ...) pojawiają się **tylko** po kliknięciu `+ Dodaj stół`. W tle (dla 2 gier przeskakujących w 1 oknie) historię blindów walidatora rozdzielamy po sygnaturze obszaru nicków/awatarów przeciwników (`seat_1` + `seat_2`), nie tworząc przy tym nowych kafli w HUD! | 
| **3** | **Panel kalibracji per stół z zatwierdzaniem i 3-sekundowym auto-ukryciem (`ui/hud.py`, `main.py`)** | Panel kalibracji jest **domyślnie całkowicie schowany**. Kliknięcie `✎ Kalibruj` przy danym stole rozwija kontrolki (`◀ ▲ ▼ ▶`, skala `- / +`, szerokość `↔ -/+`, wysokość `↕ -/+`, `✋ Przesuń` myszą) i podświetla ramki tego stołu w **pomarańczowym kolorze trybu edycji**. Pojawiają się przyciski **`✔ Zatwierdź`** (stosuje w pamięci — bez zapisu na dysk, przełącza ramki na normalne kolory na **3 sekundy**, po czym automatycznie je chowa) oraz **`✕ Anuluj`** (cofa do wartości sprzed edycji). | 
| **4** | **Jawne `+ Dodaj stół` / `✕ Usuń` (multi-tabling na 2 oknach)** | Przycisk `+ Dodaj stół` w HUD otwiera wybór obszaru dla nowego stołu (z automatycznym dociągnięciem do złotej obwódki wewnątrz wybranego obszaru), a przycisk `✕` przy stole pozwala go usunąć (z blokadą usunięcia ostatniego stołu). | 
| **5** | **Zmiana `buy-in` w locie z HUD (`ui/hud.py`, `main.py`)** | W panelu szczegółów HUD szybkie przyciski wyboru stawki: `$0.50`, `$2`, `$5`, `$10`, aktualizujące w locie `decision_maker.buy_in` bez restartu aplikacji. | 
| **6** | **Tryb „Tylko Akcja” pod przyciskami gry (`ui/hud.py`, `main.py`)** | Przełącznik `⚡ Tylko akcja` (`Ctrl+Shift+A`): zamiast dużego okna HUD wyświetla na ekranie (click-through + `WDA_EXCLUDEFROMCAPTURE`) smukły pasek szerokości przycisków `hero_actions` dokładnie **pod** przyciskami na stole: `FOLD` pod lewym przyciskiem Fold, `CHECK`/`CALL` pod środkowym przyciskiem, `BET_30 (<kwota>)` / `MIN_RAISE` / `ALL_IN` pod prawym przyciskiem! | 

## 2. Szczegółowa Specyfikacja Implementacji (Krok po Kroku)

### Krok 1: Detektor Złotej Obwódki Stołu (`vision/anchor.py` + `config.json`)

**Cel:** Wyeliminować błąd `±15–20 px` wynikający ze zmiennych marginesów paska ikon przeglądarki.

1. **Pomiar kanonicznych współrzędnych złotej obwódki na nagraniach bazowych:**

   * Uruchom krótki skrypt diagnostyczny na klatkach z `Nagrywanie 2026-11-18 224127.mp4` (`f0`, `f765`), `Nagrywanie 2 gry na raz...` (`f1383`, `f2418`) oraz `Nagrywanie 2026-11-19 211257.mp4` (`f2604`, `f4757`):

   * Wyodrębnij maskę złotej/pomarańczowej obwódki stołu w HSV (np. `H: 14..32`, `S: 100..255`, `V: 140..255`, z wykluczeniem górnego napisu `"Prize Pool:"` i dolnego pomarańczowego przycisku `Raise/Bet` poprzez analizę największego pustego w środku owalnego konturu lub symetrycznego bounding boxa).

   * Zmierz w przestrzeni kanonicznej `(1757, 997)` dokładne względne położenie złotej obwódki:
     `rim_rel = [rx, ry, rw, rh]` (gdzie `ox = tx + rx * tw`, `oy = ty + ry * th`, `ow = rw * tw`, `oh = rh * th`) i zapisz je w `config.json` pod `"anchor": { ..., "golden_rim_rel": [rx, ry, rw, rh] }`.

2. **Funkcja `find_golden_rim(frame: np.ndarray, search_rect: tuple[int, int, int, int] | None = None) -> tuple[int, int, int, int] | None` w `vision/anchor.py`:**

   * Jeśli podano `search_rect`, szuka wyłącznie w jego obrębie; w przeciwnym razie na całej klatce.

   * Zastosuj maskę HSV dla złotej obwódki + lekkie zamknięcie morfologiczne (`cv2.MORPH_CLOSE`, jądro `5x5` lub `7x7`), aby połączyć drobne przerwy (np. tam gdzie avatary/karty delikatnie przecinają obwódkę!).

   * Znajdź kontury (`cv2.RETR_EXTERNAL`) i **twardo zweryfikuj pewność detekcji (wszystkie warunki muszą być spełnione naraz!)**:

     1. Szerokość `ow >= 300 px` i wysokość `oh >= 160 px` (odrzuca małe przyciski `Bet/Raise`, żetony i napisy `Prize Pool`).

     2. Proporcje owalu: `1.55 <= (ow / oh) <= 2.15` (dopasowane dokładnie do zmierzonego `rw/rh` elipsy Stake).

     3. **Ciągłość / pewność obwódki:** Sprawdź obecność złotych pikseli na **wszystkich 4 ćwiartkach/krawędziach** bounding boxa (lewy łuk, prawy łuk, górny łuk, dolny łuk — każda z 4 stref musi zawierać wystarczającą liczbę złotych pikseli, a środek prostokąta musi być zdominowany przez **niebieskie sukno stołu**!). Ten warunek daje **100% pewności**, że wykryty prostokąt to prawdziwa złota obwódka stołu Stake, a nie losowy pomarańczowy element na ekranie!

   * Jeśli weryfikacja przejdzie, zwróć `(ox, oy, ow, oh)` w pikselach pełnej klatki; w przeciwnym razie zwróć `None`.

3. **Funkcja `compute_table_rect_from_rim(rim_rect, rim_rel) -> tuple[int, int, int, int]`:**

   * Z `(ox, oy, ow, oh)` i `[rx, ry, rw, rh]` wylicza bezpośrednio:

     * `tw = int(round(ow / rw))`

     * `th = int(round(oh / rh))`

     * `tx = int(round(ox - rx * tw))`

     * `ty = int(round(oy - ry * th))`

   * Zwraca `(tx, ty, tw, th)` — **idealnie dopasowane zarówno w osi X, jak i Y!**

4. **Kolejność w `main.py` / `VisionPipeline`:**

   * Dla każdego skonfigurowanego slotu stołu:

     1. Najpierw spróbuj wykryć złotą obwódkę `find_golden_rim(frame, search_rect=slot.search_region)`.

     2. Jeśli znaleziona z pełną pewnością → użyj `compute_table_rect_from_rim(...)` (dokładność 1–2 px!).

     3. Jeśli nie znaleziona → fallback do dotychczasowego `find_anchor` + `find_right_anchor` + `compute_unclipped_table_rect`.

5. **Korekta 2 ciasnych ROI w `config.json` (z analizy `IMG_2556.heic`):**

   * Lekko poszerz `hero_card_2` w prawo (np. szerokość z `0.0380` na `0.0420`, start `x` przesunięty delikatnie w prawo tak, żeby nie zahaczać o lewą kartę `hero_card_1`, a w pełni mieścić pochyloną prawą kartę `9♠` / `10♦`).

   * Lekko poszerz `seat_2_stack` w lewo (np. `x` z `0.665` na `0.658`, `w` z `0.048` na `0.055`), żeby nigdy nie ucinać lewej cyfry `2` w `280`.

### Krok 2: Wyłączenie auto-dodawania stołów i śledzenie turniejów po przeciwnikach (`vision/pipeline.py`, `main.py`)

1. **Jawna lista stołów w `main.py` i `ui/hud.py`:**

   * Domyślnie aplikacja śledzi wyłącznie `["table_1"]` (bez wywoływania `resolve_table_id` do tworzenia `table_2..table_6` w HUD!).

   * Każdy stół na jawnej liście `managed_tables: dict[str, TableSlotConfig]` ma własne:

     * `table_id`: `"table_1"`, `"table_2"`, ...

     * `search_region: tuple[int, int, int, int] | None` (obszar poszukiwań ustawiony przy `+ Dodaj stół` lub `📐 Obszar`, domyślnie `None` = cały ekran dla `table_1`),

     * `adjust`: `(dx, dy, scale_x, scale_y)` (domyślnie `(0, 0, 1.0, 1.0)`, **wyłącznie w pamięci RAM**, brak zapisu na dysk).

   * **Nigdy** nie pojawiają się w HUD stoły spoza `managed_tables`.

2. **Ciche rozdzielanie historii blindów dla 2 turniejów w 1 oknie (po nazwach/awatarach przeciwników, NIE po `#ID`!):**

   * W `VisionPipeline` dodaj lekką metodę `compute_opponents_signature(table_image, effective_rect) -> np.ndarray | None`:

     * Wycina 2 małe paski zawierające nazwy/awatary przeciwników `Seat 1` i `Seat 2` (ponad ich stackami, np. obszar nicka `seat_1` i `seat_2`) i sprowadza je do małego binarnego wektora/obrazka.

   * W `main.py`: dla każdego `table_id` przechowuj w tle `validator_key = f"{table_id}_{opponent_group_id}"` (porównując sygnaturę przeciwników z ostatnimi 2–3 widzianymi składami na tym slocie; próg np. `0.85`).

   * Jeśli w jednym oknie przeskoczy drugi turniej (inni przeciwnicy!), `StateValidator` i `TableTracker` używają osobnego `validator_key` (zero błędów `Blinds decreased`!), ale **HUD nadal pokazuje jeden czysty, stabilny kafel `table_1`**!

### Krok 3: Panel Kalibracji Per Stół + Zatwierdzanie + 3s Auto-Ukrycie + Buy-in Live (`ui/hud.py`, `main.py`)

1. **Nowe sygnały w `HudBridge` (`ui/hud.py`):**

   * `table_added = Signal(str, object)` (`table_id`, `search_region_or_none`)

   * `table_removed_by_user = Signal(str)` (`table_id`)

   * `table_adjust_changed = Signal(str, int, int, float, float)` (`table_id`, `dx`, `dy`, `scale_x`, `scale_y`)

   * `buy_in_changed = Signal(float)`

2. **Układ przycisków w `HudOverlay` (`ui/hud.py`):**

   * **Górny pasek (kompaktowy):** `🔍 Szczegóły`, `⚡ Tylko akcja` (`Ctrl+Shift+A`), `+ Stół`.

   * **Panel po rozwinięciu `🔍 Szczegóły`:**

     * Szybki wybór stawki **Buy-in:** przyciski `$0.50` | `$2` | `$5` | `$10` (aktywny podświetlony na niebiesko),

     * Przełącznik `🎯 Ramki ROI` (`Ctrl+Shift+O`),

     * Przy każdym stole (`table_1`, `table_2`...): przycisk **`✎ Kalibruj`**, **`📐 Obszar`**, **`↺ Auto`** oraz **`✕`** (usuń stół, ukryty gdy został tylko 1 stół).

   * **Panel kalibracji (DOMYŚLNIE SCHOWANY!):**

     * Otwiera się **dopiero po kliknięciu `✎ Kalibruj`** dla konkretnego stołu `editing_table_id`.

     * Automatycznie włącza `DebugRoiOverlay` w trybie edycji (**ramki tego stołu świecą na wyraźny POMARAŃCZOWY/ZŁOTY kolor**, aby było od razu widać, że trwa edycja!).

     * Zawiera kontrolki dla wybranego stołu:

       * Pozycja: `◀`, `▲`, `▼`, `▶` (krok `5 px`, z `Shift` `15 px`),

       * Skala ogólna: `Skala -` / `+` (`±1%`),

       * Rozciąganie niezależne: `Szer ↔ -/+` (`scale_x ±1%`), `Wys ↕ -/+` (`scale_y ±1%`),

       * `✋ Przesuń myszą` (chwycenie i przeciągnięcie ramki myszą na ekranie),

       * Wyraźne przyciski zakończenia: zielony **`✔ Zatwierdź`** oraz czerwony **`✕ Anuluj`**.

     * **Zachowanie po kliknięciu `✔ Zatwierdź`:**

       1. Zamyka i chowa panel kalibracji,

       2. Wyłącza tryb pomarańczowy na `DebugRoiOverlay` (ramki wracają do normalnych zielonych/czerwonych kolorów),

       3. Uruchamia timer `QTimer.singleShot(3000, ...)` — ramki pozostają widoczne przez **dokładnie 3 sekundy** (żeby użytkownik sprawdził idealne dopasowanie), po czym same się wyłączają!

     * **Zachowanie po kliknięciu `✕ Anuluj`:** przywraca wartości `(dx, dy, scale_x, scale_y)` sprzed rozpoczęcia edycji, chowa panel kalibracji i zamyka ramki.

3. **Przycisk `+ Stół`:**

   * Dodaje kolejny `table_N` i otwiera `RegionSelectorOverlay`, żeby użytkownik wskazał okno drugiego stołu na ekranie (jeśli anuluje `Esc`, nie dodaje stołu).

### Krok 4: Tryb „Tylko Akcja” (`ActionBarOverlay`) pod Przyciskami Gry (`ui/hud.py`, `main.py`)

1. **Klasa `ActionBarOverlay(QWidget)` w `ui/hud.py`:**

   * Pełnoekranowa, bezramkowa, przezroczysta, **zawsze click-through** i wykluczona z przechwytywania (`set_exclude_from_capture(hwnd, True)`).

   * Odbiera z `main.py` (przez `HudBridge.action_bar_updated = Signal(object)`) dla każdego stołu:

     * `actions_rect`: dokładny fizyczny prostokąt ekranowy pola `hero_actions` `(ax, ay, aw, ah)` (wyliczony z aktywnego `table_rect` + `rois_rel["hero_actions"]`),

     * `action`: np. `"FOLD"`, `"CHECK"`, `"CALL"`, `"BET_30"`, `"MIN_RAISE"`, `"ALL_IN"`, `"WAIT"`,

     * `amount_chips`: wyliczona kwota w żetonach (dla `BET_30`: `int(round(0.30 * pot))`, dla `MIN_RAISE`: `2 * big_blind`, dla `CALL`: `max(0, max_opp_bet - hero_bet)`, dla `ALL_IN`: `hero_stack`),

     * `ev_bb`: float | None,

     * `is_plan`: bool (`True` jeśli podgląd przed turą).

   * **Pozycjonowanie w `paintEvent` (z przeliczeniem `/ devicePixelRatio()`):**

     * Pasek ma szerokość dokładnie równą `aw` (szerokość przycisków gry) i pojawia się **bezpośrednio pod** `hero_actions` (na `y = ay + ah + 4 px`, a jeśli brakuje miejsca na dole ekranu, to tuż nad `ay - bar_h - 4 px`).

     * Podział na 3 kolumny dokładnie odpowiadające przyciskom gry Stake (`Fold` | `Check/Call` | `Bet/Raise`):

       * **`FOLD`** → czerwona etykieta **`▲ FOLD`** wycentrowana pod **lewą 1/3** (pod przyciskiem Fold),

       * **`CHECK` / `CALL`** → pomarańczowa/żółta etykieta **`▲ CHECK`** lub **`▲ CALL {amount}`** wycentrowana pod **środkową 1/3** (pod przyciskiem Check/Call),

       * **`BET_30` / `MIN_RAISE` / `ALL_IN`** → zielona etykieta **`▲ BET {amount}`** / **`▲ RAISE {amount}`** / **`▲ ALL-IN`** wycentrowana pod **prawą 1/3** (pod przyciskiem Bet/Raise),

       * W trybie `is_plan == True`: subtelniejsza, półprzezroczysta ramka z napisem `PLAN: ...` pod tym samym przyciskiem.

       * Dla `WAIT`: nic nie rysuje (ekran pozostaje całkowicie czysty!).

2. **Przełącznik `⚡ Tylko akcja` (`Ctrl+Shift+A`) w `HudOverlay`:**

   * Gdy włączony: pokazuje `ActionBarOverlay`, a główne okno `HudOverlay` zwija się do malutkiego paska z samym napisem `🎯 HUD [⚡ Tylko akcja | Ctrl+Shift+A]` (żeby zawsze można było łatwo wrócić kliknięciem lub skrótem).

## 3. Obowiązkowa Weryfikacja i Testy

1. **Nowe testy jednostkowe (obowiązkowe):**

   * `tests/test_vision.py`:

     * `test_find_golden_rim_and_table_rect`: weryfikuje wykrywanie złotej obwódki na syntetycznej elipsie oraz odrzucanie fałszywych pomarańczowych prostokątów (bez niebieskiego wnętrza / złe proporcje).

     * `test_opponents_signature_same_vs_different`: potwierdza, że sygnatura przeciwników rozróżnia 2 różne turnieje bez polegania na zmieniającym się `#ID` rozdania.

   * `tests/test_ui_and_main.py`:

     * `test_hud_calibration_edit_confirm_cancel_and_auto_hide`: sprawdza, że panel kalibracji jest domyślnie ukryty, `✎ Kalibruj` go pokazuje i włącza tryb edycji, `✕ Anuluj` cofa wartości, a `✔ Zatwierdź` zapisuje w pamięci i planuje ukrycie ramek po 3 s.

     * `test_hud_buy_in_switch_and_manual_table_add_remove`: sprawdza przełączanie `buy-in` (`$0.50/$2/$5/$10`) oraz ręczne dodawanie/usuwanie stołów.

     * `test_action_bar_overlay_positioning`: sprawdza renderowanie offscreen `ActionBarOverlay` dla `FOLD` (lewa 1/3), `CALL` (środkowa 1/3) i `BET_30` (prawa 1/3 z kwotą).

2. **Weryfikacja na WSZYSTKICH 5 nagraniach (pełna ścieżka z wykrywaniem złotej obwódki!):**

   * Sprawdzić skuteczność `find_golden_rim` na `224127.mp4`, `211257.mp4` (`1827`, `2604`, `3643`, `3880`, `4757`), `2 gry na raz` (`1383`, `1627`, `2418`, `2605`) oraz na klatce `211257` f2604 z doklejonym 800-px panelem `Bet Slip` po prawej.

   * Potwierdzić, że `find_golden_rim` trafia z dokładnością `<= 3 px` na wszystkich 5 nagraniach, a wszystkie kluczowe klatki (`Hero`, `Board`, `Pot`, `S0/S1/S2`) są **100% VALID**.

   * Uruchomić pełny **`pytest -v tests/`** — 100% testów musi przejść bez regresji.

## 4. Obowiązkowa Synchronizacja na GitHub (Po Zakończeniu Prac)

1. Dopisz sekcję `## V11 — Kotwiczenie o złotą obwódkę stołu, jawne zarządzanie stołami, kalibracja z zatwierdzaniem, buy-in live i tryb „Tylko Akcja” (DATA)` na samej górze pliku **`PROGRESS_LOG.md`** z opisem zmierzonych współrzędnych złotej obwódki, wynikami testów na 5 nagraniach i wynikiem `pytest`.

2. Sprawdź `git status` (brak plików `.mp4` i śmieci tymczasowych).

3. Wykonaj:

   * `git add -A`

   * `git commit -m "V11: golden-rim table anchor, explicit table manager, confirmable HUD calibration (3s auto-hide), live buy-in, ActionBarOverlay"`

   * `git push origin main`

4. Na koniec napisz **krótkie potwierdzenie**, że zmiany zostały wypchnięte na GitHub, i podaj sam link do repozytorium:
   `https://github.com/leonkazimierzzielinski-spec/poker-genius`