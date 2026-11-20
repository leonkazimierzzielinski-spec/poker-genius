# Plan Naprawy i Optymalizacji Systemu — Wersja V4 (`poker_assistant`)

Dokument stanowi kompletną, jednoznaczną specyfikację wdrożeniową dla agentów w Antigravity. Każdy punkt zawiera dokładną przyczynę błędu, docelową architekturę, wskazówki implementacyjne (żeby uniknąć regresji) oraz kryteria odbioru w `pytest` i na realnych klatkach z `nagrania testowe/`.

---

## 1. Diagnoza Głównych Przyczyn (Dlaczego HUD zawodził mimo dobrych testów)

Audyt paczki `audit_pack_ocr.zip` ujawnił **4 fundamentalne błędy architektoniczne**, przez które wywołanie `VisionPipeline` w osobnym skrypcie działało, ale uruchomienie pełnej aplikacji przez `main.py` zwracało `NO_HERO_CARDS` i `Blinds decreased`:

1. **Rozdwojona ścieżka geometrii (`main.py` vs `VisionPipeline`):**
   - `main.py` wywołuje najpierw `compute_table_rect(anchor, ...)`, które przycina ujemne współrzędne `tx, ty` do `0` (np. `(-22, -9)` staje się `(0, 0)`).
   - Następnie przekazuje ten przycięty `table_rect` do `VisionPipeline.process_frame(..., table_rect=table_rect)`.
   - Gałąź `else:` w `process_frame` pomija budowanie płótna kanonicznego `(1757, 997)`, bo różnica szerokości `1706` vs `1757` mieści się w `<= 5%`. W efekcie **wszystkie ROI przesuwają się o +22 px w prawo i +9 px w dół** — wycinek mija narożnik kart Hero (`Hero: --`) i ucina zero w `40` (`bet 4`).
2. **Wyłączone rozróżnianie stołów w `main.py`:**
   - Gdy `main.py` przekazuje `table_rect` (nie `None`), zmienna `anchor_found` w `VisionPipeline.process_frame` pozostaje `False`.
   - Wywołanie `resolve_table_id(..., has_anchor=anchor_found)` dostaje `False` i natychmiast zwraca `"table_1"`, całkowicie wyłączając rozróżnianie stołów w `main.py`.
3. **Sztywny limit 2 stołów i brak obsługi wielu turniejów w `resolve_table_id`:**
   - W 8-minutowym nagraniu (`Nagrywanie 2 gry na raz...`) pojawia się trzeci turniej (`#105540008` na klatce `8614`). Ponieważ `resolve_table_id` ma sloty tylko na `table_1` i `table_2`, trzeci turniej wpada do starego `table_1` i wywołuje `Blinds decreased from (20, 40) to (15, 30)`.
4. **Brak obsługi innych skal okna (`Nagrywanie 2026-11-19 211257.mp4`, skala ~1.3x) i duplikatów kart (`232515` klatka `12592`):**
   - `find_all_anchors` szuka `anchor.png` wyłącznie w skali `1.0x`, więc w nagraniu `211257` (`1858x1248`) nie znajduje kotwicy.
   - `CardRecognizer` nie ma mechanizmu unikania duplikatów w obrębie jednej klatki (na klatce `12592` przypisał `5s` zarówno do `Board Card 2` z `1.000`, jak i do `Board Card 3` z `0.927`, mimo że `8c` miało `0.924`).

---

## 2. Plan Ogólny (5 Filarów)

