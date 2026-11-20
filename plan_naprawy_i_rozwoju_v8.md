# Plan Naprawy i Rozwoju V8 — Board na Skalowanych Stołach, Precyzja Kart, Tracker/Exploit i Sanity-Check Postflop (`poker_assistant`)

Dokument stanowi kompletną specyfikację jednej, dużej rundy prac dla agentów w Antigravity po audycie commita `0379b74` (V7) oraz zrzutów użytkownika z klatek `2604 / 2640 / 2696` (`Nagrywanie 2026-11-19 211257.mp4`).

---

## 1. Zestawienie Wszystkich Wykrytych Błędów (7 Obszarów)

| Nr | Plik(i) | Wykryty błąd / przyczyna źródłowa | Planowana naprawa |
|---|---|---|---|
| **1** | `vision/card_recognizer.py` (L92), `config.json` / `vision/pipeline.py` | **Brak odczytu boardu (`Board: --`) na `211257` f2604/2640/2696 (`7d Td Th 2h`):** `badge_cut_h = int(roi_h * 0.68)` ucina dolne 32% również dla kart boardu (mimo że `slot_hint` jest przekazywane, ale nieużywane!), a na skali `1.28x` karty boardu mają lekko inne położenie pionowe/poziome w ROI. | Stosować `badge_cut_h = 0.68` **wyłącznie dla `hero_card_1/2`**, a dla `board_card_1..5` używać pełnej wysokości (`95%`). Zbadać dokładne wycinki `board_card_1..4` na `211257` f2604 i skorygować geometrię/segmentację `7d Td Th 2h` bez psucia pozostałych 4 nagrań. |
| **2** | `vision/card_recognizer.py` (L173–228) | **Mylenie pojedynczych kart na boardzie (`232515` f12592: `2c 5s 5c 4d 8s` zamiast `2s 5s 8c Jd 8s`):** Skalowanie `rank_crop` bez zachowania proporcji (aspect ratio) rozciąga wąskie `J` na szerokość `4`, a sztywne `mid_ratio <= 0.50` potrafi pomylić `2s` z `2c`. | Zachować proporcje (letterboxing / aspect-preserving resize na stałym płótnie, np. `24x32` dla rang i `24x24` dla kolorów) przed `matchTemplate` + skalibrować rozróżnianie `c`/`s` i `8`/`5` na wszystkich 5 nagraniach. |
| **3** | `vision/card_recognizer.py` (L33–38) | **Łamliwa ścieżka względna `_use_rank_suit`:** Jeśli aplikacja zostanie uruchomiona z innego katalogu roboczego niż root repozytorium, `self.templates_dir.resolve() == Path("data/templates/cards").resolve()` zwraca `False` i cicho wyłącza nowy silnik `Rank + Suit`. | Wyznaczać domyślne `ranks_dir` i `suits_dir` relatywnie do `Path(__file__).resolve().parent.parent / "data/templates/..."` (a tryb legacy włączać tylko wtedy, gdy caller przekazał jawnie niestandardowe `templates_dir` bez `ranks`/`suits`). |
| **4** | `state/validator.py` / `main.py` | **Fałszywe wejście w `PREFLOP` (`BB_ISO_VS_LIMP`) przy nieodczytanym boardzie:** Na f2604 `Pot: 218` i wszyscy gracze mają `bet: 0`, ale ponieważ `board_cards == []`, silnik uznał, że to Preflop i podał `CHECK (+0.05 BB)` na Turnie z dwiema parami! | Dodać twardą regułę logiczną (Postflop Pot Sanity Check): jeśli `pot > small_blind + big_blind` i `all(p.current_bet == 0 for p in players.values())` oraz `len(board_cards) == 0`, to jest to na 100% nieodczytany board postflop — oznaczyć klatkę błędem `Missing board cards on postflop pot` (żeby nigdy nie grać tabeli preflop na flopie/turnie/riverze!). |
| **5** | `state/tracker.py` (L62–68) | **Fałszywe wykrywanie `NEW_HAND` przy każdym starcie tury Hero preflop:** Warunek `prev_state.street in (..., "WAITING_FOR_TURN") and state.street == "PREFLOP"` traktuje każde przejście `WAITING_FOR_TURN -> PREFLOP` jako nowe rozdanie, zawyżając `hand_number` i kasując `last_reaction_ms` z tego rozdania! | Usunąć `"WAITING_FOR_TURN"` z warunku `street_reset` (nowe rozdanie z resetu ulicy to wyłącznie przejście z `FLOP`/`TURN`/`RIVER` do `PREFLOP` lub zmiana kart Hero / zmiana dealera). |
| **6** | `strategy/exploit.py` (L55–65) + `state/tracker.py` (L97–125) | **Błędne `Timing Tell: fast check <500ms` odpalane po szybkim BECIE rywala:** `TableTracker` zapisuje `last_reaction_ms` wyłącznie przy `curr_p.current_bet > prev_p.current_bet` (bet/raise), a `ExploitEngine` interpretuje to jako „fast check” i dodaje bonus do blefu `BET_30`! | W `ExploitEngine`: aplikować `Timing Tell: fast check <500ms` tylko wtedy, gdy rywal rzeczywiście **nie zabetował** (`current_bet == 0` na ulicy postflop, albo gdy `tracker` zarejestruje brak betu po przejściu tury), nigdy po czyimś raisie/becie. |
| **7** | `vision/capture.py`, `main.py` | **Brak obsługi drugiego monitora w trybie `--mode live`:** `dxcam.create()` zawsze nagrywa wyłącznie monitor `0`. | Dodać opcjonalny parametr CLI `--monitor <int>` (domyślnie `0`) przekazywany do `LiveScreenCapture(output_idx=args.monitor)` -> `dxcam.create(output_idx=self.output_idx, ...)`. |

