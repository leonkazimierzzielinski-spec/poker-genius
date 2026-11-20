# Plan Budowy — Moduł 1: Szkielet Projektu, Kontrakty Danych i Narzędzie Kalibracyjne

**Rola tego dokumentu:** Jest to kompletna instrukcja krok po kroku dla agenta realizującego **Część 1** projektu `poker_assistant` na podstawie `CONSTITUTION.md`. Instrukcja została napisana tak, aby każdy krok był jednoznaczny, prosty do wykonania i łatwy do przetestowania.

---

## 0. Zasady Ogólne dla Agenta (Przeczytaj przed startem)

1. **Przeczytaj `CONSTITUTION.md`** w głównym katalogu projektu przed napisaniem pierwszej linii kodu.
2. **Zakres prac (Tylko Moduł 1):** W tym zadaniu tworzysz wyłącznie strukturę katalogów, `requirements.txt`, pakiet `core/`, szablon `config.json`, narzędzie `tools/calibrator.py` oraz testy jednostkowe w `tests/`.
3. **Czego NIE robisz teraz:** Nie pisz jeszcze logiki przechwytywania ekranu (`vision/`), maszyny stanów (`state/`), silnika matematycznego (`engine/`), strategii (`strategy/`) ani nakładki HUD (`ui/`). Utwórz w tych folderach wyłącznie puste pliki `__init__.py`.
4. **Prostota i czytelność:** Używaj standardowych bibliotek Pythona (`dataclasses`, `json`, `pathlib`, `argparse`, `typing`) oraz `opencv-python` (`cv2`) dla narzędzia kalibracyjnego. Nie dodawaj zbędnych frameworków.
5. **Testy:** Po zakończeniu pracy uruchom `pytest -v` i upewnij się, że 100% testów przechodzi bez błędów.

---

## Krok 1: Utworzenie Struktury Katalogów i `requirements.txt`

Utwórz w katalogu głównym projektu `poker_assistant/` następującą strukturę folderów i pustych plików `__init__.py`:

```text
poker_assistant/
├── config.json
├── requirements.txt
├── core/
│   ├── __init__.py
│   ├── constants.py
│   └── contracts.py
├── vision/__init__.py
├── state/__init__.py
├── engine/__init__.py
├── strategy/__init__.py
├── ui/__init__.py
├── tools/
│   ├── __init__.py
│   └── calibrator.py
├── data/
│   ├── templates/cards/
│   ├── templates/digits/
│   ├── preflop_tables/
│   └── postflop_db/
├── logs/
└── tests/
    ├── __init__.py
    ├── test_contracts.py
    └── test_calibrator.py
```

Utwórz plik `requirements.txt` z następującą zawartością:

```text
opencv-python>=4.9.0
numpy>=1.26.0
pytest>=8.0.0
dxcam>=0.0.5; platform_system == "Windows"
PySide6>=6.6.0
phevaluator>=0.5.0
```

---

## Krok 2: Implementacja `core/constants.py`

Plik zawiera stałe domenowe zdefiniowane w `CONSTITUTION.md`. Zaimplementuj dokładnie poniższe wartości:

| Nazwa stałej | Typ i wartość | Opis |
| :--- | :--- | :--- |
| `TOTAL_CHIPS` | `int = 900` | Suma żetonów na stole (główny test spójności OCR). |
| `STARTING_STACK` | `int = 300` | Początkowy stack każdego z 3 graczy. |
| `BLIND_LEVELS` | `list[tuple[int, int]]` | `[(10, 20), (15, 30), (20, 40), (30, 60), (40, 80)]` |
| `CARD_MATCH_THRESHOLD` | `float = 0.92` | Minimalna pewność `cv2.matchTemplate` dla kart. |
| `EV_LOSS_THRESHOLD_BB` | `float = 0.08` | Próg odcięcia marginalnych zagrań. |
| `RANKS` | `str = "23456789TJQKA"` | Dozwolone figury kart. |
| `SUITS` | `str = "cdhs"` | Dozwolone kolory (`c`=trefl, `d`=karo, `h`=kier, `s`=pik). |
| `VALID_STREETS` | `tuple[str, ...]` | `("PREFLOP", "FLOP", "TURN", "RIVER", "WAITING_FOR_TURN")` |
| `VALID_ACTIONS` | `tuple[str, ...]` | `("FOLD", "CHECK", "CALL", "MIN_RAISE", "BET_30", "ALL_IN", "WAIT")` |
| `VALID_PROFILES` | `tuple[str, ...]` | `("LOOSE_CALLERS", "STANDARD_EXPLOIT", "HIGH_STEAL")` |

