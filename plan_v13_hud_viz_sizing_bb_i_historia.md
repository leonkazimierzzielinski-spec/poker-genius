# Plan V13 — Mikro-Kalibracja ROI, Minimalistyczny HUD z Wizualnymi Kartami i Tabelą Zagrań, Sizing Wielokrotnościami BB oraz Zapis Przebiegu Gry (`poker_assistant`)

Dokument jest kompletną, jednoznaczną specyfikacją wdrożeniową dla agenta realizującego V13. Wszystkie kluczowe decyzje architektoniczne zostały już podjęte poniżej — nie trzeba ich zgadywać.

> **Zasada "Zero działania na ślepo" (`QUESTIONS_V13.md`)**: Jeśli w trakcie wdrożenia trafisz na niejednoznaczność, konflikt z istniejącym kodem albo decyzję produktową, której nie rozstrzyga ten plan — **NIE zgaduj**. Zrealizuj wszystkie pewne części, a otwarte pytania (w formacie: kontekst + konkretne opcje A/B) zapisz w pliku **`QUESTIONS_V13.md`** w katalogu głównym repozytorium i wypchnij go razem z commitem.

---

## 0. Kluczowe Decyzje Architektoniczne (Już Podjęte)

| Obszar | Podjęta decyzja (obowiązująca) | Powód / Ochrona przed regresją |
|---|---|---|
| **Kontrakt `Decision`** | **NIE zmieniaj** kanonicznych nazw `Decision.action` (`"BET_30"`, `"MIN_RAISE"`, `"ALL_IN"`, `"CALL"`, `"CHECK"`, `"FOLD"`, `"WAIT"`). Dodaj w `core/contracts.py` dwa opcjonalne pola z domyślnym `None`: `sizing_chips: int \| None = None` oraz `sizing_bb: int \| None = None`. | Zachowuje 100% kompatybilności z `strategy/simplifier.py`, `strategy/decision_maker.py` i wszystkimi istniejącymi testami. |
| **Kwantyzacja sizingu** | Wspólna funkcja `quantize_sizing_to_bb(...)` w `strategy/simplifier.py`. Próg konwersji w `ALL_IN`: `>= 65%` efektywnego stacka lub `effective_stack <= 3 * big_blind` przy agresji. | Jedno źródło prawdy dla `main.py` (`evaluate_candidates` + `action_bar_payload`) i `ui/hud.py`. |
| **Render kart w Qt (`QLabel`)** | **NIE używaj** `display: inline-block` / `border-radius` na `<span>` (Qt RichText słabo to wspiera). Renderuj każdą kartę jako komórkę `<td>` w małej tabeli HTML z `background-color: #f8fafc; border: 1px solid #94a3b8; padding: 2px 6px;`. | Gwarantuje ostre, białe kafelki kart na Windows HiDPI (`2880x1800`, 150%). |
| **Ukrycie panelu kalibracji** | Usuń z `ui/hud.py:toggle_details()` (obecnie linia ~1313) linijkę `self.adjust_panel.setVisible(self.show_details)`. Kliknięcie `Szczegóły` pokazuje tylko mały przycisk `⚙` przy stole; dopiero `⚙` otwiera `self.calibration_panel`. | Bezpośrednia naprawa błędu z V12, w którym `Szczegóły` zawsze rozwijały kalibrację. |
| **Test `BLIND_LEVELS`** | W `tests/test_contracts.py` (linie ~22–24) zaktualizuj asercje z `len == 5` / `(40, 80)` na `len == 7` / `(60, 120)`. | Zapobiega fałszywemu błędowi w istniejącym teście po dodaniu `(50, 100)` i `(60, 120)`. |
| **Zapis historii rozdań** | Nowy moduł `state/hand_history.py` (`HandHistoryRecorder`). Katalog `hand_histories/` dodany do `.gitignore`. Zapis tylko po zakończeniu rozdania (`NEW_HAND`) + `close()` w `finally:` w `main.py` — zero blokowania pętli `< 300 ms`. | Czyste, kompletne logi `.jsonl` + `.md` bez duplikatów klatek i bez obciążania FPS. |

