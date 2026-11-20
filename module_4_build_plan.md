# Plan Budowy — Moduł 4: Silnik Matematyczny Preflop i Postflop (`engine/`)

**Rola tego dokumentu:** Instrukcja krok po kroku dla osobnego agenta realizującego **Część 4** projektu `poker_assistant` równolegle z innymi agentami.

---

## 0. Zasady Pracy Równoległej (Przeczytaj przed startem!)

1. **Przeczytaj `CONSTITUTION.md`** w głównym katalogu projektu.
2. **Zasada braku konfliktów:** Ponieważ inni agenci równolegle budują inne moduły, **TWORZYSZ I EDYTUJESZ WYŁĄCZNIE PONIŻSZE PLIKI**:
   * `engine/__init__.py`
   * `engine/preflop_nash.py`
   * `engine/monte_carlo.py`
   * `engine/flop_db.py`
   * `engine/solver_builder.py`
   * `data/preflop_tables/nash_3max.json`
   * `tests/test_engine.py`
3. **Czego NIE dotykasz:** NIE twórz ani nie edytuj `core/`, `config.json`, `requirements.txt`, `vision/`, `state/`, `strategy/`, `ui/` ani `tools/`.
4. **Budżet czasowy:** Odczyt preflop musi trwać `< 0.001 s`, a symulacja Monte Carlo `< 0.1 s`.

---

## Krok 1: `engine/preflop_nash.py` oraz `data/preflop_tables/nash_3max.json`

Zbuduj szybki silnik tablic Nasha dla 3-osobowego formatu Hyper-Turbo (`3.75–15 BB`) trzymany w pamięci RAM.

1. **Funkcja `hand_to_canonical(cards: list[str]) -> str`:**
   * Zamienia dwie karty (np. `["Qh", "4h"]`) na kanoniczną notację 169 rąk startowych:
     * Para: `"77"` (dla `["7c", "7d"]`).
     * Suited (ten sam kolor): wyższa figura pierwsza + `"s"`, np. `"Q4s"`.
     * Offsuit (różne kolory): wyższa figura pierwsza + `"o"`, np. `"AKo"`.
   * Kolejność rang: `"23456789TJQKA"`. Jeśli `len(cards) != 2`, rzuć `ValueError`.
2. **Plik `data/preflop_tables/nash_3max.json`:**
   * Utwórz kompletny plik JSON z bazowymi tabelami Nasha dla przedziałów stacków (`"4"`, `"6"`, `"8"`, `"10"`, `"12"`, `"15"` BB) i kluczowych sytuacji (`spot`):
     * `"BTN_OPEN"` (decyzje: `ALL_IN`, `MIN_RAISE`, reszta `FOLD`)
     * `"SB_OPEN"` (decyzje: `ALL_IN`, `MIN_RAISE`, reszta `FOLD`)
     * `"SB_VS_BTN_SHOVE"` (`CALL` / `FOLD`)
     * `"BB_VS_BTN_SHOVE"` (`CALL` / `FOLD`)
     * `"BB_VS_SB_SHOVE"` (`CALL` / `FOLD`)
     * `"BB_ISO_VS_LIMP"` (`ALL_IN` / `CHECK`)
   * Dla każdego spota podaj listy rąk kanonicznych (np. `"AA"`, `"KK"`, `"AKs"`, `"A2s"`, `"K9o"`, itd.).
3. **Klasa `PreflopNashEngine`:**
   * `__init__(self, tables_path: str | Path = "data/preflop_tables/nash_3max.json")`: wczytuje JSON do pamięci RAM i konwertuje listy rąk na `set[str]` dla błyskawicznego wyszukiwania `O(1)`.
   * `get_action(self, hero_cards: list[str], effective_bb: float, spot: str) -> tuple[str, float]`:
     * Wybiera najbliższy próg stacka z tabeli (`4, 6, 8, 10, 12, 15`).
     * Zwraca `(action, estimated_ev_bb)`, np. `("ALL_IN", 0.45)` lub `("FOLD", 0.0)`.

---

## Krok 2: `engine/monte_carlo.py` (Symulator `< 0.1 s`)

Zaimplementuj szybki kalkulator Equity i EV dla sytuacji postflop i niestandardowych spotów.

* Użyj biblioteki `phevaluator` (`from phevaluator import evaluate_cards`). Jeśli w środowisku testowym nie jest zainstalowana, rzuć czytelny `ImportError` lub użyj prostego fallbacku (ale preferuj `phevaluator`).
* **Klasa `MonteCarloCalculator`:**
  * `estimate_equity(self, hero_cards: list[str], board_cards: list[str], villain_range: list[tuple[str, str]] | None = None, iterations: int = 2000, time_budget_ms: float = 80.0) -> float`:
    * Buduje talię 52 kart bez kart z `hero_cards` i `board_cards`.
    * W pętli (do `iterations` lub do przekroczenia `time_budget_ms` mierzonego przez `time.perf_counter()`):
      * Losuje brakujące karty boardu (do 5 kart) oraz 2 karty dla rywala (z `villain_range` bez kolizji lub z pozostałej talii).
      * Porównuje siłę ręki Hero (`evaluate_cards(*(hero_cards + full_board))`) i rywala (`evaluate_cards(*(villain_cards + full_board))` — w `phevaluator` mniejsza liczba oznacza silniejszy układ!).
      * Zlicza wygrane (`+1.0`) i remisy (`+0.5`).
    * Zwraca `equity` w zakresie `0.0–1.0`.
  * `calculate_ev_bb(self, equity: float, pot_bb: float, call_cost_bb: float, fold_equity: float = 0.0) -> float`:
    * Dla prostego sprawdzenia (`fold_equity == 0.0`): `EV = equity * (pot_bb + call_cost_bb) - (1 - equity) * call_cost_bb`.
    * Dla zagrania z fold equity (np. shove): `EV = fold_equity * pot_bb + (1 - fold_equity) * (equity * (pot_bb + call_cost_bb) - (1 - equity) * call_cost_bb)`.