| Filar | Moduły | Cel |
|---|---|---|
| **1. Jednolita geometria kanoniczna** | `vision/anchor.py`, `vision/pipeline.py`, `main.py` | Jedna wspólna ścieżka dla `table_rect=None`, wykrytej kotwicy z `main.py` oraz ręcznego `📐 Obszar` — zawsze z pełnym płótnem kanonicznym `(CW, CH)` i zachowaniem ujemnych `tx, ty`. |
| **2. Wieloskalowe wykrywanie kotwicy** | `vision/anchor.py`, `vision/pipeline.py` | Automatyczne wykrywanie `anchor.png` także przy innych rozmiarach/zoomach okna (np. `211257` `1858x1248`) z przeskalowaniem stołu do `canonical_table_size`. |
| **3. Obsługa 3+ turniejów i czysty HUD** | `vision/pipeline.py`, `main.py`, `ui/hud.py` | Dynamiczne ID stołów (`table_1`, `table_2`, `table_3`...) z resetem walidatora przy zmianie turnieju oraz wygaszaniem nieaktywnych stołów w HUD-zie. |
| **4. Eliminacja duplikatów kart** | `vision/card_recognizer.py`, `vision/pipeline.py` | Ranking kandydatów `recognize_top_k` + rozwiązywanie kolizji kart w obrębie jednej klatki (karta o wyższym score blokuje ten kod dla pozostałych slotów). |
| **5. Płynność HUD (Anty-migotanie)** | `main.py` | Krótki bufor podtrzymania ostatniej ważnej decyzji (max 400 ms) podczas pojedynczych klatek animacji, gdy `is_hero_turn` nadal trwa. |

---

## 3. Szczegółowa Specyfikacja Wdrożenia (Krok po Kroku)

### Krok 1: Jednolita geometria kanoniczna (`vision/anchor.py` + `vision/pipeline.py` + `main.py`)

**Zasada nadrzędna:** Nigdy nie wolno przycinać ujemnych współrzędnych `tx, ty` przed rzutowaniem na płótno kanoniczne `(CW, CH)`.

1. **W `vision/anchor.py`:**
   - Pozostaw `compute_table_rect(...)` bez zmian dla wstecznej kompatybilności z istniejącymi testami (`tests/test_vision.py::test_compute_table_rect`).
   - Dodaj nową funkcję pomocniczą `compute_unclipped_table_rect(anchor_rect: tuple[int, int, int, int], table_offset_rel: list[float], canonical_size: tuple[int, int] = (1757, 997), template_size: tuple[int, int] | None = None) -> tuple[int, int, int, int]`:
     - Oblicza skalę `scale = aw / template_size[0]` (jeśli podano `template_size` i `template_size[0] > 0`, w przeciwnym razie `1.0`).
     - Wylicza rzeczywisty rozmiar stołu w pikselach oryginalnej klatki:
       `tw = int(round(canonical_size[0] * scale))`
       `th = int(round(canonical_size[1] * scale))`
     - Wylicza nieprzycięte współrzędne lewego górnego rogu stołu:
       `tx = int(round(ax - ox * tw))`
       `ty = int(round(ay - oy * th))`
     - Zwraca `(tx, ty, tw, th)` **bez przycinania do `0`**.

2. **W `vision/pipeline.py`:**
   - Dodaj metodę pomocniczą `_warp_to_canonical(self, frame: np.ndarray, rect: tuple[int, int, int, int]) -> np.ndarray`:
     - Tworzy czarne płótno `canvas = np.zeros((th, tw, 3), dtype=np.uint8)` o wymiarach `(th, tw)` z `rect = (tx, ty, tw, th)`.
     - Kopiuje wspólną część `frame` i `canvas` (obsługując zarówno `tx < 0`, `ty < 0`, jak i wystawanie poza prawą/dolną krawędź `frame`).
     - Jeśli `(tw, th) != (CW, CH)`, skaluje `canvas` do `(CW, CH)` za pomocą `cv2.resize(canvas, (CW, CH), interpolation=cv2.INTER_LINEAR)`.
     - Zwraca gotowy obraz stołu o rozmiarze dokładnie `(CH, CW, 3)` (`effective_rect = (0, 0, CW, CH)`).
   - W `VisionPipeline.process_frame(...)`:
     - Dodaj jawny parametr `has_anchor: bool | None = None` (domyślnie `None`).
     - Jeśli `table_rect is None`: wykryj kotwicę przez `find_anchor` (z obsługą skali, patrz Krok 2), wylicz `unclipped_rect = compute_unclipped_table_rect(...)`, ustaw `anchor_found = True` i wywołaj `_warp_to_canonical(frame, unclipped_rect)`. Jeśli kotwicy nie znaleziono, użyj pełnej klatki i `anchor_found = False`.
     - Jeśli `table_rect is not None` (przekazane z `main.py` lub z `manual_rect`):
       - **Zawsze** wywołuj `_warp_to_canonical(frame, table_rect)` (zamiast omijać płótno przy różnicy `<= 5%`), dzięki czemu zarówno ujemne `tx, ty` z `main.py`, jak i ręczne prostokąty z `📐 Obszar` zawsze trafiają w dokładnie ten sam układ współrzędnych `(0, 0, CW, CH)`.
       - Ustaw `anchor_found = has_anchor if has_anchor is not None else True` (a przy `manual_rect` w `main.py` przekazuj `allow_table_resolution=False`).
   - **UWAGA NA PUŁAPKĘ:** W `tests/test_vision.py::test_vision_pipeline_synthetic` sprawdzany jest syntetyczny obraz bez pliku `anchor.png` lub o niestandardowym rozmiarze. Upewnij się, że gdy `anchor_template is None` lub kotwicy nie znaleziono (`table_rect` = pełna klatka i brak kotwicy), zachowanie fallbacku pozostaje w 100% zgodne z testem syntetycznym (nie rozciąga małego syntetycznego obrazu `640x480` do `1757x997`, jeśli `anchor_found` jest `False` i `table_rect is None`).

