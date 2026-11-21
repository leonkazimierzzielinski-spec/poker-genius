# Plan Niezawodnej Geometrii Stołu V10 — Koniec Przesunięcia na Żywo (Dwupunktowe Kotwiczenie + Ręczne Dostrajanie) (`poker_assistant`)

Dokument rozwiązuje źródłową przyczynę przesunięcia wszystkich ramek ROI o ~400 px w prawo w trybie `--mode live` (ujawnioną na zdjęciu z włączoną nakładką `🎯 Ramki ROI`: `TABLE (426, 335, 2027x1150)`), zapewniając **1-pikselową precyzję automatyczną na każdym monitorze i układzie okna (z otwartym lub zamkniętym panelem `Bet Slip`)** oraz dodając **ręczne przesuwanie i skalowanie ramki stołu** w HUD.

---

## 1. Diagnoza Źródłowej Przyczyny (100% Pewności ze Zdjęcia)

Na przesłanym zrzucie z trybu live:
1. Skala (`1.15x`, `2027x1150`) oraz wysokość pionowa (`ty = 335`, góra dokładnie przy ikonkach, dół na krawędzi stołu) są **idealne co do piksela**.
2. Natomiast `tx` zostało błędnie ustawione na **`426 px`** zamiast ok. **`30 px`**.
3. **Bezpośredni winowajca — `vision/anchor.py`, linie 210–215:**
   ```python
   # Center table horizontally if single window has wide margins
   if frame_shape is not None and len(frame_shape) >= 2:
       frame_w = frame_shape[1]
       tx_centered = (frame_w - tw) // 2
       if abs(tx_centered - tx) > 50 and ax < int(tw * 0.15):
           tx = tx_centered
   ```
   Ten kod zakładał, że cały ekran (`frame_w`, np. `2880 px` na laptopie HiDPI) to samo okno gry, więc wyliczał środek całego monitora `(2880 - 2027) // 2 = 426 px` i na siłę przerzucał `tx` w prawo, ignorując to, że po prawej stronie przeglądarki jest otwarty panel `Bet Slip`!
4. Co gorsza, przycisk **`📐 Obszar`** również wywoływał `compute_unclipped_table_rect(..., frame_shape=frame.shape)`, więc ta sama linijka psuła nawet ręcznie zaznaczony obszar.

---

## 2. Docelowa Architektura Niezawodnego Wykrywania Pozycji Stołu

### Filar 1: Wykrycie prawdziwej szerokości kontenera gry przez **prawą kotwicę `anchor_right.png`** (ikony `[⚙][🏆][⊞]` w prawym górnym rogu stołu)
Na każdym oknie Stake (niezależnie od monitora, rozdzielczości, zoomu i obecności panelu `Bet Slip` po prawej):
- W **lewym górnym rogu obszaru gry** stoją ikony `[☰] [🏠]` (`data/templates/anchor.png`),
- W **prawym górnym rogu obszaru gry** (dokładnie na tym samym `y` co `anchor.png`, tuż przed panelem `Bet Slip`!) stoją ikony `[⚙] [🏆]` (lub `[⚙] [🏆] [⊞]`).
- Gdy znamy oba punkty `(ax_left, ay)` i `(ax_right, ay)` na tej samej poziomej linii:
  - **Prawdziwy środek poziomy stołu** to dokładnie:
    `center_x = (ax_left + (ax_right + aw_right)) / 2` (z uwzględnieniem drobnego stałego przesunięcia zmierzonego na nagraniach bazowych `224127` i `211257`),
  - A stąd **`tx = int(round(center_x - tw / 2))`**!