---

## Krok 3: `engine/flop_db.py` (Izomorfizm 1 755 Kanonicznych Flopów)

Zaimplementuj redukcję 22 100 flopów do **1 755 kanonicznych flopów** przez symetrię kolorów oraz klasę odpytującą bazę offline.

1. **Funkcja `canonicalize_flop(board_cards: list[str]) -> tuple[str, dict[str, str]]`:**
   * Przyjmuje 3 karty flopa (np. `["Qd", "Qs", "8d"]`).
   * Sortuje karty malejąco według rangi (`A` najwyższe, `2` najniższe). Przy równej randze ustala deterministyczną kolejność kolorów.
   * Przypisuje kolorom w kolejności pierwszego wystąpienia etykiety `"a"`, `"b"`, `"c"` (np. `{"d": "a", "s": "b"}`).
   * Zwraca `(klucz_kanoniczny, suit_map)`, np. `("QaQb8a", {"d": "a", "s": "b"})`.
2. **Funkcja `generate_all_1755_flops() -> list[str]`:**
   * Generuje wszystkie kombinacje 3 kart z 52 (`itertools.combinations`), przepuszcza przez `canonicalize_flop`, zbiera unikalne klucze i zwraca posortowaną listę.
   * Matematycznie lista musi mieć dokładnie **1755** elementów.
3. **Klasa `FlopDatabase`:**
   * `__init__(self, db_path: str | Path = "data/postflop_db/flops_1755.json")`:
     * Jeśli plik istnieje, wczytuje go do słownika w RAM. Jeśli jeszcze nie istnieje, przechowuje pusty słownik (działa bezpiecznie bez błędu).
   * `lookup(self, board_cards: list[str], hero_cards: list[str], effective_bb: float) -> dict[str, float] | None`:
     * Kanonizuje flop, mapuje kolory `hero_cards` przez `suit_map` i szuka wpisu w słowniku.
     * Zwraca słownik EV/częstości dla `{"CHECK": ..., "BET_30": ..., "ALL_IN": ...}` lub `None`, jeśli brak wpisu.

---

## Krok 4: `engine/solver_builder.py` (Skrypt Wsadowy Offline dla TexasSolver)

Napisz skrypt CLI umożliwiający jednorazowe wygenerowanie bazy 1 755 flopów przy użyciu lokalnej binarki `TexasSolver`:
* Argumenty CLI (`argparse`):
  * `--solver-bin <ścieżka>` (ścieżka do `console_solver.exe`)
  * `--out <ścieżka>` (domyślnie `data/postflop_db/flops_1755.json`)
  * `--limit <int>` (opcjonalny limit flopów do przeliczenia w jednej sesji, np. do testów)
  * `--dry-run` (flaga: generuje listę 1 755 flopów i przykładowy skrypt wejściowy dla TexasSolver bez uruchamiania `.exe`)
* Dla każdego flopa buduje uproszczone drzewo zakładów (`Check`, `Bet 30%`, `All-in`), obsługuje wznawianie (pomija flopy już zapisane w `--out`) i zapisuje wyniki inkrementalnie.

---

## Krok 5: Testy Jednostkowe `tests/test_engine.py`

Napisz testy w `pytest`:
1. `test_hand_to_canonical`: sprawdza pary (`"77"`), suited (`"Q4s"`), offsuit (`"AKo"`) oraz błąd dla złej liczby kart.
2. `test_preflop_nash_lookup_and_speed`: ładuje `data/preflop_tables/nash_3max.json`, sprawdza decyzje dla `"AA"` i `"72o"`, oraz weryfikuje czas zapytania `< 5 ms`.
3. `test_monte_carlo_equity_and_budget`: sprawdza `estimate_equity(["As", "Ah"], ["Kd", "7c", "2s"]) > 0.70` i czas wykonania `< 150 ms`.
4. `test_generate_all_1755_flops`: weryfikuje, że `len(generate_all_1755_flops()) == 1755`.
5. `test_flop_db_missing_file_safe`: sprawdza, że `FlopDatabase` dla nieistniejącego pliku w `tmp_path` zwraca `None` przy `lookup(...)`.

### Kryterium odbioru
Uruchom w terminalu:
```bash
pytest -v tests/test_engine.py
python -m engine.solver_builder --dry-run
```
Oba polecenia muszą zakończyć się kodem wyjścia `0`.