3. **W `main.py` (`processing_loop`):**
   - Zamiast `compute_table_rect(anchor, ...)`, używaj `compute_unclipped_table_rect(anchor, pipeline.table_offset_rel, canonical_size=pipeline.canonical_table_size, template_size=(tpl_w, tpl_h))`.
   - Do `pipeline.process_frame(...)` przekazuj `has_anchor=(manual_rect is None and len(anchors) > 0)`.

---

### Krok 2: Wieloskalowe wykrywanie kotwicy (`vision/anchor.py`)

**Cel:** Obsłużyć okna przeglądarki w innej skali/zoomie (np. `Nagrywanie 2026-11-19 211257.mp4`, `1858x1248`, skala ~`1.3x`) bez spowalniania normalnych klatek `1.0x`.

1. W `find_all_anchors(frame, anchor_template, threshold=0.85, min_distance_px=100, scales=(1.0, 1.25, 1.30, 1.15, 0.85, 0.75, 1.40))`:
   - **Krok szybki (skala `1.0`):** Najpierw wykonaj standardowe `cv2.matchTemplate` dla `scale = 1.0`. Jeśli znajdzie co najmniej 1 dopasowanie `>= threshold`, zwróć wynik natychmiast (zero narzutu na zwykłych klatkach!).
   - **Fallback wieloskalowy (tylko gdy skala `1.0` zwróciła `[]`):**
     - Przeskaluj `anchor_template` kolejno dla pozostałych skal `s` (pamiętając o sprawdzeniu `tw_s <= fw and th_s <= fh`).
     - Zbieraj najlepsze dopasowania (lub wybierz skalę dającą najwyższy `max_val >= threshold`) i wykonaj NMS jak dotychczas.
     - Zwracane `(x, y, tw_s, th_s)` mają już dokładny, przeskalowany rozmiar wykrytej kotwicy na klatce, dzięki czemu `compute_unclipped_table_rect` w Kroku 1 wyliczy `scale = tw_s / tpl_w` i automatycznie przeskaluje stół do `(1757, 997)`!
2. Analogicznie w `find_anchor(...)`: jeśli w skali `1.0` `max_val < threshold`, sprawdź te same skale zapasowe i zwróć najlepsze dopasowanie `(x, y, tw_s, th_s)`.

---

### Krok 3: Obsługa 3+ turniejów w `resolve_table_id` i porządek w HUD (`vision/pipeline.py`, `main.py`, `ui/hud.py`)

**Cel:** Gdy w jednej sesji w tym samym oknie pojawi się 3. lub 4. turniej (np. `#105540008` po `#105538734` i `#105538775`), system nie może wrzucać go do `table_1` i wywoływać `Blinds decreased`.

