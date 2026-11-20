# Konstytucja Projektu: Asystent Decyzyjny Poker (3-Handed Hyper-Turbo)

Dokument stanowi nadrzędną specyfikację techniczną, architektoniczną i organizacyjną projektu `poker_assistant`. Każdy agent pracujący w Antigravity nad dowolnym modułem systemu ma obowiązek przestrzegać poniższych zasad, kontraktów danych i granic odpowiedzialności.

---

## 1. Żelazne Zasady Systemu (Inwarianty Nienaruszalne)

1. **Architektura w 100% nieinwazyjna:** System nie odczytuje pamięci procesu przeglądarki, nie wstrzykuje kodu w DOM strony i nie analizuje ruchu sieciowego. Jedynym źródłem danych wejściowych jest obraz z ekranu (lub zapisane klatki w trybie testowym Offline Replay).
2. **Model Human-in-the-Loop:** System pełni wyłącznie pasywną funkcję doradczą (HUD). Fizyczne kliknięcia na stole wykonuje człowiek. Zabronione jest dodawanie jakichkolwiek modułów symulujących ruchy myszy lub kliknięcia w oknie gry.
3. **100% przetwarzanie lokalne:** Całość obliczeń (CV, OCR, logika preflop/postflop, Monte Carlo, HUD) działa lokalnie na stacji roboczej (Windows, Intel Core Ultra 7 255H, 32 GB RAM) bez zapytań do zewnętrznych API i bez użycia modeli LLM w pętli czasu rzeczywistego.
4. **Budżet czasowy decyzji:** Czas od przechwycenia klatki do wyświetlenia rekomendacji na nakładce HUD nie może przekraczać **0,3 s** (przy limicie 5 s na decyzję w grze).

---

## 2. Środowisko Docelowe i Specyfika Domeny (Stake 3-Handed)

| Parametr | Wartość / Charakterystyka | Wpływ na implementację |
| :--- | :--- | :--- |
| System operacyjny | Windows | Przechwytywanie ekranu przez `dxcam` (DirectX Desktop Duplication) oraz obsługa flag okna click-through przez Win32 API. |
| Stos technologiczny | Python 3.11+ | Jednolity język dla wszystkich warstw (`dxcam`, `opencv-python`, `phevaluator`/`treys`, `PySide6`, `pytest`). |
| Okno gry | Przeglądarkowe, skalowalne i przesuwalne | Wymagane wykrywanie stałej kotwicy (Anchor) i operowanie na współrzędnych relatywnych (`0.0–1.0`). |
| Multi-tabling | Obsługa 1 lub wielu stołów jednocześnie | Każdy obserwowany stół działa jako niezależna instancja `TableTracker` z przypisanym widokiem HUD. |
| Format i pula startowa | 3-Handed Hyper-Turbo, 300 żetonów/gracz | Łączna suma żetonów na stole to zawsze **900** (liczby całkowite w żetonach, bez przeliczania na BB). |
| Struktura blindów | `10/20 → 15/30 → 20/40 → 30/60 → 40/80` | Zakres głębokości stacków od `15 BB` do `3.75 BB`. Ewentualne ante nie zmienia sumy kontrolnej `900`. |
| Ekonomia i nagrody | Wpisowe `2` (skalowalne `10`, `50`), pula `4–40 000` | Pule `4 / 6 / 8` to format winner-takes-all; od `10+` (gdy wypłacane są >1 miejsca) włącza się model ICM. |
| Talia i elementy stołu | Stały motyw graficzny, talia **2-kolorowa** | Karo i kier są czerwone, pik i trefl czarne — dopasowanie kart (`cv2.matchTemplate`) musi opierać się na pełnym kształcie rangi i koloru. |
| Detektor tury i Showdown | Przyciski `Fold / Check / Bet` w prawym dolnym rogu | Brak przycisków akcji (np. podczas All-in runout) automatycznie przełącza HUD w stan oczekiwania `WAITING_FOR_TURN`. |
| Statusy wyjątkowe | `Sit out`, `Disconnected` | Brak liczby w polu stacka nie może powodować błędu krytycznego; gracz oznaczany jest jako nieaktywny. |

