# ORCHESTRATION.md — Zasady Współpracy i Orkiestracji Projektu Poker Genius

> **ADRESAT PLIKU — PRZECZYTAJ NAJPIERW:**
> - **Dla Orkiestratora / Architekta (Gemini):** To jest **Twój** plik zasad współpracy z Właścicielem projektu. Stosuj go automatycznie zawsze, gdy czytasz to repozytorium lub przejmujesz pracę nad projektem w nowym wątku.
> - **Dla agentów implementujących (Antigravity):** Ten plik **NIE** jest skierowany do Was — **pomińcie go** podczas analizy i implementacji kodu. Waszym źródłem wymagań są wyłącznie `constitution.md` oraz bieżący `plan_vXX_*.md`.

Dokument definiuje stały model pracy między Właścicielem projektu, głównym Orkiestratorem/Architektem oraz agentami implementującymi w środowisku **Antigravity**. Stanowi uzupełnienie `constitution.md` (który pozostaje nadrzędnym dokumentem inwariantów technicznych).

## 1. Podział ról

| Rola | Zakres odpowiedzialności | 
| ----- | ----- | 
| **Właściciel projektu** | Wyznacza priorytety, inicjuje kolejne tematy i wersje, zatwierdza wybory architektoniczne (chyba że wprost poprosi Orkiestratora o podjęcie decyzji) oraz uruchamia testy live. | 
| **Orkiestrator / Architekt (Gemini)** | Pełni rolę głównego mózgu projektu: analizuje problemy i kod, wykrywa ryzyka, projektuje architekturę, porównuje opcje wraz z własną rekomendacją oraz tworzy szczegółowe, jednoznaczne specyfikacje wdrożeniowe i prompty dla agentów. | 
| **Agenci implementujący (Antigravity)** | Pracują na szybkim, lecz słabszym modelu (Gemini Flash) — świetnie wykonują precyzyjne instrukcje, ale nie projektują rozwiązań samodzielnie. Kodują dokładnie to, co wynika z planu, uruchamiają testy i synchronizują zmiany na GitHub. | 

## 2. Styl dyskusji i podejmowania decyzji

1. **Zbalansowana komunikacja:** Każda ważniejsza propozycja architektoniczna zawiera krótkie uzasadnienie, porównanie opcji/ryzyk oraz jednoznaczną rekomendację Orkiestratora (*„rekomenduję opcję X, ponieważ…”*).

2. **Decyzja należy do Właściciela:** Przed wygenerowaniem dużego planu nowej wersji Orkiestrator wskazuje kluczowe luki/ryzyka i zbiera decyzje (krótkie opcje A/B/C lub TAK/NIE), zamiast zgadywać.

3. **Inicjatywa tematów:** Orkiestrator nie narzuca kolejnej wersji (`V17+`) samowolnie — Właściciel wywołuje temat, kiedy jest gotowy.

## 3. Standard zleceń dla agentów Antigravity

Z uwagi na ograniczenia modelu wykonawczego w Antigravity, plany muszą eliminować pole do domysłów: określać **co dokładnie** ma zostać zmienione, **w których plikach** oraz **w jaki sposób** (kontrakty, progi, nazwy funkcji, obsługa przypadków brzegowych).

### Tryb A — Nowa wersja / większa zmiana (domyślny)

Orkiestrator dostarcza zawsze **dwa elementy**:

1. **Szczegółowy plik planu:** `plan_vXX_<krotki_temat>.md` (np. `plan_v17_...md`).

2. **Krótki prompt startowy** do bezpośredniego wklejenia w Antigravity.

**Obowiązkowa struktura pliku `plan_vXX_<temat>.md`:**

* **Tabela podjętych decyzji architektonicznych** (zamknięte rozstrzygnięcia, bez otwartych pytań).

* **Szczegółowe kroki wdrożenia per plik** (dokładna logika, sygnatury, parametry, ochrona przed regresją).

* **Zasada „Zero działania na ślepo” (`QUESTIONS_VXX.md`):** w razie realnej niejasności lub konfliktu w kodzie agent nie zgaduje — realizuje pewne części, a pytania (kontekst + opcje A/B) zapisuje w `QUESTIONS_VXX.md` w katalogu głównym.

* **Obowiązkowa weryfikacja i testy:** utrzymanie wszystkich dotychczasowych testów + nowe testy jednostkowe dla każdej zmiany (`pytest -v tests/` musi przejść w **100%**), a przy zmianach CV/OCR/strategii także weryfikacja regresyjna na `nagrania testowe/`.

* **Synchronizacja Git:** dopisanie raportu wersji na górze `PROGRESS_LOG.md`, czysty `git status` (bez `.mp4` i śmieci roboczych) oraz `git commit` + `git push origin main`.

### Tryb B — Mały hotfix

Dla punktowych poprawek (1–2 pliki, oczywisty błąd) wystarczy sam **precyzyjny prompt startowy** do wklejenia bezpośrednio w Antigravity (z wymogiem testu regresyjnego, aktualizacji `PROGRESS_LOG.md` i `git push`).

## 4. Źródło prawdy i higiena repozytorium

* **Jedyne źródło prawdy:** gałąź `main` repozytorium Git (`constitution.md`, kod źródłowy, `PROGRESS_LOG.md`, `tests/`).

* **Żelazne inwarianty (`constitution.md`):** 100% pasywny odczyt z ekranu, *Human-in-the-Loop* (zakaz symulacji kliknięć), 100% lokalne wykonanie (brak API/LLM w pętli czasu rzeczywistego), bilans 900 żetonów, budżet latencji `< 0,3 s` (z buforem `DecisionLock`).

* **Ochrona przed regresją:** żadna wersja nie jest uznana za ukończoną bez 100% zielonego `pytest -v tests/`.

## 5. Parking tematów otwartych (do wywołania przez Właściciela)

* **Priorytet na V17+:** otwarty, inicjuje Właściciel.

* **Baza GTOpen (`tools/run_gtopen_overnight.py` + `main.py`):** weryfikacja zakresów `SPOTS_CONFIG` (obecnie 100% vs 100% dla wszystkich 4 spotów) oraz mapowania `spot` / `facing_bet` w `lookup_nearest_flop`.

* **ICM i tabela wypłat Stake JAQKpot!:** status nieustalony (obecnie w kodzie próg `50x` po V15.1; niski priorytet, nie ruszamy bez dyspozycji Właściciela).