---

## 1. Krok 1: Mikro-kalibracja ROI i poziomy blindów (`config.json`, `core/constants.py`, `tests/test_contracts.py`)

Na podstawie zdjęć makro z trybu live (`IMG_2561`, `IMG_2562`, `IMG_2563`):

1. **`config.json` — zaktualizuj wyłącznie te 4 ramki (dodanie marginesu bezpieczeństwa):**
   - `seat_2_bet`: zmień z `[0.675, 0.405, 0.04, 0.038]` na **`[0.666, 0.405, 0.049, 0.038]`** (cyfra `5` w `565` dotykała lewej krawędzi).
   - `seat_1_dealer`: zmień `y` i `h` na **`[0.368, 0.270, 0.032, 0.042]`** (dolna krawędź żetonu `(D)` była ucinana).
   - `seat_2_dealer`: zmień `y` i `h` na **`[0.602, 0.270, 0.032, 0.042]`**.
   - `blinds`: zmień z `[0.55, 0.57, 0.065, 0.0351]` na **`[0.546, 0.57, 0.072, 0.036]`** (cyfra `5` w `50/100` stykała się z lewą krawędzią; zweryfikuj na nagraniach, by nie zahaczyć o myślnik `-` z napisu `Blinds - 50/100`).
   - Dodatkowo skontroluj na klatkach z 3-cyfrowym betem (`100`, `565`), czy `seat_1_bet` i `seat_0_bet` nie obcinają cyfr (jeśli tak, poszerz je o `0.004` w lewo).

2. **`core/constants.py`:**
   - Dopisz `(50, 100)` oraz `(60, 120)` na koniec `BLIND_LEVELS`:
     ```python
     BLIND_LEVELS: list[tuple[int, int]] = [
         (10, 20),
         (15, 30),
         (20, 40),
         (30, 60),
         (40, 80),
         (50, 100),
         (60, 120),
     ]
     ```
3. **`tests/test_contracts.py` (linie 22–24):**
   - Zaktualizuj `assert len(BLIND_LEVELS) == 7` oraz `assert BLIND_LEVELS[-1] == (60, 120)`.

---

## 2. Krok 2: Sizing wyłącznie w wielokrotnościach `BB` lub `ALL_IN` (`core/contracts.py`, `strategy/simplifier.py`, `main.py`, `ui/hud.py`)

1. **`core/contracts.py`:**
   - Rozszerz dataclass `Decision` (na końcu, z wartościami domyślnymi, żeby nie złamać żadnego istniejącego wywołania):
     ```python
     @dataclass
     class Decision:
         table_id: str
         action: str
         ev_bb: float | None
         confidence: float
         profile_used: str
         reason: str
         sizing_chips: int | None = None
         sizing_bb: int | None = None
     ```

2. **`strategy/simplifier.py` — dodaj funkcję `quantize_sizing_to_bb`:**
   ```python
   def quantize_sizing_to_bb(
       target_chips: float,
       big_blind: int,
       hero_stack: int,
       effective_stack: int,
       min_bb_mult: int = 1,
       all_in_threshold_ratio: float = 0.65,
   ) -> tuple[str, int | None, int]:
       """Zwraca (mode, bb_mult, chips), gdzie mode to 'ALL_IN' albo 'BB_MULT'."""
       bb = max(1, int(big_blind))
       hero_stk = max(0, int(hero_stack))
       eff_stk = max(0, int(effective_stack))
       if hero_stk == 0:
           return ("ALL_IN", None, 0)

       bb_mult = max(min_bb_mult, int(round(target_chips / bb)))
       chips = bb_mult * bb

       # Reguła przejścia w ALL_IN: >= 65% efektywnego stacka, >= stacka Hero lub <= 3 BB przy agresji
       if (
           chips >= hero_stk
           or (eff_stk > 0 and chips >= int(round(all_in_threshold_ratio * eff_stk)))
           or (eff_stk > 0 and eff_stk <= 3 * bb and bb_mult >= 2)
       ):
           return ("ALL_IN", None, hero_stk)

       return ("BB_MULT", bb_mult, chips)
   ```