---

## Krok 3: Implementacja `core/contracts.py`

Zaimplementuj trzy klasy danych przy użyciu `@dataclass` z modułu `dataclasses`. Każda klasa musi mieć metodę `to_dict(self) -> dict` (można użyć `dataclasses.asdict`).

### 1. `PlayerState`
Pola (zachowaj dokładne nazwy i typy):
* `seat_id: int` (`0` = Hero, `1` = Lewy rywal, `2` = Prawy rywal)
* `stack: int | None` (`None`, jeśli `Sit out` lub brak odczytu)
* `current_bet: int = 0`
* `is_dealer: bool = False`
* `is_active: bool = True`
* `status_text: str = "ACTIVE"` (np. `"ACTIVE"`, `"SIT_OUT"`, `"ALL_IN"`)
* `last_reaction_ms: int | None = None`

### 2. `TableState`
Pola (zachowaj dokładne nazwy i typy):
* `table_id: str`
* `timestamp_ms: int`
* `prize_pool: int`
* `small_blind: int`
* `big_blind: int`
* `pot: int`
* `hero_cards: list[str]` (np. `["Qh", "4h"]`)
* `board_cards: list[str]` (0, 3, 4 lub 5 kart)
* `street: str` (wartość z `VALID_STREETS`)
* `is_hero_turn: bool`
* `available_actions: list[str]` (np. `["FOLD", "CHECK", "BET"]`)
* `players: dict[int, PlayerState]`
* `is_valid: bool = False`

### 3. `Decision`
Pola (zachowaj dokładne nazwy i typy):
* `table_id: str`
* `action: str` (wartość z `VALID_ACTIONS`)
* `ev_bb: float | None`
* `confidence: float`
* `profile_used: str` (wartość z `VALID_PROFILES`)
* `reason: str`

---

## Krok 4: Szablon Konfiguracji `config.json`

Wszystkie strefy na ekranie (ROI — Region of Interest) muszą być zapisane jako **współrzędne relatywne** `[x_rel, y_rel, w_rel, h_rel]` w zakresie od `0.0` do `1.0` względem wykrytego prostokąta stołu (`table_rect`). Dzięki temu zmiana rozmiaru okna przeglądarki nie zepsuje odczytu.

Utwórz plik `config.json` o poniższej strukturze (z domyślnymi wartościami `[0.0, 0.0, 0.0, 0.0]` do wypełnienia przez kalibrator):

```json
{
  "version": "1.0",
  "anchor": {
    "template_path": "data/templates/anchor.png",
    "match_threshold": 0.85,
    "table_offset_rel": [0.0, 0.0, 1.0, 1.0]
  },
  "rois": {
    "prize_pool": [0.0, 0.0, 0.0, 0.0],
    "pot": [0.0, 0.0, 0.0, 0.0],
    "blinds": [0.0, 0.0, 0.0, 0.0],
    "hero_actions": [0.0, 0.0, 0.0, 0.0],
    "hero_card_1": [0.0, 0.0, 0.0, 0.0],
    "hero_card_2": [0.0, 0.0, 0.0, 0.0],
    "board_card_1": [0.0, 0.0, 0.0, 0.0],
    "board_card_2": [0.0, 0.0, 0.0, 0.0],
    "board_card_3": [0.0, 0.0, 0.0, 0.0],
    "board_card_4": [0.0, 0.0, 0.0, 0.0],
    "board_card_5": [0.0, 0.0, 0.0, 0.0],
    "seat_0_stack": [0.0, 0.0, 0.0, 0.0],
    "seat_0_bet": [0.0, 0.0, 0.0, 0.0],
    "seat_0_dealer": [0.0, 0.0, 0.0, 0.0],
    "seat_1_stack": [0.0, 0.0, 0.0, 0.0],
    "seat_1_bet": [0.0, 0.0, 0.0, 0.0],
    "seat_1_dealer": [0.0, 0.0, 0.0, 0.0],
    "seat_2_stack": [0.0, 0.0, 0.0, 0.0],
    "seat_2_bet": [0.0, 0.0, 0.0, 0.0],
    "seat_2_dealer": [0.0, 0.0, 0.0, 0.0]
  },
  "hud": {
    "lock_shortcut": "Ctrl+Shift+L",
    "opacity": 0.9,
    "default_offset_px": [20, 20]
  },
  "tables": [
    {
      "table_id": "table_1",
      "enabled": true
    }
  ]
}
```

---

## Krok 5: Narzędzie Kalibracyjne `tools/calibrator.py`