---

## 3. Struktura Katalogów Projektu

Wszystkie moduły rozwijane są w obrębie jednego repozytorium według poniższego podziału:

```text
poker_assistant/
├── CONSTITUTION.md
├── config.json                 # Współrzędne relatywne ROI, progi pewności, ustawienia HUD
├── requirements.txt
├── main.py                     # Orkiestrator pętli wielowątkowej i wielostołowej
├── core/
│   ├── contracts.py            # Wspólne struktury danych (TableState, PlayerState, Decision)
│   └── constants.py            # Stałe gry (TOTAL_CHIPS=900, progi EV, blindy)
├── vision/
│   ├── capture.py              # dxcam (live) + OfflineReplayCapture (zrzuty/wideo)
│   ├── anchor.py               # Wykrywanie kotwicy i skalowanie ROI
│   ├── card_recognizer.py      # cv2.matchTemplate na 52 wzorcach rogów kart
│   └── ocr.py                  # Preprocessing i odczyt cyfr 0–9 oraz statusów
├── state/
│   ├── validator.py            # Sanity checks (suma==900, unikalność kart, monotoniczność)
│   ├── tracker.py              # Maszyna stanów stołu, ulice, Timing Tells (ms)
│   └── logger.py               # Lekkie logowanie sparsowanych zdarzeń do .jsonl / .csv
├── engine/
│   ├── preflop_nash.py         # Tablice Push/Fold, Min-raise, Iso-Shove (3.75–15 BB) w RAM
│   ├── flop_db.py              # Loader i wyszukiwarka bazy 1 755 kanonicznych flopów
│   ├── monte_carlo.py          # Szybki kalkulator Equity/EV (phevaluator / treys)
│   └── solver_builder.py       # Skrypt wsadowy offline do przeliczenia 1 755 flopów (TexasSolver)
├── strategy/
│   ├── multiplier_adapter.py   # Profile LOOSE_CALLERS (4), STANDARD_EXPLOIT (6/8), HIGH_STEAL (10+)
│   ├── exploit.py              # Modyfikatory MDA, Timing Tells, Sizing Tells
│   └── simplifier.py           # Próg EV-Loss (+0.08 BB), czyste strategie, redukcja sizingów
├── ui/
│   └── hud.py                  # Nakładka PySide6 (click-through + skrót do przesuwania)
├── tools/
│   ├── calibrator.py           # Narzędzie do zaznaczania relatywnych ROI i wycinania wzorców
│   └── offline_tester.py       # Odtwarzacz klatek testowych do strojenia CV/OCR
├── data/
│   ├── templates/cards/        # 52 wzorce rogów kart
│   ├── templates/digits/       # Wzorce cyfr 0–9
│   ├── preflop_tables/         # Tablice Nasha (JSON)
│   └── postflop_db/            # Baza 1 755 flopów (izomorfizm)
└── tests/                      # Testy jednostkowe pytest dla każdego modułu
```

---

## 4. Kontrakty Danych (Interfejsy Międzymodułowe)

Moduły komunikują się wyłącznie przez ustandaryzowane obiekty zdefiniowane w `core/contracts.py`. Zmiana poniższych pól wymaga aktualizacji Konstytucji.

### `PlayerState`
* `seat_id`: `int` (`0` = Hero, `1` = Lewy rywal, `2` = Prawy rywal)
* `stack`: `int | None` (`None`, jeśli status `Sit out` lub błąd odczytu)
* `current_bet`: `int` (aktualny zakład przed graczem na danej ulicy)
* `is_dealer`: `bool`
* `is_active`: `bool` (czy gracz bierze udział w rozdaniu)
* `status_text`: `str` (np. `"ACTIVE"`, `"SIT_OUT"`, `"ALL_IN"`)
* `last_reaction_ms`: `int | None` (zmierzony czas reakcji w milisekundach)