- **Dlaczego to jest matematycznie niezawodne?**
  - Z otwartym `Bet Slip` po prawej → `anchor_right` stoi przed `Bet Slip`, więc `center_x` wypada **idealnie na środku stołu**!
  - Z zamkniętym `Bet Slip` lub szerokim oknem (jak w nagraniu `211257.mp4`!) → `anchor_right` stoi przy prawej krawędzi okna, więc `center_x` również wypada **idealnie na środku stołu**!
  - Gdy okno przeglądarki jest przesunięte w dowolne miejsce na ekranie (albo na 2. monitorze) → `tx` podąża za stołem co do 1 piksela!
  - **Fallback (gdy `anchor_right` nie zostanie znalezione, np. ucięta prawa krawędź):** używaj czystego `tx = int(round(ax - ox * tw))` z samej lewej kotwicy — **NIGDY** nie centruj do `frame_w` całego monitora!

### Filar 2: Naprawa przycisku `📐 Obszar` (bez nadpisywania!)
- Jeśli użytkownik zaznaczy obszar myszą przez **`📐 Obszar`**:
  - Szukaj kotwicy wewnątrz zaznaczonego prostokąta **bez centrowania do `frame_w`** (używając dwupunktowego kotwiczenia `anchor_left` + `anchor_right` wyłącznie wewnątrz `sub_frame`!).
  - Dodatkowo dodaj w HUD przycisk/tryb **`📐 Czysty Obszar`** (lub jeśli użytkownik ręcznie przesuwa ramkę, nie nadpisuj jej).

### Filar 3: Ręczne przesuwanie i dostrajanie ramki stołu w HUD (`ui/hud.py` + `main.py`)
Użytkownik poprosił o możliwość ręcznego przesuwania ramki na żywo:
- Po rozwinięciu **`🔍 Szczegóły`** dodaj kompaktowy pasek kalibracji na żywo (widoczny razem z `🎯 Ramki ROI`):
  - Przyciski przesunięcia o `5 px` (lub `15 px` z `Shift`): **`◀`**, **`▲`**, **`▼`**, **`▶`** (`offset_x`, `offset_y`),
  - Przyciski korekty skali o `±1%`: **`-`**, **`+`** (`scale_mult`),
  - Przycisk **`↺ Reset`** (zeruje `offset_x=0, offset_y=0, scale_mult=1.0`, podpięty też pod `↺ Auto`),
  - Opcjonalnie: tryb **przeciągania ramki myszą** (przycisk **`✋ Przesuń ramkę`** wyłączający na chwilę `click-through` na `DebugRoiOverlay`, żeby można było chwycić cyjanowy prostokąt `TABLE` myszą i przesunąć go dokładnie na stół, a po puszczeniu myszy automatycznie przywracający `click-through`!).
- Korekty `(offset_x, offset_y, scale_mult)` są przekazywane przez nowy sygnał `HudBridge.table_adjust_changed = Signal(int, int, float)` do `main.py` i nakładane na wyliczony `table_rect` przed `pipeline.process_frame` oraz przed wysłaniem `debug_overlay_updated`, dzięki czemu **użytkownik od razu widzi przesuwające się ramki na żywo na ekranie**.

---

## 3. Szczegółowe Kroki Implementacji dla Agenta

