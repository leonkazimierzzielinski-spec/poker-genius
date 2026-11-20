# Plan Kompleksowego Audytu i Diagnostyki V5 (`poker_assistant`)

Dokument stanowi pełną instrukcję dla agentów w Antigravity. Celem tej tury **NIE jest modyfikacja kodu produkcyjnego**, lecz maksymalnie dokładne przeskanowanie **wszystkich 5 nagrań w `nagrania testowe/`** przez pełną ścieżkę produkcyjną `main.py` oraz przygotowanie jednej paczki **`audit_pack_v5.zip`** z kompletem danych potrzebnych do ostatecznej naprawy wszystkich wykrytych i podejrzewanych błędów.

> **ZASADA NADRZĘDNA:** NIE modyfikuj żadnych plików projektu (`core/`, `vision/`, `state/`, `engine/`, `strategy/`, `ui/`, `main.py`, `config.json`, `data/templates/`). Wszystkie skrypty robocze uruchom i posprzątaj po wygenerowaniu `audit_pack_v5.zip`.

---

## 1. Lista 9 Podejrzewanych Błędów i Ryzyk (Co dokładnie badamy)

Poniższa tabela opisuje wszystkie obszary, w których podejrzewamy ukryte błędy w logice, OCR lub strategii:

| Nr | Podejrzewany błąd / ryzyko | Co konkretnie chcemy zmierzyć i sprawdzić |
|---|---|---|
| **B1** | **Mylenie kart na innych skalach (np. `Jc 4d` → `Ac 8d` na `211257` f3643)** | Czy problemem jest obniżony próg, brak szablonu `Jc.png`/`4d`, przesunięcie `tx = -198`, czy rozmycie `INTER_LINEAR` przy zmniejszaniu z `1.28x` do `1.0x`. |
| **B2** | **Gracz na All-In (`"All-In"` zamiast `0` w stacku)** | Ile klatek we wszystkich nagraniach odpada błędem `Missing stack reading`, mimo że suma niepustych stacków + `pot` == `900` (jeden lub dwóch graczy ma napis `"All-In"`). |
| **B3** | **Brakujące lub mylone karty z całej talii 52 kart** | Które z 52 szablonów kart (`2c..As`) faktycznie istnieją w `data/templates/cards/`, jakie mają wymiary, czy brakuje wariantów `hero` vs `board` i które pary kart mają najniższy margines między `Top 1` a `Top 2` (ryzyko pomyłki). |
| **B4** | **Przesłanianie kart Hero przez badge akcji (`Call`, `Check`, `Fold`, `Raise`)** | Jak często po akcji Hero (jak na `211257` f3668 z niebieskim napisem `Call` na dole kart) znika odczyt `hero_cards` i czy wycinek `hero_card_1/2` zahacza o ten napis. |
| **B5** | **Nadmierne rekomendowanie `ALL_IN` postflop (Monte Carlo)** | Na klatkach postflop (np. `1383`, `1627`, `2500`) aplikacja bardzo często krzyczy `ALL_IN` z ogromnym `+EV` (`+4.61 BB`, `+10.74 BB`, `+3.33 BB`). Sprawdźmy dokładny rozkład `equity`, `check_ev`, `bet_ev`, `call_ev`, `shove_ev` (czy wzór `calculate_ev_bb` z `fold_equity=0.40` i losowym zakresem rywala nie zawyża absurdalnie EV shova!). |
| **B6** | **Błędy rozpoznawania spotu Preflop (`determine_preflop_spot`)** | Czy w sytuacjach: (a) Hero na BTN po limpie/raisie vs SB/BB All-In (`211257` po f3863), (b) Heads-Up, (c) multiway limped pot, (d) SB vs BTN min-raise — `determine_preflop_spot` przypisuje właściwy spot i właściwy `effective_bb`. |
| **B7** | **Odczyt zakładów (`current_bet`) i `pot` przy 3-cyfrowych kwotach i sklejonych cyfrach** | Jak często `seat_0/1/2_bet` lub `seat_0/1/2_stack` zwraca błędne liczby (np. `0`, obcięta cyfra, `None`) przy betach typu `120`, `166`, `240`, `444` i czy ROI `seat_0/1/2_bet` nie ucina 3-cyfrowych zakładów. |
| **B8** | **Wykrywanie tury Hero (`detect_hero_actions`) i `available_actions`** | Czy są klatki, na których jest tura Hero, a system zwraca `is_hero_turn=False` (np. gdy pasek timera już się kończy i ma `< 500` fioletowych pikseli!), albo klatki, gdzie `CHECK` jest pomylone z `CALL` przy becie rywala. |
| **B9** | **Multi-tabling, zmiana turniejów i wydajność (Latency)** | Jak często pojawiają się fałszywe błędy `Blinds decreased`, ile unikalnych `table_id` powstaje na całych nagraniach oraz jakie są średnie i P95 czasy przetwarzania (`latency_ms`) na klatkę w pełnej ścieżce `main.py`. |

