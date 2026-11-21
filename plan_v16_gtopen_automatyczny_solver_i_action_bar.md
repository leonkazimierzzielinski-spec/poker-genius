# Plan V16 — Automatyczna Instalacja i Pipeline Nocny `GTOpen` (Preflop 0–15 BB + Baza 47 Flopów), Integracja `FlopDatabase` oraz Ulepszony `ActionBarOverlay` (`poker_assistant`)

Dokument jest kompletną specyfikacją wdrożeniową V16 dla agentów. Cel: **zautomatyzować wszystko samodzielnie** — od poprawki `ActionBarOverlay` i `HU_SB`, przez instalację i kompilację otwartego solvera [GTOpen (Apache 2.0)](https://github.com/MatthewPDingle/GTOpen) na CPU (Intel Core Ultra 5 225H, 14 rdzeni AVX2), aż po napisanie i przetestowanie skryptu nocnego generującego prawdziwe solverowe tabele preflop i bazę 47 kanonicznych flopów dla 15 BB.

> **Zasada "Zero działania na ślepo" (`QUESTIONS_V16.md`)**: Jeśli podczas instalacji Rust/MSVC/GTOpen (np. brak uprawnień administratora) lub mapowania API `GTOpen` trafisz na bloker albo niejasność — **NIE zgaduj i nie rób prowizorek**. Zrealizuj wszystkie pewne części (w tym Krok 1, Krok 4 i testy), a konkretne pytania / wymagane akcje użytkownika zapisz w pliku **`QUESTIONS_V16.md`** w katalogu głównym repozytorium i wypchnij go razem z commitem. Jeśli wszystko poszło w pełni automatycznie, nie twórz tego pliku.

## 0. Kluczowe Decyzje Architektoniczne (Już Podjęte)

| Obszar | Podjęta decyzja (obowiązująca) | Powód | 
| ----- | ----- | ----- | 
| **Lokalizacja `GTOpen`** | Sklonuj i zbuduj `GTOpen` **POZA** repozytorium `poker genius`, dokładnie w katalogu **`c:\Users\leonk\Desktop\porjekty\gtopen\`** (build CPU release: `cargo build --release`, bez CUDA — laptop ma Intel Core Ultra 5 225H / Intel Arc 130T). | Nie zaśmieca naszego repozytorium Git ciężkimi plikami Rust/target (kilka GB) i pozwala na czysty lokalny serwer / CLI. | 
| **Parametry solvera (14 rdzeni CPU)** | Używaj **12 wątków** (zostawiając 2 rdzenie dla Windowsa). Proste drzewa sizingów: preflop `2 BB` + `LIMP` + `ALL-IN`; postflop `33%` / `50%` / `ALL-IN`, dokładność `0.5%` puli (szybka zbieżność na CPU, praktycznie 0 straty EV). | 12 wątków Arrow Lake @ 4.9 GHz AVX2 pozwala policzyć 47 flopów w 1–3 godziny w nocy bez zawieszania systemu. | 
| **4 priorytetowe spoty (47 flopów)** | `BTN_vs_BB_SRP`, `SB_vs_BB_LIMPED`, `HU_SB_vs_BB_SRP`, `HU_SB_vs_BB_LIMPED` (efektywny stack `12 BB`, pula odpowiednio `4 BB` / `2 BB`, 0% dodatkowego postflop rake — rake w JAQKPOT! jest w tabeli mnożników, nie w puli!). | Te 4 spoty pokrywają \~80% wszystkich flopów w 15 BB 3-max/HU; zapis z checkpointami po każdym flopie chroni przed utratą postępu. | 
| **Dopasowanie najbliższego flopa** | W `engine/flop_db.py` dodaj `lookup_nearest_flop(board_cards, spot, hero_hand)` mapujące dowolny z 1755 kanonicznych flopów na najbliższy rozwiązany klaster z 47 flopów (po teksturze: high card, para, kolor, konektory). | Natychmiast wykorzystuje bazę 47 flopów na 100% realnych rozdań (z płynnym fallbackiem do `RangeTracker`, jeśli baza jeszcze pusta). | 
| **Ulepszony `ActionBarOverlay`** | Domyślnie **ZAWSZE włączony** obok HUD (niezależnie od trybu `⚡ Tylko akcja`, z możliwością ukrycia osobnym kliknięciem), **szerszy** (+25–30%, min. `112 px` na badge), tekst w **2 czytelnych wierszach** (np. wiersz 1: `▲ RAISE 2 BB`, wiersz 2: `(60)  +1.29 BB`), idealnie wycentrowany pod konkretnym guzikiem (`Fold` / `Check-Call` / `Bet-Raise`). | Nigdy więcej ucinania tekstu akcji i pełna widoczność wskaźników pod guzikami w każdym rozdaniu. | 

## 1. Krok 1: Ulepszenie `ActionBarOverlay` i Korekta `HU_SB` (`ui/hud.py`, `main.py`, `data/preflop_tables/nash_3max.json`)

1. **Zawsze widoczne, szersze, 2-wierszowe wskaźniki `ActionBarOverlay` (`ui/hud.py`, `main.py`):**

   * W `HudOverlay.__init__`: ustaw domyślnie wyświetlanie nakładki `ActionBarOverlay` jako **aktywne od startu** (tj. wskaźniki pod guzikami akcji pojawiają się zawsze podczas gry, również gdy widoczny jest normalny HUD; przycisk `⚡ Tylko akcja` nadal przełącza ukrycie głównego okna HUD, zostawiając samo `ActionBarOverlay`).

   * W `ActionBarOverlay.get_badge_rect_for_action(...)` i `paintEvent(...)`:

     * Zwiększ szerokość każdego badge'a do **`max(112, int(btn_w * 1.28))`** (wycentrowanego dokładnie względem środka konkretnego guzika akcji: `center_x = btn_x + btn_w / 2`, `bx = int(center_x - bw / 2)`!) oraz wysokość do **`max(38, int(bh * 1.35))`** (z bezpiecznym clampem do ekranu).

     * Renderuj tekst w **2 czytelnych wierszach** z nieco mniejszą, ostrą czcionką:

       * Wiersz 1 (pogrubiony, `11 px`): główna akcja, np. `▲ RAISE 2 BB`, `▲ BET 1 BB`, `▲ ALL-IN`, `▲ CALL`, `▲ CHECK`, `▲ FOLD` (lub `▲ PLAN: ...`).

       * Wiersz 2 (`10 px`, lekko przytłumiony biały `#e2e8f0`): kwota żetonów i EV, np. `(60) • +1.29 BB` (albo samo `(280)` gdy EV brak).

       * Jeśli tekst nadal byłby szerszy niż `bw - 8`, dynamicznie dopasuj rozmiar fontu (min. `9 px`), żeby **nigdy** nie ucinało liter!

2. **Natychmiastowa korekta tabeli `HU_SB` (`data/preflop_tables/nash_3max.json`):**

   * W `HU_SB` (Heads-Up na BTN/SB) dla `10–15 BB`: rozszerz zakres otwarcia / limpu do \~80–85% rąk (m.in. `87o`, `76o`, `97o`, wszystkie suited konektory i gappersy grają `CALL`/limp lub `MIN_RAISE`, **nigdy `FOLD`** przy 9–15 BB!); `A2s–A6s` przy `11–15 BB` grają **`MIN_RAISE` (2 BB)** lub `LIMP`, a nie `ALL_IN` za 12 BB!

## 2. Krok 2: Automatyczna Instalacja i Kompilacja `GTOpen` (`c:\Users\leonk\Desktop\porjekty\gtopen\`)

Wykonaj samodzielnie w środowisku lokalnym Windows:

1. Sprawdź czy `git`, `rustc`, `cargo` oraz kompilator MSVC (`cl.exe` / Visual Studio Build Tools) są zainstalowane.

   * Jeśli brakuje Rust (`rustup`/`cargo`) → zainstaluj przez `winget install -e --id Rustlang.Rustup` (lub oficjalny instalator).

   * Jeśli brakuje MSVC C++ Build Tools → spróbuj zainstalować przez `winget` lub, jeśli wymaga uprawnień administratora/restartu, zanotuj dokładny krok w `QUESTIONS_V16.md` i przejdź dalej do przygotowania wszystkich skryptów w `poker genius`.

2. Sklonuj repozytorium:

   ```
   git clone https://github.com/MatthewPDingle/GTOpen.git "c:\Users\leonk\Desktop\porjekty\gtopen"
   
   ```

3. Zbuduj binarkę CPU release (bez CUDA):

   ```
   cd "c:\Users\leonk\Desktop\porjekty\gtopen"
   cargo build --release -p server
   
   ```

   *(Sprawdź w `Cargo.toml` / `start.sh` / `GTOpen.cmd` dokładną nazwę binarki serwera lub CLI w `GTOpen` — dostosuj komendę do aktualnej struktury repozytorium `GTOpen`!).*

4. Zbadaj dokładne endpointy HTTP API serwera `GTOpen` (w `crates/server` i `docs/`) lub tryb CLI — na tej podstawie zbuduj bezbłędny skrypt w Kroku 3.

## 3. Krok 3: W pełni Automatyczny Skrypt Nocny `tools/run_gtopen_overnight.py`

Stwórz w naszym repozytorium `poker genius` skrypt **`tools/run_gtopen_overnight.py`** obsługujący 2 tryby:

* `--mode dry-test`: szybki test end-to-end (\~1–2 minuty): 1 spot Preflop + 3 reprezentatywne flopy (`Ah 7d 2c`, `Jh Ts 8s`, `Kd Kh 4c`), weryfikujący pełny zapis i import do `poker genius`.

* `--mode overnight`: pełne nocne liczenie (4 główne spoty × 47 kanonicznych flopów + pełny Preflop Lab 15/12/10/8/6/4 BB dla 3-max i HU).

Wymagania funkcjonalne `tools/run_gtopen_overnight.py`:

1. **Automatyczny start i zatrzymanie lokalnego serwera `GTOpen`** (uruchamia proces z `c:\Users\leonk\Desktop\porjekty\gtopen\target\release\...`, czeka aż port odpowie, a w `finally:` czysto go zamyka).

2. **Blokada uśpienia Windowsa podczas liczenia** (`ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)` — `ES_CONTINUOUS | ES_SYSTEM_REQUIRED` na czas trwania skryptu, przywracane w `finally:`), żeby laptop nie zasnął w nocy!

3. **Checkpointy i wznawianie (`--resume`)**: po każdym policzonym flopie dopisuje wynik do pliku checkpointowego `data/flop_db/gtopen_progress.json` — jeśli skrypt zostanie przerwany, ponowne uruchomienie wznawia od ostatniego niepoliczonego flopa.

4. **Czytelny log postępu w konsoli**: np. `[Spot 1/4: BTN_vs_BB_SRP] Flop 14/47 (Kd 8s 3c) -> solved in 41.2s (exploitability 0.48%) | ETA: 22 min`.

5. **Automatyczny eksport do formatu `poker genius`**: po zakończeniu każdego spota aktualizuje `data/flop_db/gtopen_47_flops.json` (dla postflopu) oraz `data/preflop_tables/nash_3max.json` (z zachowaniem kopii zapasowej `nash_3max.backup.json` przed nadpisaniem!).

## 4. Krok 4: Integracja Bazy `gtopen_47_flops.json` w `engine/flop_db.py` i `main.py`

1. W `engine/flop_db.py`:

   * Dodaj ładowanie opcjonalnej bazy `data/flop_db/gtopen_47_flops.json` (jeśli istnieje).

   * Zaimplementuj funkcję **`lookup_nearest_flop(board_cards: list[str], spot: str, hero_cards: list[str]) -> dict[str, float] | None`**:

     * Najpierw szuka dokładnego dopasowania kanonicznego (`canonicalize_flop(board_cards)`).

     * Jeśli dokładny flop nie jest wśród 47 policzonych, wylicza prosty wektor cech tekstury dla `board_cards` i dla każdego z 47 flopów w bazie: `(high_card_rank, mid_card_rank, is_paired, is_monotone, is_two_tone, is_connected)` oraz siłę/klasę ręki Hero na tym boardzie (`classify_combo` z `engine/range_engine.py`: `MONSTER`, `STRONG`, `MEDIUM`, `DRAW`, `AIR`) — zwraca zagregowaną strategię / EV dla tej klasy ręki na najbliższym klastrze flopa!

   * Jeśli baza nie istnieje lub spot nie jest w bazie, zwraca `None` → `main.py` płynnie używa naszego silnika `Range-vs-Range` z V15.

2. W `main.py` (`evaluate_candidates`):

   * Na Flopie w 4 głównych spotach najpierw sprawdź `flop_db.lookup_nearest_flop(...)`; jeśli zwróci wynik z bazy `GTOpen`, użyj go jako bazowych `candidate_evs` (w `< 2 ms`!).

## 5. Krok 5: Testy, Dry-Test `GTOpen` i Weryfikacja (Obowiązkowe)

1. **Testy jednostkowe:**

   * `tests/test_ui_and_main.py`:

     * `test_action_bar_enabled_by_default_and_two_line_wider_badges`: sprawdza, że `ActionBarOverlay` jest aktywne domyślnie, badge ma szerokość `>= 112 px` i jest wycentrowany pod guzikiem akcji.

   * `tests/test_strategy.py`:

     * `test_hu_sb_87o_not_fold_and_a4s_12bb_not_all_in`: `7s 8c` w `HU_SB` przy 9.25 BB nie zwraca `FOLD`; `4d Ad` przy 12 BB gra `MIN_RAISE` (nie `ALL_IN`).

   * `tests/test_engine.py`:

     * `test_flop_db_nearest_cluster_lookup_and_fallback`: weryfikuje mapowanie dowolnego flopa na najbliższy klaster z bazy `gtopen_47_flops.json` i bezpieczny fallback gdy pliku brak.

2. **Test próbny (`dry-test`):**

   * Jeśli `GTOpen` skompilowało się poprawnie, uruchom `python tools/run_gtopen_overnight.py --mode dry-test` (1 preflop + 3 flopy) i wpisz zmierzony czas na 1 flop oraz dokładny szacunek czasu dla pełnej paczki nocnej (`4 × 47` flopów) w `PROGRESS_LOG.md`!
4. **Automatyczne uruchomienie pełnego nocnego liczenia przez agenta (zero ręcznego wpisywania przez użytkownika!):**
   * Natychmiast po `git push origin main` i potwierdzeniu zielonego `dry-test`, **samodzielnie uruchom** pełne liczenie nocne `python tools/run_gtopen_overnight.py --mode overnight --resume` jako odłączony proces w tle na Windowsie (np. `Start-Process python -ArgumentList 'tools/run_gtopen_overnight.py','--mode','overnight','--resume' -WorkingDirectory 'c:\Users\leonk\Desktop\porjekty\poker genius' -RedirectStandardOutput 'logs/gtopen_overnight.log' -RedirectStandardError 'logs/gtopen_overnight_err.log'`), zweryfikuj po 5 sekundach, że proces żyje i zapisuje postęp do `logs/gtopen_overnight.log`, i potwierdź to w odpowiedzi końcowej!

3. **Pełny `pytest -v tests/`** — 100% testów na zielono.

## 6. Obowiązkowa Synchronizacja na GitHub (Po Zakończeniu Prac)

1. Upewnij się, że katalog `gtopen` leży **poza** repozytorium `poker genius`, a duże pliki tymczasowe (`gtopen_progress.json`) są w `.gitignore` (natomiast finalny kompaktowy `data/flop_db/gtopen_47_flops.json` może być w repo jeśli `< 10 MB`).

2. Jeśli pojawiły się jakiekolwiek niejasności lub blokery instalacji (np. wymagane uprawnienia administratora dla MSVC/Rust) — zapisz je precyzyjnie w **`QUESTIONS_V16.md`** w katalogu głównym repozytorium.

3. Dopisz szczegółowy raport V16 (w tym wynik kompilacji `GTOpen`, wynik `dry-test` i szacowany czas nocnego liczenia) na samej górze **`PROGRESS_LOG.md`**.

4. Wykonaj `git add -A`, `git commit -m "V16: Always-on wider 2-line ActionBar, HU_SB fix, GTOpen overnight solver pipeline & nearest-flop DB integration"`, `git push origin main`.

5. W odpowiedzi końcowej napisz krótkie potwierdzenie (z informacją, czy `GTOpen` jest już gotowe do nocnego biegu i czy powstał `QUESTIONS_V16.md`) i podaj **WYŁĄCZNIE** link do repozytorium:
   `https://github.com/leonkazimierzzielinski-spec/poker-genius`