### Krok 1: Wycięcie `data/templates/anchor_right.png` i naprawa `vision/anchor.py`
1. Z nagrań w `nagrania testowe/` (`224127.mp4` klatka `0`, skala `1.0x`) wytnij czysty szablon **`data/templates/anchor_right.png`** zawierający parę ikon `[⚙] [🏆]` (lub `[⚙] [🏆] [⊞]`) z prawego górnego rogu stołu (dokładnie na wysokości `y` odpowiadającej `anchor.png`).
2. Zmierz na `224127.mp4` (skala `1.0x`), `2 gry na raz` (skala `1.0x`) oraz `211257.mp4` (skala `1.28x`) dokładną relację `center_x = (ax_left + ax_right + aw_right) / 2` względem idealnego środka stołu `tx_ideal + tw / 2` — zapisz ewentualną stałą korektę (zwykle ~`0 px`) jako parametr w `config.json` (`anchor.right_template_path: "data/templates/anchor_right.png"`).
3. **W `vision/anchor.py`:**
   - **USUŃ** wadliwe centrowanie do całego monitora (linie 210–215: `tx_centered = (frame_w - tw) // 2`!).
   - Dodaj funkcję `find_right_anchor(frame, right_template, left_anchor, threshold=0.72)`:
     * Przeszukuje **wyłącznie wąski poziomy pas** na prawo od `left_anchor` (`y` w zakresie `[ay - 25, ay + ah + 25]`, `x` w zakresie `[ax + int(tw * 0.50), min(frame_w, ax + int(tw * 1.20))]`) ze skalą `scale = aw / left_tpl_w` — trwa to **< 1 ms** i jest w 100% odporne na fałszywe trafienia!
     * Zwraca `(rx, ry, rw, rh)` w współrzędnych pełnej klatki lub `None`.
   - W `compute_unclipped_table_rect(..., right_anchor: tuple[int, int, int, int] | None = None)`:
     * Jeśli `right_anchor is not None`:
       - Wylicz środek poziomy obszaru gry: `game_center_x = (ax + (rx + rw)) / 2.0` (plus zmierzona na `224127` mikro-korekta `right_center_offset_rel * tw`, jeśli różna od zera).
       - Ustaw `tx = int(round(game_center_x - tw / 2.0))`.
     * Jeśli `right_anchor is None`:
       - Użyj czystego `tx = int(round(ax - ox * tw))` (bez żadnego centrowania do `frame_w`!).

### Krok 2: Integracja `anchor_right` w `vision/pipeline.py` i `main.py`
1. W `VisionPipeline.__init__`: wczytaj `self.right_anchor_template` z `data/templates/anchor_right.png` (jeśli plik istnieje).
2. W `main.py` (`processing_loop`, zarówno dla trybu `Auto`, jak i `manual_rect`) oraz w `VisionPipeline.process_frame` (gdy `table_rect is None`):
   - Po wykryciu `anchor` wywołaj `find_right_anchor(frame, pipeline.right_anchor_template, anchor, ...)` (dla `manual_rect` ograniczając szukanie do `mx + mw`).
   - Przekaż `right_anchor` do `compute_unclipped_table_rect(...)`.

### Krok 3: Ręczne przesuwanie i skalowanie ramki w HUD (`ui/hud.py` + `main.py`)
1. W `ui/hud.py`:
   - Dodaj sygnał `HudBridge.table_adjust_changed = Signal(int, int, float)` (`dx`, `dy`, `scale_mult`).
   - W `HudOverlay` (widoczne w panelu po rozwinięciu `🔍 Szczegóły`):
     * Dodaj zgrabny wiersz przycisków: `◀` `▲` `▼` `▶` (krok `10 px`, z `Shift` `2 px`), `-` `+` (skala `±0.01`), `✋ Przesuń` (tryb drag na `DebugRoiOverlay`) oraz etykietę np. `Offset: (0, 0) | 100%`.
     * Kliknięcie `↺ Auto` resetuje także `(dx=0, dy=0, scale_mult=1.0)` i emituje `table_adjust_changed.emit(0, 0, 1.0)`.
   - W `DebugRoiOverlay`:
     * Dodaj tryb `set_drag_mode(enabled: bool)`: gdy `True`, tymczasowo wyłącza `set_click_through(hwnd, False)`, zmienia kursor na `SizeAllCursor` i pozwala przeciągnąć myszą cały prostokąt `TABLE` po ekranie, emitując w czasie rzeczywistym zaktualizowane `(dx, dy)` do `HudOverlay` / `HudBridge`; po puszczeniu myszy (lub ponownym kliknięciu `✋ Przesuń`) natychmiast wraca do `click-through`.
