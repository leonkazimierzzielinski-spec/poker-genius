# Plan Budowy — Moduł 6: Nakładka HUD i Orkiestrator (`ui/hud.py` + `main.py`)

**Rola tego dokumentu:** Instrukcja krok po kroku dla osobnego agenta realizującego **Część 6** projektu `poker_assistant` równolegle z innymi agentami.

---

## 0. Zasady Pracy Równoległej (Przeczytaj przed startem!)

1. **Przeczytaj `CONSTITUTION.md`** w głównym katalogu projektu.
2. **Zasada braku konfliktów:** Ponieważ inni agenci równolegle budują pozostałe moduły, **TWORZYSZ I EDYTUJESZ WYŁĄCZNIE PONIŻSZE PLIKI**:
   * `ui/__init__.py`
   * `ui/hud.py`
   * `main.py`
   * `tests/test_ui_and_main.py`
3. **Czego NIE dotykasz:** NIE twórz ani nie edytuj `core/`, `config.json`, `requirements.txt`, `vision/`, `state/`, `engine/`, `strategy/` ani `tools/`.
4. **Bezpieczne importy:** `main.py` spina wszystkie moduły (`core`, `vision`, `state`, `engine`, `strategy`, `ui`). W `tests/test_ui_and_main.py` użyj `pytest.importorskip("PySide6")` dla testów widżetu Qt oraz testuj czyste funkcje pomocnicze z `main.py` niezależnie od tego, czy pozostałe moduły są już na dysku.

---

## Krok 1: `ui/hud.py` (Nakładka Click-Through + Przesuwanie)

Zbuduj lekką nakładkę ekranową w `PySide6`, która nie blokuje kliknięć na stole i pozwala się przesuwać po odblokowaniu:

1. **Obsługa Win32 Click-Through (tylko Windows):**
   * Funkcja `set_click_through(hwnd: int, enabled: bool) -> None`:
     * Jeśli `sys.platform != "win32"`, kończy działanie bez błędu.
     * Na Windows używa `ctypes.windll.user32` (`GetWindowLongW`, `SetWindowLongW` z `GWL_EXSTYLE = -20`, `WS_EX_LAYERED = 0x80000`, `WS_EX_TRANSPARENT = 0x20`), aby włączać lub wyłączać przepuszczanie kliknięć myszy.
2. **Sygnał wątkowy `HudBridge(QObject)`:**
   * `decision_updated = Signal(object, float)` (przekazuje obiekt `Decision` oraz `latency_ms`).
3. **Klasa `HudOverlay(QWidget)`:**
   * Flagi okna: `Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool`, tło `Qt.WA_TranslucentBackground`.
   * Przechowuje słownik kart/wierszy dla wielu stołów: `table_widgets: dict[str, QLabel]` (multi-tabling — każdy `table_id` dostaje własny czytelny wiersz w panelu).
   * **Wyświetlane informacje dla każdego stołu:**
     * Nazwa stołu i aktywny profil (`LOOSE_CALLERS` / `STANDARD_EXPLOIT` / `HIGH_STEAL`).
     * Duża rekomendacja akcji (`ALL_IN`, `BET_30`, `MIN_RAISE`, `CALL`, `CHECK`, `FOLD`, `WAIT`) z wyraźnym kolorem tła (np. zielony dla agresji/value, żółty dla `CALL`/`CHECK`, czerwony dla `FOLD`, szary dla `WAIT`).
     * Wartość `EV` (np. `+0.42 BB`), krótki `reason` oraz czas obliczeń `latency_ms`.
   * **Tryb przesuwania (`is_locked: bool = True`):**
     * Domyślnie `is_locked = True` (okno jest click-through).
     * Metoda `toggle_lock() -> bool`: zmienia `is_locked`. Gdy `False`, wyłącza `WS_EX_TRANSPARENT`, pokazuje wyraźne obramowanie i napis `[ODBLOKOWANY - przeciągnij myszą]`. Gdy `True`, włącza `WS_EX_TRANSPARENT` i chowa ramkę.
     * Obsługa `QShortcut(QKeySequence("Ctrl+Shift+L"), self)` podpięta do `toggle_lock`.
     * Obsługa `mousePressEvent` i `mouseMoveEvent` do płynnego przesuwania okna, gdy `not self.is_locked`.
   * Slot `on_decision_updated(self, decision: Decision, latency_ms: float)` aktualizujący wiersz dla `decision.table_id`.