---

## 2. Szczegółowe Instrukcje Implementacji (Krok po Kroku)

### Krok 1: Naprawa odczytu boardu na `211257` i precyzji `Rank + Suit` (`vision/card_recognizer.py` + `vision/pipeline.py` + `config.json`)

1. **Diagnoza klatki `2604` (`211257.mp4`):**
   - Wypisz wycinki `rois["board_card_1..4"]` na klatce `2604` po `_warp_to_canonical` i sprawdź dokładnie:
     - Jakie jest `white_fraction`, `red_count`, wykryte `boxes` oraz dopasowanie rangi i koloru dla każdej z 4 kart (`7d`, `Td`, `Th`, `2h`).
     - Sprawdź, czy problemem jest wyłącznie `badge_cut_h = 0.68`, czy również lekkie przesunięcie `y` / `x` boardu w `211257` (pamiętaj o `compute_unclipped_table_rect` w `vision/anchor.py`!).
2. **Wykorzystanie `slot_hint` w `vision/card_recognizer.py`:**
   - W `_recognize_rank_suit_candidates(..., slot_hint=slot_hint)`:
     - Jeśli `slot_hint in ("hero_card_1", "hero_card_2")`: stosuj `badge_cut_h = int(roi_h * 0.68)` (odcinanie badge'y `Call`/`Bet`/`Check`).
     - Jeśli `slot_hint` zaczyna się od `"board_card"` (lub `None` dla boardu): stosuj `badge_cut_h = int(roi_h * 0.96)` (pełna wysokość karty bez obcinania symbolu koloru!).
3. **Aspect-preserving normalization dla rang i kolorów (naprawa `232515` f12592 i `T` / `J` / `8`):**
   - Zamiast rozciągać wąską literę `J` lub `1` do pełnej szerokości szablonu `K`/`Q`/`4`, napisz mały helper `_fit_glyph_to_box(crop, target_w, target_h)` (skaluje z zachowaniem proporcji do maksymalnego rozmiaru mieszczącego się w `(target_w, target_h)` i centruje na czarnym tle `0`), stosowany spójnie zarówno przy wczytywaniu szablonów (albo na tym samym stałym boxie `24x32` dla rang i `24x24` dla kolorów), jak i w czasie rozpoznawania.
   - Zadbaj szczególnie o 2-znakową rangę **`T` (`10`)** na boardzie (klatka `2604` ma **`Td`** i **`Th`** obok siebie!): zweryfikuj próg scalania `1` i `0` (`abs(by1 - ry) <= 8 and bx1 < rx + rw + 15`) tak, aby nigdy nie rozbijał `10` na samo `1` lub `0`, i jednocześnie nie sklejał rangi z symbolem koloru ani krawędzią sąsiedniej karty.
   - Sprawdź na klatce `12592` (`232515.mp4`), aby board rozpoznał się dokładnie jako **`['2s', '5s', '8c', 'Jd', '8s']`** (bez pomyłki `2s->2c`, `8c->5c`, `Jd->4d`).
4. **Niezawodne ścieżki szablonów (`__init__`):**
   - Użyj `Path(__file__).resolve().parent.parent / "data/templates"` jako bazy dla domyślnych ścieżek `cards`, `ranks`, `suits`, aby uruchomienie aplikacji z dowolnego katalogu roboczego zawsze włączało tryb `Rank + Suit`.
   - Zachowaj 100% kompatybilności wstecznej dla testów przekazujących własny `templates_dir=tmp_path`.

---

### Krok 2: Sanity-Check Postflop w Walidatorze (`state/validator.py`)

W `StateValidator.validate(state)`:
- Dodaj regułę chroniącą przed traktowaniem nierozpoznanego boardu jako Preflop:
  ```python
  all_bets_zero = all(p.current_bet == 0 for p in state.players.values())
  if (
      len(state.board_cards) == 0
      and state.pot > (state.small_blind + state.big_blind)
      and all_bets_zero
      and state.pot < self.total_chips
  ):
      errors.append("Missing board cards on postflop pot")
  ```
- **Uwaga na testy jednostkowe:** Sprawdź wszystkie istniejące testy w `tests/test_state.py` i `tests/test_ui_and_main.py`, czy żaden syntetyczny test nie ustawia ręcznie `pot > sb + bb`, `bets == 0` i `board_cards == []` z oczekiwaniem `is_valid == True` (np. w testach `test_validator_valid_sum_900` — jeśli tak, dopasuj warunek lub zaktualizuj komentarz/test tylko jeśli był nierealistyczny, ale lepiej nie psuć żadnych istniejących asercji!).

---

### Krok 3: Naprawa `TableTracker` i `ExploitEngine` (`state/tracker.py` + `strategy/exploit.py`)

1. **W `state/tracker.py` (`update`, linie 62–66):**
   - Zmień `street_reset` na:
     ```python
     street_reset = (
         self.prev_state.street in ("FLOP", "TURN", "RIVER")
         and state.street == "PREFLOP"
     )
     ```
   - Dzięki temu wejście w turę Hero na preflopie (`WAITING_FOR_TURN -> PREFLOP`) nie resetuje już rozdania ani nie nabija fałszywego `hand_number`.
2. **W `strategy/exploit.py` (`apply_exploits`, linie 55–65):**
   - Warunek `has_fast_check` powinien dodatkowo wymagać `getattr(p, "current_bet", 0) == 0` (szybki check ma sens tylko gdy rywal ma `bet == 0`, nigdy po jego becie lub raisie!).

---

### Krok 4: Obsługa wyboru monitora `--monitor` (`vision/capture.py` + `main.py`)

1. W `vision/capture.py` (`LiveScreenCapture.__init__`):
   - Dodaj opcjonalny parametr `output_idx: int = 0` i przekazuj go do `dxcam.create(output_idx=self.output_idx, region=self.region, max_buffer_len=4)`.
2. W `main.py`:
   - Dodaj flagę CLI `--monitor` (`type=int`, `default=0`, opis: `"Monitor index for live dxcam capture (0 = primary, 1 = secondary)"`) i przekazuj `LiveScreenCapture(output_idx=args.monitor)`.

---

## 3. Obowiązkowa Weryfikacja i Testy

1. **Nowe testy jednostkowe:**
   - `tests/test_vision.py`: test `CardRecognizer` w trybie `Rank + Suit` sprawdzający, że `slot_hint="board_card_1"` NIE ucina dolnych 32% oraz że domyślne ścieżki działają niezależnie od `os.chdir(tmp_path)`.
   - `tests/test_state.py`:
     - test `TableTracker`, że przejście `WAITING_FOR_TURN -> PREFLOP` z tymi samymi kartami Hero NIE generuje fałszywego `NEW_HAND`,
     - test `StateValidator`, że `pot=218, bets=0, board_cards=[]` zwraca `INVALID` (`Missing board cards on postflop pot`).
   - `tests/test_strategy.py`: test `ExploitEngine`, że `last_reaction_ms < 500` przy `current_bet > 0` NIE odpala `"Timing Tell: fast check <500ms"`.
   - `tests/test_ui_and_main.py`: test parsowania flagi `--monitor 1`.

2. **Weryfikacja na realnych nagraniach (pełna ścieżka `main.py`):**
   - **`2026-11-19 211257.mp4`:**
     - Klatki **`2604`**, **`2640`**, **`2696`**: `Hero: ['Kh', '2s']`, **`Board: ['7d', 'Td', 'Th', '2h']`**, `Street: TURN`, `VALID`, sensowna decyzja postflop (NIE `BB_ISO_VS_LIMP`!).
     - Klatki **`1827`** (`Kh 2s`), **`3220`** (`Jc 7d`), **`3643`** (`Jc 4d`), **`3668`** (`Jc 4d` z badge `Call`), **`3863`**, **`3880`** (`BB_VS_SB_SHOVE -> FOLD`).
   - **`2026-11-18 232515.mp4`:**
     - Klatka **`12592`**: Board dokładnie **`['2s', '5s', '8c', 'Jd', '8s']`** (weryfikacja precyzji `c/s` i `8/5`, `J/4`).
   - **`Nagrywanie 2 gry na raz , przeskakujące okna.mp4`:** `1383`, `1627`, `2418`, `2605`.
   - **`2026-11-18 224127.mp4`:** `0`, `765`, `2370`, `4950`, `12600`.
   - **Skan co 30 klatek po całym `211257` i `2 gry na raz`:** podać `% VALID` (przy widocznym stole), liczbę klatek z odczytanym boardem (przed vs po na `211257`) oraz średnią latencję.

3. **Uruchomić `pytest -v tests/`** — 100% testów musi przejść bez błędów.

---

## 4. Obowiązkowa Synchronizacja na GitHub (Po Zakończeniu Prac)

1. Dopisz nową sekcję na samej górze pliku **`PROGRESS_LOG.md`** z nagłówkiem `## V8 — Naprawa boardu na skalowanych stołach, precyzja Rank+Suit, Tracker/Exploit i obsługa --monitor (DATA)` zawierającą:
   - dokładną przyczynę `Board: --` na klatce `2604` (`211257`),
   - listę wszystkich wprowadzonych zmian,
   - pełną tabelę weryfikacji wszystkich wymienionych klatek (w tym `2604`, `2640`, `2696`, `12592`),
   - statystyki skanu porównawczego V7 vs V8 (ze szczególnym uwzględnieniem odczytu boardu na `211257` i latencji),
   - pełny wynik `pytest -v tests/`.
2. Sprawdź `git status` i upewnij się, że nie dodajesz żadnych plików `.mp4`, śmieci roboczych ani folderów z `.gitignore`.
3. Wykonaj:
   - `git add -A`
   - `git commit -m "V8: fix scaled board recognition, aspect-preserving rank+suit, tracker/exploit/validator fixes, monitor CLI"`
   - `git push origin main`
4. Na koniec napisz **krótkie potwierdzenie**, że `git push` zakończył się sukcesem, oraz podaj gotowe do skopiowania linki:
   - `https://github.com/leonkazimierzzielinski-spec/poker-genius/commit/<HASH>`
   - `https://github.com/leonkazimierzzielinski-spec/poker-genius/blob/main/PROGRESS_LOG.md`