1. **W `vision/pipeline.py` (`resolve_table_id`):**
   - Zamiast sztywnych dwóch kluczy `"table_1"` i `"table_2"`, przechowuj `self._table_signatures: dict[str, np.ndarray]` oraz `self._table_last_seen: dict[str, int]` (znacznik kolejności/czasu użycia).
   - Limit jednoczesnych aktywnych sygnatur możesz ustawić np. na `max_tables = 6` (albo dynamicznie przydzielać `table_1`, `table_2`, `table_3`, ...).
   - Jeśli pojawi się nowy nagłówek ze score `< 0.94` wobec wszystkich zapisanych sygnatur:
     - Gdy `len(self._table_signatures) < max_tables`, utwórz nowy `table_{len + 1}`.
     - Gdy osiągnięto `max_tables`, nadpisz najstarszy nieużywany klucz z `self._table_last_seen` (i oznacz zmianę, żeby `main.py` mogło zresetować `StateValidator` dla tego klucza).
   - **UWAGA NA TESTY:** Sprawdź `tests/test_vision.py::test_resolve_table_id_two_games` — upewnij się, że dla 2 różnych obrazów w teście nadal zwraca kolejno `"table_1"` i `"table_2"`, a dla powtarzającego się obrazu zachowuje ten sam ID.

2. **W `main.py` + `ui/hud.py` (czyszczenie starych kart stołów w HUD):**
   - Jeśli w trybie jednego okna (`len(anchors) <= 1`) aktywny `resolved_tid` zmienił się na inny stół i stary stół nie był aktualizowany np. przez >15 sekund (`stale_timeout_sec = 15.0`), HUD nie powinien trzymać w nieskończoność nieaktualnych kart (lub może usuwać wygasłe karty przez sygnał `HudBridge.table_removed = Signal(str)` / metodę `remove_table(table_id)`).
   - W trybie 2 okien obok siebie (`len(anchors) == 2`) oba stoły są odświeżane w każdej klatce, więc żaden nie wygaśnie.

---

### Krok 4: Eliminacja duplikatów kart w obrębie jednej klatki (`vision/card_recognizer.py` + `vision/pipeline.py`)

**Cel:** Naprawić błędy typu `2s 5s 5s Jd 8s` (klatka `12592` z `232515.mp4`), gdzie dwie różne karty o podobnym wyglądzie dostają tę samą etykietę.

1. **W `vision/card_recognizer.py`:**
   - Dodaj metodę `recognize_candidates(self, card_roi: np.ndarray, top_k: int = 3) -> list[tuple[str, float]]`:
     - Zwraca listę unikalnych kodów kart (po złączeniu wariantów np. `5s` i `5s_board` bierzemy wyższy score dla danego kodu karty!) posortowaną malejąco po `score`, ograniczoną do wyników `>= self.threshold` (max `top_k`).
   - Dotychczasowa metoda `recognize(card_roi)` pozostaje bez zmian w sygnaturze `(card | None, best_score)` i korzysta z najlepszego kandydata.

2. **W `vision/pipeline.py` (`process_frame`):**
   - Dla `hero_card_1..2` oraz `board_card_1..5` zbierz listy kandydatów przez `recognize_candidates(..., top_k=3)`.
   - Przypisuj karty zachłannie od najwyższego `score` (lub najpierw sloty o najwyższym `top_1_score`, rezerwując `used_cards: set[str]`):
     - Na klatce `12592` `Board Card 2` ma `5s (1.000)`, więc rezerwuje `5s`.
     - `Board Card 3` ma kandydatów `[('5s', 0.927), ('8c', 0.924)]` — ponieważ `5s` jest już zajęte przez `Board Card 2` z wynikiem `1.000`, `Board Card 3` automatycznie wybiera drugiego kandydata `8c (0.924)` zamiast produkować duplikat!
   - **UWAGA NA KARTY HERO POZA TURĄ:** Jeśli nie jest tura Hero (`not is_hero_turn`), `board_cards` można pominąć (dla szybkości), ale `hero_cards` **zawsze** odczytuj (żeby `TableTracker` prawidłowo wykrywał nowe rozdanie).

---

### Krok 5: Stabilizacja HUD (Anty-migotanie podczas pojedynczych klatek animacji) (`main.py`)

**Cel:** Podczas pojedynczej klatki animacji żetonów lub rozdawania kart HUD nie powinien natychmiast mrugać z np. `ALL_IN` na `WAIT` i z powrotem.