3. **`main.py` — spójne liczenie EV i przypisanie `sizing_bb` / `sizing_chips`:**
   - **W `evaluate_candidates()` (postflop, okolice linii 455–492):**
     - Zamiast liczyć EV dla ułamkowego `bet30_bb = 0.30 * pot_bb`, najpierw oblicz `target_chips = 0.30 * pot` i przepuść przez `quantize_sizing_to_bb(target_chips, big_blind, hero_stack, effective_stack, min_bb_mult=1)`:
       - Jeśli `mode == "BB_MULT"`: użyj dokładnego `bet_bb = float(bb_mult)` przy wyliczaniu `bet_ev` (matematyczna spójność z realnym rozmiarem betu!).
       - Jeśli `mode == "ALL_IN"`: nie dawaj osobnego `BET_30` (albo usuń `BET_30` z `candidate_evs`, zostawiając `CHECK`, `ALL_IN`, `FOLD`), bo bet >= 65% stacka to zawsze `ALL_IN`.
   - **Po wywołaniu `decision_maker.decide(...)` w `main.py` (zanim wyślesz `decision` do HUD i `action_bar_payload`):**
     - Dla `decision.action == "MIN_RAISE"`:
       - Wylicz `min_legal_chips = max(2 * bb, max_opp_bet * 2)`.
       - `min_mult = max(2, int((min_legal_chips + bb - 1) // bb))` (zaokrąglenie w górę do pełnego BB, żeby zawsze spełnić legalny min-raise!).
       - Wywołaj `mode, bb_mult, chips = quantize_sizing_to_bb(min_mult * bb, bb, hero_stack, effective_stack, min_bb_mult=min_mult)`.
       - Jeśli `mode == "ALL_IN"`: ustaw `decision.action = "ALL_IN"`, `decision.sizing_bb = None`, `decision.sizing_chips = chips`.
       - W przeciwnym razie: `decision.sizing_bb = bb_mult`, `decision.sizing_chips = chips`.
     - Dla `decision.action == "BET_30"`:
       - Wywołaj `mode, bb_mult, chips = quantize_sizing_to_bb(0.30 * pot, bb, hero_stack, effective_stack, min_bb_mult=1)`.
       - Jeśli `mode == "ALL_IN"`: ustaw `decision.action = "ALL_IN"`, `decision.sizing_bb = None`, `decision.sizing_chips = chips`.
       - W przeciwnym razie: `decision.sizing_bb = bb_mult`, `decision.sizing_chips = chips`.
     - Dla `decision.action == "ALL_IN"`: `decision.sizing_bb = None`, `decision.sizing_chips = hero_stack`.
     - Dla `decision.action == "CALL"`: `decision.sizing_bb = None`, `decision.sizing_chips = max(0, max_opp_bet - hero_bet)`.
   - **W `action_bar_payload` (okolice linii 1244–1286):**
     - Zamiast osobnego ponownego przeliczania `0.30 * pot_val_chips`, użyj bezpośrednio `decision.sizing_chips` oraz dopisz `"sizing_bb": decision.sizing_bb` do słownika `action_bar_payload`.

4. **Wspólne etykiety akcji w `ui/hud.py`:**
   - Dodaj funkcję `format_action_label(action: str, sizing_bb: int | None = None, sizing_chips: int | None = None) -> str`:
     - `BET_30`: `f"BET {sizing_bb} BB ({sizing_chips})"` (gdy oba są obecne) / `f"BET {sizing_bb} BB"` / fallback `"BET 30%"`
     - `MIN_RAISE`: `f"RAISE {sizing_bb} BB ({sizing_chips})"` / `f"RAISE {sizing_bb} BB"` / fallback `"RAISE 2 BB"`
     - `ALL_IN`: `f"ALL-IN ({sizing_chips})"` (gdy `sizing_chips` > 0) / `"ALL-IN"`
     - `CALL`: `f"CALL ({sizing_chips})"` (gdy `sizing_chips` > 0) / `"CALL"`
     - `CHECK`, `FOLD`, `WAIT`: bez zmian.
   - Użyj `format_action_label(...)` w `on_decision_updated` (główna odznaka w HUD) oraz w `ActionBarOverlay`.