### `TableState`
* `table_id`: `str` (identyfikator okna lub regionu dla multi-tablingu)
* `timestamp_ms`: `int`
* `prize_pool`: `int` (wylosowana pula nagrody, np. `4`, `6`, `8`, `20`)
* `small_blind`: `int`
* `big_blind`: `int`
* `pot`: `int`
* `hero_cards`: `list[str]` (np. `["Qh", "4h"]`, puste gdy brak)
* `board_cards`: `list[str]` (0, 3, 4 lub 5 kart, np. `["Qd", "Qs", "8d"]`)
* `street`: `str` (`"PREFLOP"`, `"FLOP"`, `"TURN"`, `"RIVER"`, `"WAITING_FOR_TURN"`)
* `is_hero_turn`: `bool` (wykryte na podstawie widoczności przycisków akcji Hero)
* `available_actions`: `list[str]` (np. `["FOLD", "CHECK", "BET"]`)
* `players`: `dict[int, PlayerState]`
* `is_valid`: `bool` (wynik przejścia testów spójności)

### `Decision`
* `table_id`: `str`
* `action`: `str` (`"FOLD"`, `"CHECK"`, `"CALL"`, `"MIN_RAISE"`, `"BET_30"`, `"ALL_IN"`, `"WAIT"`)
* `ev_bb`: `float | None` (szacowana wartość oczekiwana w BB)
* `confidence`: `float`
* `profile_used`: `str` (`"LOOSE_CALLERS"`, `"STANDARD_EXPLOIT"`, `"HIGH_STEAL"`)
* `reason`: `str` (krótki opis do wyświetlenia na HUD, np. `"MDA +15% shove vs limp"`, `"Timing Tell: fast check"`)

---

## 5. Reguły Walidacji (Sanity Checks) i Logowanie

Każda klatka przed przekazaniem z `vision/` do `engine/` musi przejść walidację w `state/validator.py`:

1. **Zasada zachowania żetonów:** Suma `stack + current_bet` wszystkich 3 graczy oraz `pot` musi wynosić dokładnie **900**. Odchylenie oznacza animację przesuwania żetonów lub błąd OCR i powoduje odrzucenie klatki.
2. **Unikalność i pewność kart:** Brak duplikatów pomiędzy `hero_cards` a `board_cards`. Dopasowania z `cv2.matchTemplate` o pewności (`confidence`) poniżej **0.92** są odrzucane.
3. **Monotoniczność blindów:** Wartości `small_blind` i `big_blind` w obrębie jednego `table_id` nie mogą maleć w trakcie trwania turnieju.
4. **Polityka logowania:** System zapisuje wyłącznie lekkie logi tekstowe (`.jsonl` / `.csv`) zawierające sparsowane obiekty `TableState`, `Decision` oraz metryki czasu. Zapisywanie surowych zrzutów ekranu na dysk jest wyłączone w trybie produkcyjnym i służy wyłącznie do tworzenia małego zbioru testowego dla trybu Offline Replay.

---

## 6. Logika Matematyczna, Eksploatacja i Nakładka HUD

1. **Preflop (`3.75–15 BB`):** Odczyt z gotowych tablic Nasha (Push/Fold, Min-raise, Iso-Shove) trzymanych w pamięci RAM (`~0.001 s`).
2. **Postflop (`10–15 BB`):** Warstwa hybrydowa łącząca precomputed bazę **1 755 kanonicznych flopów** (sprowadzonych z 22 100 kombinacji przez izomorfizm kolorów, przeliczonych w `TexasSolver` dla drzewa `Check / Bet 25–30% / All-in`) z szybkim symulatorem Monte Carlo (`< 0.1 s`).
3. **Adapter mnożnika (`MultiplierAdapter`):**
   * **Pula 4 (2x) — `LOOSE_CALLERS`:** ograniczenie blefów postflop o ~30%, szersze All-iny for value, wybór opcji o wyższej wariancji w spotach granicznych (`~0 EV`).
   * **Pule 6 / 8 (3x–4x) — `STANDARD_EXPLOIT`:** standardowe modyfikacje MDA (`+10–15%` zakresów All-in przeciwko zbyt ciasnym sprawdzeniom, agresywne Iso-Shove przeciwko open-limp, małe C-bety `25–30%` na suchych flopach).
   * **Pule 10 / 12+ (5x+) — `HIGH_STEAL`:** podniesienie agresji kradzieży blindów o `+15–20%` przeciwko wystraszonym rywalom (scared money) oraz przełączenie na model ICM przy wypłatach dla więcej niż 1 miejsca.