---

## 2. Instrukcja Wykonania dla Agenta (Krok po Kroku)

### Krok 1: Utworzenie folderu roboczego i skopiowanie aktualnego kodu
Utwórz folder `audit_pack_v5/` w głównym katalogu projektu i skopiuj do niego **aktualny** stan kodu:
- `vision/` (cały folder)
- `state/` (`validator.py`, `tracker.py`)
- `engine/` (`preflop_nash.py`, `monte_carlo.py`, `flop_db.py`)
- `strategy/` (cały folder)
- `core/` (`constants.py`, `contracts.py`)
- `ui/hud.py`
- `main.py`
- `config.json`
- `data/preflop_tables/nash_3max.json` (tylko JSON, bez ciężkich plików wideo)

### Krok 2: Audyt statyczny szablonów kart (`audit_pack_v5/diagnostics/01_templates_audit.md`)
Napisz i uruchom skrypt diagnostyczny, który sprawdzi `data/templates/cards/`:
1. Wylistuje wszystkie obecne pliki `.png` wraz z ich wymiarami `(w, h)`.
2. Sprawdzi, których kart z pełnej talii 52 kart (`2..A` x `c,d,h,s`) brakuje całkowicie, a które mają wariant `_board` / `_hero`.
3. Obliczy macierz podobieństwa (cross-correlation `TM_CCOEFF_NORMED`) między wszystkimi szablonami kart i wypisze **Top 20 najbardziej podobnych par RÓŻNYCH kart** (np. `Jc` vs `Ac`, `4d` vs `8d`, `3s` vs `5s`, `9s` vs `Qs`) wraz z ich wynikiem podobieństwa — to pokaże dokładnie, które karty mogą się mylić.

### Krok 3: Pełny skan statystyczny WSZYSTKICH 5 nagrań przez ścieżkę `main.py` (`audit_pack_v5/diagnostics/02_full_videos_stats.md` + `02_stats.json`)
Dla **każdego pliku `.mp4` w `nagrania testowe/`** przeskanuj całe nagranie co **30 klatek** (co 1 sekundę wideo) używając **dokładnie pełnej ścieżki z `main.py`** (`find_all_anchors` → `compute_unclipped_table_rect` → `pipeline.process_frame` → `StateValidator` → `evaluate_candidates` → `DecisionMaker`), mierząc czas każdej klatki.

Dla każdego nagrania wylicz i zapisz w `02_full_videos_stats.md`:
1. Liczba klatek ogółem, liczba wykrytych kotwic (i wykryte skale `scale`), średnia i P95 `latency_ms`.
2. Podział statusów walidacji: `% VALID`, `% INVALID` z dokładnym zliczeniem każdej przyczyny błędu (`Missing stack reading`, `Invalid card count`, `Chip conservation failed`, `Duplicate cards detected`, `Blinds decreased`).
3. **Analiza B2 (All-In):** Ile z klatek `Missing stack reading` ma `pot + sum(non_none_stacks) == 900` (czyli fałszywy błąd przez napis `"All-In"`!).
4. **Analiza B5 (Rozkład decyzji):** Ile razy podczas `is_hero_turn == True` i `VALID` system zarekomendował `ALL_IN`, `BET_30`, `MIN_RAISE`, `CALL`, `CHECK`, `FOLD` — osobno dla `PREFLOP` i osobno dla `POSTFLOP` (`FLOP`/`TURN`/`RIVER`).
5. **Analiza B8 (Krótkie paski timera):** Ile klatek ma aktywne kolorowe przyciski (`FOLD/CALL/RAISE`), ale odrzucony fioletowy timer (`purple_px < 500`, podaj rozkład liczby fioletowych pikseli w przedziale `50..500`).
6. **Analiza B9 (Turnieje):** Lista wykrytych `table_id` oraz liczba wystąpień `Blinds decreased`.

### Krok 4: Głęboka analiza 25–30 kluczowych klatek i wycinków (`audit_pack_v5/diagnostics/frames/` + `03_deep_frame_audit.md`)
Wybierz i zapisz **25–30 konkretnych klatek** pokrywających wszystkie 9 podejrzeń (B1–B9):
- **Obowiązkowe klatki z `Nagrywanie 2026-11-19 211257.mp4`:**
  - `2500`, `3643` (pomyłka `Jc 4d` → `Ac 8d`), `3668` (badge `Call` na kartach), `3863` (`S1` na `"All-In"`),
  - **+ 2–3 kolejne klatki po `3863`** (moment, kiedy `S2` kończy ruch i przychodzi tura Hero przeciwko All-Inowi `166`!).