---

## 3. Krok 3: Śledzenie Zagrań w Rozdaniu (`state/tracker.py`) + Zapis Historii (`state/hand_history.py`)

### 3.1. Rozszerzenie `TableTracker` (`state/tracker.py`)

Dodaj śledzenie bieżącego rozdania bez psucia istniejącego API `update(state) -> tuple[TableState, list[GameEvent]]`:

1. **Stan bieżącego rozdania (`self.current_hand: dict`):**
   - Inicjalizowany przy pierwszym `VALID` stanie oraz resetowany przy każdym `NEW_HAND` (poprzednie rozdanie zapisuj w `self.last_completed_hand: dict | None`, zanim wyzerujesz `self.current_hand`!).
   - Pola `self.current_hand`:
     - `hand_number: int`, `table_id: str`, `start_ts_ms: int`, `blinds: tuple[int, int]`, `prize_pool: float | int`,
     - `hero_cards: list[str]`, `board_cards: list[str]`, `street: str`, `pot: int`,
     - `players: dict[int, dict]` dla `seat_id in (0, 1, 2)`:
       ```python
       {
           "seat_id": sid,
           "name": "Ty (S0)" if sid == 0 else f"Rywal {sid} (S{sid})",
           "is_dealer": bool,
           "stack": int | None,
           "invested_total": int,       # suma żetonów włożonych w całym rozdaniu
           "street_bet": int,           # aktualny bet na bieżącej ulicy (zerowany na STREET_CHANGE)
           "last_action": str,          # np. "BLIND 20", "CALL 40", "RAISE 100", "ALL-IN 565", "CHECK", "FOLD", "—"
           "last_decision_sec": float | None,
           "folded": bool,
       }
       ```
     - `action_log: list[dict]`: chronologiczna lista zdarzeń:
       ```python
       {
           "time_str": "19:14:22",      # HH:MM:SS (dla offline replay < 1e9 ms formatuj jako MM:SS)
           "street": "PREFLOP",
           "seat_id": 2,
           "player_name": "Rywal 2 (S2)",
           "action": "ALL-IN",
           "amount": 565,
           "invested_total": 565,
           "decision_sec": 1.8,         # None dla blindów startowych
       }
       ```
     - `recommendations: list[dict]`: lista rekomendacji HUD w tym rozdaniu (dodawana metodą `tracker.record_recommendation(decision, street, timestamp_ms)` wywoływana z `main.py`, z deduplikacją gdy ta sama akcja na tej samej ulicy nie uległa zmianie).