4. **Sygnały ze stołu:**
   * **Timing Tells:** Natychmiastowy check rywala (`< 0.5 s`) klasyfikowany jako brak trafienia w stół i premia dla małego blefu.
   * **Sizing Tells:** Dziwne małe zakłady (np. `1 BB` na flopie) klasyfikowane jako słaba ręka lub dobieranie → agresywne przebicie lub All-in.
5. **Upraszczanie strategii (Ochrona przed profilem RTA):**
   * Odrzucanie marginalnych zagrań o zysku niższym niż **+0.08 BB** (`EV-Loss Threshold`).
   * Zamiana miksów procentowych solvera na deterministyczne reguły czyste oparte na sile ręki i blokerach.
   * Ograniczenie sizingów postflop do maksymalnie dwóch standardowych wartości (`25–30%` puli oraz `All-in`).
6. **Nakładka HUD (`PySide6`):**
   * Okno bezramkowe, zawsze na wierzchu (`WindowStaysOnTopHint`), domyślnie przezroczyste dla kliknięć myszy (`WS_EX_TRANSPARENT`).
   * Wbudowany tryb edycji pozycji (skrót klawiszowy np. `Ctrl+Shift+L` lub mały przycisk kłódki), który tymczasowo wyłącza tryb click-through, pozwala swobodnie przesunąć HUD i ponownie go blokuje.

---

## 7. Podział Prac na Etapy dla Agentów w Antigravity

Prace realizowane są sekwencyjnie lub równolegle w ramach **6 jasno wydzielonych części**. Każda część musi zostać dostarczona z testami jednostkowymi `pytest` weryfikującymi zgodność z kontraktami z sekcji 4 (bez blokowania tempa prac nadmiernym formalizmem).

1. **Część 1 — Szkielet, Kontrakty i Narzędzie Kalibracyjne:** `core/`, `config.json`, `tools/calibrator.py`. Możliwość zaznaczenia ROI na zrzucie ekranu (zapis relatywny) i wycięcia wzorców kart/cyfr.
2. **Część 2 — Przechwytywanie Ekranu i Moduł Wizyjny:** `vision/`. Obsługa wielu stołów przez `dxcam` + `OfflineReplayCapture`, wykrywanie kotwicy, rozpoznawanie kart (`>= 0.92`) i cyfr, detekcja tury Hero.
3. **Część 3 — Maszyna Stanów, Walidacja i Logger:** `state/`. Testy spójności (`suma == 900`), wykrywanie zmian ulic, pomiar `last_reaction_ms` oraz zapis do `.jsonl`.
4. **Część 4 — Silnik Matematyczny Preflop i Postflop:** `engine/`. Tablice Nasha w RAM, kalkulator Monte Carlo (`< 0.1 s`), obsługa bazy `1 755` flopów i skrypt do jej wygenerowania przez `TexasSolver`.
5. **Część 5 — Warstwa Eksploatacyjna i Upraszczania:** `strategy/`. `MultiplierAdapter`, reguły MDA, obsługa Timing/Sizing Tells, filtr `+0.08 BB` i redukcja miksów do strategii czystych.
6. **Część 6 — Nakładka HUD i Orkiestrator:** `ui/hud.py` i `main.py`. Przesuwalna nakładka click-through w `PySide6` (multi-table) spięta z pętlą czasu rzeczywistego (`< 0.3 s`).
