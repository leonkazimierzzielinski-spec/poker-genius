# Plan Budowy — Moduł 2: Przechwytywanie Ekranu i Moduł Wizyjny (`vision/`)

**Rola tego dokumentu:** Instrukcja krok po kroku dla osobnego agenta realizującego **Część 2** projektu `poker_assistant` równolegle z innymi agentami.

---

## 0. Zasady Pracy Równoległej (Przeczytaj przed startem!)

1. **Przeczytaj `CONSTITUTION.md`** w głównym katalogu projektu.
2. **Zasada braku konfliktów:** Ponieważ inni agenci mogą równolegle budować inne moduły, **TWORZYSZ I EDYTUJESZ WYŁĄCZNIE PONIŻSZE PLIKI**:
   * `vision/__init__.py`
   * `vision/capture.py`
   * `vision/anchor.py`
   * `vision/card_recognizer.py`
   * `vision/ocr.py`
   * `vision/pipeline.py`
   * `tools/offline_tester.py`
   * `tests/test_vision.py`
3. **Czego NIE dotykasz:** NIE twórz ani nie edytuj `core/contracts.py`, `core/constants.py`, `config.json`, `requirements.txt`, `tools/calibrator.py`, `state/`, `engine/`, `strategy/` ani `ui/`.
4. **Bezpieczny import `core` (gdy Moduł 1 jeszcze się buduje):** W `vision/pipeline.py` importuj `TableState` i `PlayerState` z `core.contracts`. Jeśli w trakcie Twojej pracy `core/contracts.py` jeszcze nie istnieje w katalogu, nie twórz go — w `tests/test_vision.py` przetestuj wszystkie komponenty `vision/` niezależnie (a test `pipeline` oznacz `pytest.importorskip("core.contracts")`).
5. **Wydajność:** Przetworzenie jednej klatki (kotwica + ROI + karty + OCR) musi zajmować znacznie poniżej **100 ms** na CPU.

---

## Krok 1: `vision/capture.py` (Live `dxcam` + Offline Replay)

Zaimplementuj wspólny interfejs źródła klatek oraz dwie klasy:

1. **`FrameSource` (klasa bazowa / ABC):**
   * `grab() -> np.ndarray | None` (zwraca obraz BGR w formacie `numpy.ndarray` lub `None`, gdy brak kolejnej klatki).
   * `release() -> None`
2. **`LiveScreenCapture(FrameSource)`:**
   * Przechwytywanie obrazu na Windows przez `dxcam` (`import dxcam` wewnątrz `try/except ImportError`, żeby moduł dało się zaimportować na każdym systemie podczas testów).
   * Parametry `__init__(self, region: tuple[int, int, int, int] | None = None, target_fps: int = 15)`.
   * Wspiera multi-tabling: może przyjąć `region=(left, top, right, bottom)` dla konkretnego stołu lub `None` dla całego ekranu.
   * Konwertuje wyjście `dxcam` (RGB) na BGR (`cv2.cvtColor(..., cv2.COLOR_RGB2BGR)`), żeby było spójne z OpenCV.
3. **`OfflineReplayCapture(FrameSource)`:**
   * Przyjmuje `source_path: str | Path` — obsługuje **zarówno**:
     * **folder** zawierający obrazy testowe (`.png`, `.jpg`, `.jpeg`) posortowane alfabetycznie,
     * **pojedynczy plik** obrazu lub wideo (`.mp4`, `.mkv`, `.avi` przez `cv2.VideoCapture`).
   * Parametr `loop: bool = False` — czy zapętlać po dojściu do końca.
   * `grab()` zwraca kolejną klatkę BGR lub `None` po zakończeniu zbioru (gdy `loop=False`).

---

## Krok 2: `vision/anchor.py` (Kotwica, Multi-Tabling i Skalowanie ROI)

Zaimplementuj funkcje do wykrywania stołu i wycinania stref na podstawie relatywnych współrzędnych z `config.json`:

1. **`find_all_anchors(frame: np.ndarray, anchor_template: np.ndarray, threshold: float = 0.85, min_distance_px: int = 100) -> list[tuple[int, int, int, int]]`**
   * Używa `cv2.matchTemplate(frame, anchor_template, cv2.TM_CCOEFF_NORMED)`.
   * Znajduje wszystkie dopasowania `>= threshold`, wykonuje prosty Non-Maximum Suppression (odrzuca wykrycia leżące bliżej niż `min_distance_px` od silniejszego dopasowania).
   * Zwraca posortowaną listę `(x, y, w, h)` dla każdego wykrytego stołu na ekranie (umożliwia obserwację wielu stołów jednocześnie).