2. **Deterministyczne reguły aktualizacji `invested_total` i `folded`:**
   - **Start rozdania (`NEW_HAND`):** dla każdego `sid`: `street_bet = p.current_bet`, `invested_total = p.current_bet`, `folded = (not p.is_active) or (p.status_text == "FOLDED")`. Jeśli `p.current_bet > 0`, dodaj wpis startowy `BLIND` (`decision_sec=None`).
   - **Wzrost zakładu w trakcie ulicy (`curr_p.current_bet > street_bet`):**
     - `delta = curr_p.current_bet - street_bet`, `invested_total += delta`, `street_bet = curr_p.current_bet`.
     - Nazwa akcji:
       - jeśli `curr_p.stack == 0` lub `curr_p.status_text == "ALL_IN"` → `"ALL-IN"`,
       - jeśli `curr_p.current_bet == max_bet_before` → `"CALL"`,
       - jeśli `max_bet_before == 0` → `"BET"`,
       - inaczej → `"RAISE"`.
     - Dopisz wpis do `action_log` z `decision_sec = round(reaction_ms / 1000.0, 1)`.
   - **Wykrywanie `FOLD` (bez zgadywania):**
     - Warunek A: `curr_p.status_text == "FOLDED"` lub `not curr_p.is_active`.
     - Warunek B (`STREET_CHANGE`): jeśli przed zmianą ulicy `max_prev_bet > 0`, a gracz miał `prev_p.current_bet < max_prev_bet` oraz `(prev_p.stack or 0) > 0` (nie był all-in i nie sprawdził betu), oznacz `folded = True`, `last_action = "FOLD"` i dopisz `FOLD` do `action_log`.
     - Warunek C (Hero fold): jeśli `prev_state.is_hero_turn` było `True`, `to_call > 0`, teraz `state.is_hero_turn` jest `False`, a `hero.current_bet` nie wzrósł i nie zmieniła się ulica (lub zaczął się `NEW_HAND`), oznacz `folded = True`, `last_action = "FOLD"` i dopisz `FOLD` dla `seat_id=0`.
   - **Zmiana ulicy (`STREET_CHANGE`):** dla wszystkich aktywnych (nie-folded) graczy wyzeruj `street_bet = 0`.
   - Udostępnij metodę `tracker.get_hand_summary() -> dict` zwracającą płytką kopię gotową dla HUD.

### 3.2. Rejestrator historii rozdań (`state/hand_history.py`)

Stwórz klasę `HandHistoryRecorder(output_dir: str | Path = "hand_histories")`:
1. Przy pierwszym zapisie (lazy init, żeby w testach bez zapisu nie śmiecić katalogiem) tworzy katalog `output_dir` oraz parę plików:
   - `session_YYYYMMDD_HHMMSS.jsonl` (1 linia JSON na zakończone rozdanie),
   - `session_YYYYMMDD_HHMMSS.md` (czytelny raport Markdown: nagłówek rozdania `# Rozdanie #N (HH:MM:SS) — Blinds 50/100 | Prize $6`, karty Hero i Board, tabela graczy z `Włożył` i statusem `FOLD/ACTIVE`, chronologiczna lista zagrań z czasem decyzji oraz sekcja **Rekomendacje HUD** z akcją, sizingiem i EV).
2. Metody:
   - `record_hand(hand_summary: dict) -> None` — dopisuje rozdanie do `.jsonl` i `.md` z `flush()`. Pomija puste rozdania (bez kart Hero i bez żadnych akcji).
   - `close(active_trackers: dict[str, TableTracker] | None = None) -> None` — przy zamykaniu aplikacji zapisuje jeszcze niezamknięte bieżące rozdanie (jeśli ma karty/akcje) i zamyka uchwyty plików.
3. W `main.py`:
   - Inicjalizuj `hand_recorder = HandHistoryRecorder()` w trybie `live` (i opcjonalnie w `replay` z parametrem, nie zaśmiecając repo podczas testów).
   - Gdy `tracker.update(state)` zwróci zdarzenie `NEW_HAND` i `tracker.last_completed_hand` nie jest `None` → wywołaj `hand_recorder.record_hand(tracker.last_completed_hand)`.
   - W bloku `finally:` w `main.py` wywołaj `hand_recorder.close(trackers)`.
4. Dopisz `hand_histories/` do `.gitignore`.

---

## 4. Krok 4: Minimalistyczny HUD, Wizualne Karty, Tabela Zagrań i Osobny Guzik Kalibracji (`ui/hud.py`, `main.py`)

### 4.1. Funkcja wizualnych kart (`render_visual_cards_html` w `ui/hud.py`)