---

## Krok 2: `main.py` (Dwuwątkowy Orkiestrator Czasu Rzeczywistego)

Połącz wszystkie warstwy systemu w architekturze dwuwątkowej z budżetem czasu `< 0.3 s`:

1. **Argumenty CLI (`argparse`):**
   * `--mode <live | offline>` (domyślnie `"live"`)
   * `--source <ścieżka>` (wymagane dla `--mode offline` — folder z nagraniami testowymi lub plik wideo/obraz)
   * `--config <ścieżka>` (domyślnie `"config.json"`)
   * `--buy-in <int>` (domyślnie `2`)
   * `--headless` (flaga uruchamiająca pętlę bez okna Qt — przydatna do szybkich testów integracyjnych w terminalu)
2. **Funkcja pomocnicza `determine_preflop_spot(state: TableState) -> str`:**
   * Na podstawie pozycji `is_dealer` oraz `current_bet` graczy wyznacza nazwę spota dla `PreflopNashEngine` (np. `"BTN_OPEN"`, `"SB_OPEN"`, `"BB_ISO_VS_LIMP"`, `"BB_VS_BTN_SHOVE"`).
3. **Funkcja pomocnicza `evaluate_candidates(state, preflop_engine, flop_db, mc_calc) -> tuple[dict[str, float], str]`:**
   * Jeśli `state.street == "PREFLOP"`: wyznacza `spot`, odpytuje `preflop_engine.get_action(...)` i buduje słownik `candidate_evs` (np. `{"FOLD": 0.0, action: ev_bb}`).
   * Jeśli `state.street in ("FLOP", "TURN", "RIVER")`: najpierw sprawdza `flop_db.lookup(...)`; jeśli zwróci `None`, wylicza equity przez `mc_calc.estimate_equity(...)` (`time_budget_ms=80.0`) i buduje `candidate_evs` dla `CHECK`, `BET_30`, `ALL_IN`.
4. **Wątek 1 (`capture_loop`):**
   * Co `50–100 ms` pobiera klatkę z `LiveScreenCapture` lub `OfflineReplayCapture`.
   * Umieszcza klatkę w `queue.Queue(maxsize=1)`. Jeśli kolejka jest pełna, wyrzuca starą klatkę (`get_nowait()`), żeby zawsze przetwarzać najświeższy obraz bez opóźnień.
5. **Wątek 2 (`processing_loop`):**
   * Pobiera klatkę z kolejki, wykrywa stoły przez `find_all_anchors` (lub przetwarza pojedynczy stół w trybie fallback).
   * Dla każdego stołu wykonuje łańcuch: `VisionPipeline` → `StateValidator` → `TableTracker` → `evaluate_candidates` → `DecisionMaker`.
   * Zapisuje wynik w `SessionLogger` i wysyła `Decision` + `latency_ms` do `HudBridge.decision_updated.emit(...)`.
6. **Wątek główny:**
   * Jeśli `--headless`: uruchamia `processing_loop` do zakończenia źródła offline (lub `Ctrl+C`).
   * W trybie normalnym: tworzy `QApplication`, `HudOverlay`, uruchamia oba wątki jako `daemon=True` i wywołuje `app.exec()`.

---

## Krok 3: Testy Jednostkowe `tests/test_ui_and_main.py`

Napisz testy w `pytest`:
1. `test_determine_preflop_spot`: sprawdza na prostych obiektach testowych poprawne rozpoznanie `"BTN_OPEN"`, `"SB_OPEN"` i `"BB_ISO_VS_LIMP"`.
2. `test_hud_overlay_lock_toggle`: (z `pytest.importorskip("PySide6")` i `QT_QPA_PLATFORM=offscreen`) tworzy `HudOverlay`, sprawdza że domyślnie `is_locked is True`, wywołuje `toggle_lock()` i sprawdza `is_locked is False`.
3. `test_hud_overlay_updates_multi_table`: wysyła dwie decyzje dla `"table_1"` i `"table_2"` i sprawdza, że oba klucze pojawiły się w `hud.table_widgets`.

### Kryterium odbioru
Uruchom w terminalu:
```bash
pytest -v tests/test_ui_and_main.py
python main.py --help
```
Oba polecenia muszą zakończyć się kodem wyjścia `0`.