2. **`find_anchor(frame: np.ndarray, anchor_template: np.ndarray, threshold: float = 0.85) -> tuple[int, int, int, int] | None`**
   * Zwraca najsilniejsze pojedyncze dopasowanie lub `None`.
3. **`compute_table_rect(anchor_rect: tuple[int, int, int, int], table_offset_rel: list[float], frame_shape: tuple[int, ...]) -> tuple[int, int, int, int]`**
   * Przelicza pozycję kotwicy na prostokąt całego stołu i przycina do wymiarów `frame_shape` (`(height, width, ...)`).
   * Jeśli `table_offset_rel == [0.0, 0.0, 1.0, 1.0]`, przyjmuje cały `anchor_rect` (lub całą klatkę, gdy kotwicą jest obrys okna).
4. **`crop_rois(frame: np.ndarray, table_rect: tuple[int, int, int, int], rois_rel: dict[str, list[float]]) -> dict[str, np.ndarray]`**
   * Dla każdego klucza w `rois_rel`, którego wartości nie są `[0.0, 0.0, 0.0, 0.0]`:
     * Przelicza `[x_rel, y_rel, w_rel, h_rel]` na piksele wewnątrz `table_rect`.
     * Bezpiecznie przycina współrzędne do granic `frame` (nigdy nie zwraca pustego wycinka o rozmiarze 0, w razie błędu pomija klucz).
   * Zwraca słownik `{nazwa_roi: wycinek_bgr}`.

---

## Krok 3: `vision/card_recognizer.py` (Dopasowanie 52 Kart)

Stół Stake używa talii **2-kolorowej** (karo i kier czerwone, pik i trefl czarne), dlatego kluczowe jest porównywanie zarówno kształtu figury/symbolu, jak i koloru.

Zaimplementuj klasę `CardRecognizer`:
* **`__init__(self, templates_dir: str | Path = "data/templates/cards", threshold: float = 0.92)`**
  * Wczytuje wszystkie pliki `*.png` z `templates_dir` do pamięci RAM jako `dict[str, np.ndarray]` (klucz to nazwa pliku bez rozszerzenia, np. `"Qh"`, `"4h"`, `"Qd"`).
  * Jeśli katalog jest pusty lub nie istnieje, nie rzuca wyjątku — zapisuje pusty słownik i działa bezpiecznie.
* **`recognize(self, card_roi: np.ndarray) -> tuple[str | None, float]`**
  * Jeśli `card_roi` jest puste lub brak szablonów, zwraca `(None, 0.0)`.
  * Dla każdego szablonu w pamięci:
    * Jeśli rozmiar `card_roi` różni się od rozmiaru szablonu (skutek skalowania okna), przeskaluj `card_roi` do wymiarów szablonu za pomocą `cv2.resize(..., interpolation=cv2.INTER_AREA)`.
    * Uruchom `cv2.matchTemplate(resized_roi, template, cv2.TM_CCOEFF_NORMED)` w pełnych 3 kanałach BGR i pobierz maksymalną wartość `score`.
  * Wybierz kartę z najwyższym `best_score`.
  * Jeśli `best_score >= self.threshold` (`0.92`), zwróć `(best_card, float(best_score))`. W przeciwnym razie zwróć `(None, float(best_score))`.

---

## Krok 4: `vision/ocr.py` (Odczyt Liczb i Detektor Tury Hero)

Zaimplementuj lekkie rozpoznawanie cyfr oparte na OpenCV (bez ciężkich modeli OCR) oraz detektor przycisków akcji:

1. **Klasa `DigitOCR`:**
   * **`__init__(self, templates_dir: str | Path = "data/templates/digits", threshold: float = 0.80)`**
     * Wczytuje szablony cyfr `0.png` – `9.png` w skali szarości. Jeśli brak szablonów, działa bezpiecznie i zwraca `None`.
   * **`preprocess(self, roi: np.ndarray) -> np.ndarray`**
     * Konwersja do skali szarości (`cv2.cvtColor`), powiększenie x2 (`cv2.resize`), progowanie binarne (`cv2.THRESH_BINARY + cv2.THRESH_OTSU`).
   * **`read_int(self, roi: np.ndarray) -> int | None`**
     * Znajduje kontury cyfr na obrazie binarnym (`cv2.findContours`), filtruje zbyt małe szumy, sortuje kontury od lewej do prawej (`x`).
     * Każdą wyodrębnioną cyfrę skaluje do rozmiaru szablonu i dopasowuje przez `cv2.matchTemplate`.
     * Jeśli wszystkie cyfry przejdą `threshold`, łączy je w `int` (np. `280`). Jeśli obraz nie zawiera cyfr (np. napis `"Sit out"` lub puste pole), zwraca `None` bez rzucania wyjątku.
   * **`read_blinds(self, roi: np.ndarray) -> tuple[int, int] | None`**
     * Wykrywa dwie grupy cyfr oddzielone ukośnikiem lub większym odstępem poziomym (np. `10/20` → `(10, 20)`). Zwraca `None`, jeśli nie uda się odczytać dwóch liczb.