```python
def render_visual_cards_html(cards: list[str], empty_text: str = "—") -> str:
```
- Dla pustej listy zwraca `<span style="color: #64748b; font-size: 11px;">{empty_text}</span>`.
- Dla każdej karty (np. `"Ad"`, `"Tc"`, `"6c"`):
  - Zamień `"T"` na `"10"`.
  - Kolor i symbol: `h` → `♥` (`#dc2626`), `d` → `♦` (`#dc2626`), `s` → `♠` (`#0f172a`), `c` → `♣` (`#0f172a`).
  - Renderuj jako tabelę HTML `<table cellspacing="3" cellpadding="0" style="display: inline-table;"><tr>...</tr></table>`, gdzie każda karta to:
    ```html
    <td style="background-color: #f8fafc; color: {color}; border: 1px solid #94a3b8; padding: 2px 6px; font-weight: bold; font-size: 13px; white-space: nowrap;">{rank}{suit}</td>
    ```
  - Zaktualizuj również istniejącą `format_cards_html(scan_summary)` tak, aby dla kompatybilności korzystała z `render_visual_cards_html` (białe kafelki zamiast tekstu na czarnym tle).

### 4.2. Minimalistyczny układ HUD i rozdzielenie `Szczegóły` od `⚙` (Kalibracja)

1. **Tryb domyślny (`self.show_details == False` — maksymalnie minimalistyczny):**
   - Górny pasek: kompaktowy tytuł `POKER` + malutkie guziki `🔍` (Szczegóły), `⚡` (Tylko akcja), `+` (Dodaj stół).
   - Karta stołu:
     - Odznaka akcji z `format_action_label(...)` (np. **`BET 2 BB (200)`**, **`ALL-IN (235)`**, **`FOLD`**) + **`EV: +1.45 BB`**,
     - Poniżej rząd wizualnych białych kafelków: **Moje karty** + **Stół** (jeśli są),
     - Brak zbędnego opisu `reason`, brak `Buy-in`, brak panelu kalibracji, brak czarnego bloku diagnostycznego.
2. **Tryb rozwinięty (`self.show_details == True`):**
   - **KRYTYCZNE:** W `toggle_details()` (linia ~1312) **USUŃ** `self.adjust_panel.setVisible(self.show_details)`!
     - Kliknięcie `🔍 Szczegóły` **NIGDY** nie otwiera `self.calibration_panel`.
     - Jeśli zwijasz `Szczegóły` (`show_details == False`), a kalibracja nie jest w trakcie edycji (`editing_table_id is None`), upewnij się, że `self.calibration_panel.setVisible(False)`.
   - Zamiast dużego guzika `"✎ Kalibruj"`, w nagłówku stołu (widocznym po kliknięciu `Szczegóły`) umieść **malutki, dyskretny przycisk `⚙`** (`setFixedSize(22, 20)`, `setToolTip("Kalibracja ramki stołu")`, kliknięcie przełącza `start_table_calibration(tid)` / `cancel_table_calibration()`).
   - **Panel szczegółów dla stołu (`details_widgets[table_id]`, `QLabel` z `Qt.TextFormat.RichText`):**
     Wyraźna, czysta struktura HTML:
     1. **Moje karty:** białe kafelki z `render_visual_cards_html(hero_cards)`
     2. **Karty na stole:** białe kafelki z `render_visual_cards_html(board_cards)`
     3. **Tabela zagrań** (HTML `<table>` `width="100%"`, `cellpadding="3"`):
        - Nagłówki: `Gracz` | `Stack` | `Włożył` | `Zagranie` | `Czas`
        - Wiersze dla `S0`, `S1`, `S2`:
          - Dealer ma złotą odznakę `<span style="color:#f59e0b; font-weight:bold;">[D]</span>`.
          - Gracz z `folded == True` ma **wyszarzony wiersz** (`color: #64748b; background-color: rgba(255,255,255,0.02);`), przekreśloną nazwę `<s>...</s>` oraz akcję `FOLD`.
          - Aktywni gracze wyraźnym jasnym tekstem (`#f8fafc`), kolumna `Włożył` pogrubiona (np. `100`, `565`), kolumna `Czas` pokazuje np. `1.4s` (lub `—`).
        - Poniżej tabeli (jeśli `action_log` niepusty): kompaktowa, max 4-wierszowa historia ostatnich zagrań w rozdaniu z godziną (`19:14:22 • S2 ALL-IN 565 (1.8s)`).
     4. Jednoliniowa dyskretna stopka: `Blinds 50/100 • Pot 665 • Prize $6 • RIM (18 ms)`.