Narzędzie musi działać w terminalu z podglądem w oknie `OpenCV` (`cv2`). Jego zadaniem jest umożliwienie użytkownikowi kliknięcia stref na zrzucie ekranu lub klatce z nagrania testowego (bez pisania kodu ręcznie).

### Wymagane funkcje czystej matematyki (do łatwego testowania w `pytest`)
Wydziel w `tools/calibrator.py` dwie funkcje pomocnicze:
1. `abs_to_rel(abs_rect: tuple[int, int, int, int], table_rect: tuple[int, int, int, int]) -> list[float]`
   * Przelicza piksele `(x, y, w, h)` na relatywne `[x_rel, y_rel, w_rel, h_rel]` zaokrąglone do 4 miejsc po przecinku:
     * `x_rel = (x - table_x) / table_w`
     * `y_rel = (y - table_y) / table_h`
     * `w_rel = w / table_w`
     * `h_rel = h / table_h`
   * Jeśli `table_w <= 0` lub `table_h <= 0`, rzuć `ValueError`.
2. `rel_to_abs(rel_rect: list[float], table_rect: tuple[int, int, int, int]) -> tuple[int, int, int, int]`
   * Odwrotna konwersja do pikseli (`round(...)`), zwracająca `(x, y, w, h)` jako `int`.

### Tryby pracy CLI (`argparse`)
Skrypt uruchamiany komendą `python -m tools.calibrator` musi obsługiwać następujące argumenty:
* `--source <ścieżka>`: ścieżka do pliku obrazu (`.png`, `.jpg`) lub pliku wideo (`.mp4`, `.mkv`, `.avi` — wtedy pobiera pierwszą lub wskazaną klatkę `--frame 0`).
* `--config <ścieżka>`: domyślnie `config.json`.
* `--mode <rois | templates | preview>`:
  1. **`rois` (domyślny):**
     * Najpierw wyświetla obraz i prosi o zaznaczenie myszą prostokąta całego stołu (`table_rect`) za pomocą `cv2.selectROI`. Zatwierdzenie `ENTER`/`SPACE`.
     * Następnie w pętli pyta w terminalu, który klucz z `rois` z `config.json` użytkownik chce skalibrować (albo pozwala przejść po kolei przez wszystkie, z możliwością wpisania `skip` lub `quit`).
     * Po każdym zaznaczeniu przelicza współrzędne przez `abs_to_rel` i zapisuje zaktualizowany `config.json`.
  2. **`templates`:**
     * Wyświetla obraz i pozwala zaznaczyć mały wycinek (np. róg karty lub cyfrę) za pomocą `cv2.selectROI`.
     * Pyta w terminalu o typ (`card` / `digit` / `anchor`) i nazwę (np. `Qh`, `4h`, `0`..`9`).
     * Zapisuje wycięty fragment jako `.png` odpowiednio w `data/templates/cards/<nazwa>.png`, `data/templates/digits/<nazwa>.png` lub `data/templates/anchor.png`.
  3. **`preview`:**
     * Wczytuje `config.json`, każe zaznaczyć (lub podać) `table_rect`, przelicza wszystkie niezerowe ROI przez `rel_to_abs`, rysuje zielone ramki z nazwą klucza na obrazie i wyświetla okno podglądu aż do naciśnięcia klawisza `q` lub `ESC`.

---

## Krok 6: Testy Jednostkowe (`tests/`) i Weryfikacja

Napisz proste, szybkie testy w `pytest`, które działają bez otwierania okien GUI i bez plików zewnętrznych użytkownika:

1. **`tests/test_contracts.py`:**
   * Sprawdza wartości stałych w `core/constants.py` (`TOTAL_CHIPS == 900`, `STARTING_STACK == 300`, `len(BLIND_LEVELS) == 5`).
   * Tworzy poprawne obiekty `PlayerState`, `TableState`, `Decision` i sprawdza wynik `to_dict()`.
2. **`tests/test_calibrator.py`:**
   * Testuje `abs_to_rel` oraz `rel_to_abs` na przykładowych rozdzielczościach (np. `1280x720` i `1920x1080`) — sprawdza dokładność konwersji w obie strony.
   * Testuje rzucanie `ValueError` przy zerowych wymiarach stołu.
   * Testuje odczyt i zapis `config.json` na pliku tymczasowym (`tmp_path`).

### Kryterium odbioru (Uruchom przed zgłoszeniem zakończenia)
Agent musi wykonać w terminalu:
```bash
pytest -v tests/
python -m tools.calibrator --help
```
Oba polecenia muszą zakończyć się kodem wyjścia `0` bez błędów importu ani ostrzeżeń składniowych.