2. W `main.py` (`processing_loop`):
   - Podłącz `hud_bridge.table_adjust_changed` do współdzielonego stanu `adjust_holder = [0, 0, 1.0]`.
   - Przed `pipeline.process_frame` i przed wysłaniem `debug_payload` zaaplikuj korektę na `table_rect = (tx, ty, tw, th)`:
     - Nowy rozmiar: `new_tw = int(round(tw * scale_mult))`, `new_th = int(round(th * scale_mult))`,
     - Nowa pozycja (skalowana względem środka + przesunięcie):
       `new_tx = tx + dx - (new_tw - tw) // 2`
       `new_ty = ty + dy - (new_th - th) // 2`.

---

## 4. Obowiązkowa Weryfikacja i Testy

1. **Test kluczowy — symulacja ekranu z `Bet Slip` po prawej (`tests/test_vision.py`):**
   - `test_compute_unclipped_table_rect_wide_monitor_with_right_panel`:
     * Umieść syntetyczny stół po **lewej stronie szerokiego ekranu `2880x1800`** (symulując otwarty panel `Bet Slip` po prawej, dokładnie jak na laptopie użytkownika!) z `left_anchor` i `right_anchor`.
     * Zweryfikuj, że `compute_unclipped_table_rect` zwraca `tx` na lewej połowie ekranu (NIE `426 px` na środku monitora!), z dokładnością `<= 2 px`!
   - `test_table_adjust_signal_and_drag_mode` w `tests/test_ui_and_main.py`: weryfikuje sygnał `table_adjust_changed`, przyciski przesuwania/skalowania i reset w `HudOverlay`.

2. **Weryfikacja na WSZYSTKICH 5 nagraniach (w tym szerokim `211257` i zwykłych `224127`, `2 gry na raz`):**
   - `2026-11-19 211257.mp4` (`1858x1248`, skala `1.28x`): potwierdzić, że dzięki `anchor_right` (bez starego `tx_centered`!) klatki **`1827`**, **`2604`** (`Kh 2s | 7d Td Th 2h`), **`3643`** (`Jc 4d`), **`3880`**, **`4757`** (`7s 7d | Qc 7c 7h | Pot 682`) nadal przechodzą w **100% VALID**!
   - `2026-11-18 224127.mp4` (`0`, `765`, `2370`, `4950`), `2 gry na raz` (`1383`, `1627`, `2418`, `2605`) — **100% PASS** bez żadnych regresji!
   - Przetestować dodatkowo sztucznie doklejony czarny pasek `800 px` z prawej strony klatki `211257` f2604 (symulacja `Bet Slip` na monitorze `2658x1248`!) i potwierdzić, że system nadal w 100% odczytuje `Hero: ['Kh', '2s']`, `Board: ['7d', 'Td', 'Th', '2h']` i `Pot: 218`!

3. **Uruchomić `pytest -v tests/`** — 100% testów musi przejść.

---

## 5. Obowiązkowa Synchronizacja na GitHub (Po Zakończeniu Prac)

1. Dopisz sekcję `## V10 — Dwupunktowe kotwiczenie stołu (anchor_right), usunięcie błędu centrowania i ręczne dostrajanie ramki w HUD (DATA)` na samej górze pliku **`PROGRESS_LOG.md`** z opisem przyczyny błędu ze zdjęcia, zmianami, wynikami testu z doklejonym panelem `Bet Slip` oraz wynikiem `pytest`.
2. Sprawdź `git status` (brak plików `.mp4` i śmieci tymczasowych).
3. Wykonaj:
   - `git add -A`
   - `git commit -m "V10: dual-anchor table alignment (fix wide-monitor/BetSlip shift) + manual HUD offset/scale/drag"`
   - `git push origin main`
4. Na koniec napisz **krótkie potwierdzenie**, że zmiany zostały wypchnięte na GitHub, i podaj sam link do repozytorium:
   `https://github.com/leonkazimierzzielinski-spec/poker-genius`