2. **Funkcja `detect_hero_actions(actions_roi: np.ndarray) -> tuple[bool, list[str]]`**
   * Sprawdza, czy w wycinku `hero_actions` (prawy dolny róg stołu) widoczne są aktywne przyciski akcji Hero.
   * Prosta, szybka heurystyka oparta na kolorach HSV w wycinku (na stole Stake: przycisk `Fold` ma wyraźny odcień czerwony, `Check/Call` zielony, `Bet/Raise` pomarańczowo-złoty).
   * Jeśli wykryje co najmniej 2 przyciski akcji (np. `["FOLD", "CHECK", "BET"]` lub `["FOLD", "ALL_IN"]`), zwraca `(True, lista_wykrytych_akcji)`.
   * Gdy przyciski są niewidoczne (np. tura rywala lub All-in runout), zwraca `(False, [])`.

---

## Krok 5: `vision/pipeline.py` i `tools/offline_tester.py`

1. **`vision/pipeline.py`:**
   * Klasa `VisionPipeline(config_path: str | Path = "config.json")`:
     * Wczytuje `config.json`, inicjalizuje `CardRecognizer` i `DigitOCR`, ładuje szablon kotwicy (jeśli istnieje).
     * Metoda `process_frame(self, frame: np.ndarray, table_id: str = "table_1", timestamp_ms: int | None = None, table_rect: tuple[int, int, int, int] | None = None) -> TableState`:
       * Jeśli `table_rect is None`, szuka kotwicy przez `find_anchor` (a gdy brak szablonu kotwicy, używa całej klatki `(0, 0, w, h)` jako fallback do testów).
       * Wycina ROI przez `crop_rois`.
       * Odczytuje `hero_cards`, `board_cards`, `pot`, `prize_pool`, `blinds`, `players` (`seat_0`, `seat_1`, `seat_2`), oraz `is_hero_turn, available_actions`.
       * Wyznacza `street`: jeśli `not is_hero_turn` i brak kart albo trwa runout -> `"WAITING_FOR_TURN"` lub na podstawie liczby `board_cards` (`0` -> `"PREFLOP"`, `3` -> `"FLOP"`, `4` -> `"TURN"`, `5` -> `"RIVER"`).
       * Zwraca wypełniony obiekt `TableState` (z `is_valid=False`, bo pełną walidację robi Moduł 3).
2. **`tools/offline_tester.py`:**
   * Proste CLI (`python -m tools.offline_tester --source <folder_lub_plik> --config config.json`).
   * Przechodzi po klatkach z `OfflineReplayCapture`, mierzy czas `time.perf_counter()` na klatkę i wypisuje w konsoli podsumowanie: numer klatki, czas w `ms`, wykryte karty, pulę, stacki i czy to tura Hero.

---

## Krok 6: Testy Jednostkowe `tests/test_vision.py`

Napisz niezależne testy w `pytest`, które tworzą syntetyczne obrazy `numpy` w `tmp_path` (nie wymagają prawdziwych screenshotów ani kamery `dxcam`):

1. `test_offline_replay_capture_folder`: zapisuje 3 tymczasowe obrazy `.png` w `tmp_path`, odczytuje je po kolei przez `OfflineReplayCapture` i sprawdza, że 4. wywołanie `grab()` zwraca `None`.
2. `test_find_all_anchors_multi_table`: tworzy czarny obraz `1000x600`, wkleja w 2 różnych miejscach ten sam mały wzorzec kotwicy `40x20` i sprawdza, że `find_all_anchors` zwraca dokładnie 2 prostokąty.
3. `test_crop_rois_bounds`: sprawdza wycinanie ROI z `table_rect` oraz poprawne przycinanie przy krawędziach obrazu.
4. `test_card_recognizer_match_and_threshold`: zapisuje syntetyczny wzorzec `Qh.png` w `tmp_path`, sprawdza że `recognize` zwraca `("Qh", score >= 0.92)`, a dla losowego szumu zwraca `(None, score < 0.92)`.
5. `test_digit_ocr_empty_returns_none`: sprawdza, że pusty/szary obraz (symulacja `"Sit out"`) zwraca `None` bez błędu.

### Kryterium odbioru
Uruchom w terminalu:
```bash
pytest -v tests/test_vision.py
python -m tools.offline_tester --help
```
Oba polecenia muszą zakończyć się kodem wyjścia `0`.