- **Obowiązkowe klatki z `Nagrywanie 2 gry na raz , przeskakujące okna.mp4`:**
  - `1383`, `1627` (postflop `ALL_IN` z `+10.74 BB`), `2418`, `2605`, `5400`, `6900`, `8614`.
- **Po 3–4 najciekawsze klatki z pozostałych nagrań (`224127`, `223258`, `232515`):**
  - przynajmniej 2 klatki z graczem na `"All-In"` (gdzie `stack is None` i `pot + stacks == 900`),
  - przynajmniej 3 klatki z tury Hero **POSTFLOP** (z pełnym zrzutem `equity`, `candidate_evs`, `exploited_evs`, `decision`),
  - przynajmniej 2 klatki z tury Hero w **Heads-Up**,
  - przynajmniej 2 klatki, gdzie `is_hero_turn=False` mimo widocznych przycisków (niski `purple_px`), jeśli takie wystąpią.

Dla każdej z tych 25–30 klatek zapisz w `audit_pack_v5/diagnostics/frames/<nagranie>_f<nr>/`:
- `overview.jpg` (szerokość max 1280 px, z narysowanymi prostokątami ROI i etykietami),
- wycinki po `_warp_to_canonical`: `hero_card_1.png`, `hero_card_2.png`, `board_card_1..3.png`, `seat_0_stack.png`, `seat_1_stack.png`, `seat_0_bet.png`, `seat_1_bet.png`.

W pliku `audit_pack_v5/diagnostics/03_deep_frame_audit.md` wypisz dla każdej z tych klatek:
- `anchor`, `scale`, `unclipped_rect`, `table_id`, `is_valid`, `errors`,
- **Top 5 dopasowań z `CardRecognizer`** dla `hero_card_1`, `hero_card_2` i `board_card_1..5` (dla `211257` klatki `3643` porównaj również w raporcie tekstowym score przy `INTER_LINEAR` vs `INTER_AREA` w pamięci — bez zapisu zmian w kodzie!),
- Wszystkie odczyty `DigitOCR` (`prize_pool`, `pot`, `blinds`, `S0/S1/S2 stack & bet`, `dealer`),
- Liczbę fioletowych pikseli w `seat_0_timer` oraz wynik `detect_hero_actions`,
- **Pełny ślad decyzyjny silnika strategii:** `spot`, `effective_bb`, `equity` (dla postflop), surowy słownik `candidate_evs`, słownik `exploited_evs` po `ExploitEngine`, finalna `Decision` (`action`, `ev_bb`, `profile_used`, `reason`).

### Krok 5: Test symulacji "Podgląd w przód" (`[PLAN]`) (`audit_pack_v5/diagnostics/04_preview_mode_check.md`)
Bez modyfikacji kodu, zasymuluj w skrypcie diagnostycznym na 10 klatkach spoza tury Hero (gdzie `is_hero_turn == False`, `len(hero_cards) == 2`, `is_valid == True` — w tym na klatce `3863` po wirtualnym potraktowaniu `S1` jako `stack=0, ALL_IN`):
- Co zwróciłby `evaluate_candidates` + `DecisionMaker`, gdyby wyliczyć `available_actions` ze stanu stołu (`FOLD/CALL/ALL_IN` gdy `max_opp_bet > hero_bet`, albo `CHECK/BET_30/ALL_IN` gdy `max_opp_bet == hero_bet`).
- Zapisz wyniki w tabeli w `04_preview_mode_check.md`, aby zweryfikować, czy podgląd w przód daje sensowne rekomendacje.

### Krok 6: Spakowanie i posprzątanie
1. Uruchom `pytest -v tests/` i zapisz wynik do `audit_pack_v5/diagnostics/00_pytest_results.txt`.
2. Spakuj cały folder `audit_pack_v5/` do pliku **`audit_pack_v5.zip`** w głównym katalogu projektu (upewnij się, że nie zawiera plików `.mp4` i waży najwyżej ok. 5–10 MB).
3. Usuń roboczy folder `audit_pack_v5/` oraz wszystkie tymczasowe skrypty pomocnicze — zostaw wyłącznie `audit_pack_v5.zip`.
4. W odpowiedzi wypisz krótkie podsumowanie kluczowych liczb z `02_full_videos_stats.md` oraz rozmiar archiwum `audit_pack_v5.zip`.