3. **Przekazywanie `hand_summary` z `main.py` do `ui/hud.py` (100% kompatybilności wstecznej):**
   - W `HudBridge` dodaj osobny sygnał: `hand_summary_updated = Signal(str, object)` (albo przyjmij opcjonalny 4. parametr, przy czym osobny sygnał `hand_summary_updated(table_id, hand_summary_dict)` **gwarantuje** brak kolizji z istniejącymi testami wywołującymi `on_decision_updated(decision, latency_ms)` i `on_decision_updated(decision, latency_ms, scan_summary)`!).
   - W `PokerHUD` podłącz `bridge.hand_summary_updated.connect(self.on_hand_summary_updated)`, przechowuj w `self.hand_summaries[table_id]` i odświeżaj HTML panelu szczegółów.

---

## 5. Krok 5: Testy i Weryfikacja (Obowiązkowe)

1. **Aktualizacja istniejącego testu:**
   - `tests/test_contracts.py`: `len(BLIND_LEVELS) == 7`, `BLIND_LEVELS[-1] == (60, 120)`.
2. **Nowe testy jednostkowe:**
   - `tests/test_strategy.py`: `test_quantize_sizing_to_bb_and_all_in` (wielokrotności `BB` dla `BB=20` i `BB=100`, przejście w `ALL_IN` przy `>= 65%` efektywnego stacka oraz przy `effective_stack <= 3 * BB`).
   - `tests/test_state.py`:
     - `test_tracker_hand_summary_invested_time_and_fold` (sumowanie `invested_total` przez ulice, `decision_sec`, wykrywanie `folded=True`),
     - `test_hand_history_recorder_jsonl_and_md` (zapis poprawnego JSONL i Markdown do `tmp_path` + `close()`).
   - `tests/test_ui_and_main.py`:
     - `test_render_visual_cards_html_and_action_labels` (białe kafelki `10♦`, `A♦`, `6♣` z właściwymi kolorami; `BET 2 BB (200)`, `RAISE 2 BB (40)`, `ALL-IN (235)`),
     - `test_hud_details_shows_table_with_grayed_fold_and_keeps_calibration_hidden` (kliknięcie `toggle_details()` pokazuje tabelę zagrań z wyszarzonym wierszem `FOLD` i mały guzik `⚙`, a `calibration_panel.isVisible()` pozostaje **`False`** dopóki nie kliknie się `⚙`).
3. **Regresja na nagraniach (`nagrania testowe/`):**
   - Zweryfikuj kluczowe klatki z `211257`, `224127` i `2 gry na raz` po mikro-kalibracji `seat_2_bet`, `seat_1/2_dealer` i `blinds`: 100% `VALID`, brak regresji OCR, wszystkie zakłady w wielokrotnościach `BB` lub `ALL_IN`.
   - Uruchom pełny **`pytest -v tests/`** — 100% testów musi przejść na zielono.

---

## 6. Obowiązkowa Synchronizacja na GitHub (Po Zakończeniu Prac)

1. Dopisz `hand_histories/` do `.gitignore`.
2. Jeśli pojawiły się jakiekolwiek niepewności lub otwarte pytania — zapisz je w **`QUESTIONS_V13.md`** w katalogu głównym repozytorium (nie zgaduj!). Jeśli wszystko było jasne, nie twórz tego pliku.
3. Dopisz szczegółowy raport V13 (zmiany, wyniki `pytest`, wyniki weryfikacji nagrań) na samej górze **`PROGRESS_LOG.md`**.
4. Wykonaj `git add -A`, `git commit -m "V13: ROI micro-tuning, minimalist HUD with visual cards & action table, BB-multiple sizing, hand history recorder"`, `git push origin main`.
5. W odpowiedzi końcowej napisz **krótkie potwierdzenie** (i ewentualną wzmiankę, jeśli dodałeś `QUESTIONS_V13.md`) oraz podaj **WYŁĄCZNIE** link do repozytorium:
   `https://github.com/leonkazimierzzielinski-spec/poker-genius`