1. W `main.py` (`processing_loop`), utrzymuj słownik `last_valid_decisions: dict[str, tuple[float, Decision, str]]` (czas w sekundach, ostatnia decyzja niebędąca `WAIT`, ostatni `scan_summary`).
2. Jeśli bieżąca klatka dla `resolved_tid` ma `state.is_hero_turn == True`, ale `state.is_valid == False` (np. chwilowy brak stacka w trakcie animacji przesuwania żetonów) **oraz** od ostatniej ważnej decyzji na tym stole minęło mniej niż `0.4 s`, wstrzymaj wysłanie `WAIT` do HUD-a (utrzymaj poprzednią rekomendację na ekranie).
3. Jeśli `state.is_hero_turn == False` lub minęło `>= 0.4 s`, normalnie wyślij `WAIT`.

---

## 4. Lista Kontrolna Testów i Weryfikacji

### A. Nowe testy jednostkowe (obowiązkowe):
1. `tests/test_vision.py`:
   - `test_find_all_anchors_multiscale`: obraz z kotwicą przeskalowaną o `1.3x` zostaje wykryty i zwraca przeskalowane `(x, y, w, h)`.
   - `test_compute_unclipped_table_rect_negative_offsets`: sprawdza zachowanie ujemnych `tx, ty` bez przycinania do `0`.
   - `test_card_recognizer_collision_resolution`: dwie karty w `VisionPipeline`, gdzie druga ma najwyższy score dla tej samej karty co pierwsza, ale drugiego kandydata powyżej progu — brak duplikatu.
   - `test_resolve_table_id_more_than_two_tables`: 3 różne turnieje (`#1`, `#2`, `#3`) otrzymują 3 różne ID bez mieszania `table_1`.
2. `tests/test_ui_and_main.py`:
   - `test_processing_loop_uses_unclipped_canonical_rect`: weryfikuje, że ścieżka przez `main.py` (z wykrytym anchorem i ujemnym offsetem) daje identyczny wynik `TableState` co bezpośrednie `pipeline.process_frame(frame, table_rect=None)`.

### B. Weryfikacja na realnych nagraniach (przez pełną ścieżkę `main.py`, NIE tylko `pipeline.process_frame`!):
Uruchom skrypt weryfikacyjny używający dokładnie tej samej ścieżki co `main.py` (`find_all_anchors` → `compute_unclipped_table_rect` → `pipeline.process_frame` → `StateValidator` → `evaluate_candidates` → `DecisionMaker`) i potwierdź:
1. **`Nagrywanie 2 gry na raz , przeskakujące okna.mp4`:**
   - Klatka **`1383`**: `Hero: [Ks, 9s]`, `Board: [3s, Ac, Ah]`, `bet 0`, `Prize: $1.5`, `VALID`, decyzja != `WAIT`.
   - Klatka **`1627`**: `Hero: [Ks, 9s]`, `Board: [3s, Ac, Ah]`, `S0 bet: 40` (NIE `4`!), `Prize: $1.5`, `VALID`, decyzja != `WAIT`.
   - Klatka **`2418`**: `Hero: [4d, Qs]`, `S0: 440`, `VALID`, osobne `table_id`.
   - Klatka **`2605`**: `Hero: [4d, Qs]`, `Board: [5d, 8c, Jh]`, `VALID`.
   - Klatka **`8614`**: nowy `table_id` (brak błędu `Blinds decreased from (20, 40) to (15, 30)`!).
2. **`Nagrywanie 2026-11-19 211257.mp4`:**
   - Klatka **`2500`**: kotwica wykryta automatycznie (skala ~`1.3x`), `Hero Turn: True`, odczytane `hero_cards`, `stacki`, `pot` i `blinds`.
3. **`Nagrywanie 2026-11-18 232515.mp4`:**
   - Klatka **`12592`**: brak błędu `Duplicate cards detected` na boardzie (`2s 5s 8c Jd 8s` zamiast `2s 5s 5s Jd 8s`).
4. Pełny `pytest -v tests/` przechodzi w **100%** bez żadnych regresji.
