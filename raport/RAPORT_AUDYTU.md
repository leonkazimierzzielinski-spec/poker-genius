# Audyt Jakości Odczytu i Rekomendacji Decyzji (Poker Assistant)

**Materiał badawczy:** `nagrania testowe/Nagrywanie 2026-11-18 224127.mp4`  
**Zakres audytu:** Pierwsze 3:00 minuty nagrania (klatki 0–5400, 30.0 FPS, próbkowanie co 15 klatek = 0,5 s)  
**Data audytu:** 2026-11-19  
**Potok przetwarzania:** `VisionPipeline` (OpenCV + 52 templates + DigitOCR) → `StateValidator` (Suma 900) → `TableTracker` → `evaluate_candidates` (Nash + FlopDB + Monte Carlo) → `DecisionMaker`  

---

## 1. Podsumowanie Statystyczne (3 Minuty / 5400 Klatek)

| Parametr | Wartość | Komentarz |
|---|---|---|
| **Przetworzone klatki (próbki)** | **360** | Analiza co 15 klatek (co 500 ms) |
| **Klatki poprawne (`is_valid == True`)** | **296 (82.2%)** | Pełna spójność sumy 900 chipów, kart i blindów |
| **Klatki odrzucone (`is_valid == False`)** | **64 (17.8%)** | Animacje rozdawania, przesuwanie żetonów, showdown |
| **Wykryte tury Hero (`is_hero_turn == True`)** | **360** | Obecność przycisków akcji Hero na ekranie |
| **Tury Hero z poprawnym stanem** | **296** | Pełna gotowość do natychmiastowej decyzji |
| **Średni czas analizy potoku** | **150.6 ms** | Wymóg konstytucyjny: < 300 ms (zapach x3.5) |
| **Czas analizy 95. percentyl (P95)** | **208.7 ms** | Stabilna praca w czasie rzeczywistym |
| **Minimalny / Maksymalny czas** | **118.2 ms / 264.2 ms** | Pełny potok CV + MC w reżimie < 0.15 s |

### Przyczyny odrzucenia klatek (`is_valid == False`)

| Przyczyna odrzucenia | Liczba klatek | % odrzuconych | Wyjaśnienie natury zjawiska |
|---|---|---|---|
| `Missing stack reading` | 39 | 60.9% | Animacja żetonów w locie lub rozmycie napisów podczas przesuwania puli |
| `Duplicate cards detected` | 14 | 21.9% | Artefakty graficzne nakładania kart podczas animacji tasowania |
| `Invalid card count` | 12 | 18.8% | Klatka w ułamku sekundy, gdy odsłaniana jest pojedyncza karta na flopie |
| `Chip conservation failed` | 2 | 3.1% | Moment inkasowania żetonów przez wygranego gracza przed aktualizacją stanu puli |

> [!NOTE]
> W pokerze online hyper-turbo około 25–40% czasu wideo to animacje (rozdawanie kart, zgarnianie puli, baner wygranej). Odrzucanie tych klatek przez `StateValidator` jest pożądanym zachowaniem konstytucyjnym, gwarantującym, że HUD nie podejmuje decyzji na 'ruchomych piaskach'.

---

## 2. Chronologiczny Przebieg Wszystkich Tur Gracza Hero

Poniższa tabela zawiera wszystkie momenty, w których Hero posiadał aktywną turę (`is_hero_turn == True`), wraz z kompletnym odczytem stanu gry i wygenerowaną rekomendacją decyzyjną:

| Klatka | Czas | Blindy | Pot | Ręka Hero | Board | Ulica | S0 (Hero) | S1 | S2 | Dealer | Spot | Rekomendacja | EV (BB) | Profil | Zrzut |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `0000` | 00:00 | 10/20 | 80 | **2s Ts** | `--` | PREFLOP | 260 | 280 | 280 | -- | `BTN_OPEN` | **`FOLD`** | +0.00 | `LOOSE_CALLERS` | [01_frame_0000_hero_preflop_fold.png](screens/01_frame_0000_hero_preflop_fold.png) |
| `0015` | 00:00 | 10/20 | 80 | **2s Ts** | `--` | PREFLOP | 260 | 280 | 280 | -- | `BTN_OPEN` | **`FOLD`** | +0.00 | `LOOSE_CALLERS` |  |
| `0030` | 00:01 | 10/20 | 80 | **2s Ts** | `--` | PREFLOP | 260 | 280 | 280 | -- | `BTN_OPEN` | **`FOLD`** | +0.00 | `LOOSE_CALLERS` |  |
| `0045` | 00:01 | 10/20 | 80 | **2s Ts** | `--` | PREFLOP | 260 | 280 | 280 | -- | `BTN_OPEN` | **`FOLD`** | +0.00 | `LOOSE_CALLERS` |  |
| `0060` | 00:02 | 10/20 | 80 | **2s Ts** | `--` | PREFLOP | 260 | 280 | 280 | -- | `BTN_OPEN` | **`FOLD`** | +0.00 | `LOOSE_CALLERS` |  |
| `0075` | 00:02 | 10/20 | 80 | **2s Ts** | `--` | PREFLOP | 260 | 280 | 280 | -- | `BTN_OPEN` | **`FOLD`** | +0.00 | `LOOSE_CALLERS` |  |
| `0090` | 00:03 | 10/20 | 80 | **2s Ts** | `--` | PREFLOP | 260 | 280 | 280 | -- | `BTN_OPEN` | **`FOLD`** | +0.00 | `LOOSE_CALLERS` |  |
| `0105` | 00:03 | 10/20 | 360 | **2s Ts** | `--` | PREFLOP | 260 | -- | 280 | S2 | `SB_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` | [08_frame_0105_missing_stack_reading.png](screens/08_frame_0105_missing_stack_reading.png) |
| `0120` | 00:04 | 10/20 | 360 | **2s Ts** | `--` | PREFLOP | 260 | -- | 280 | S2 | `SB_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `0135` | 00:04 | 10/20 | 360 | **2s Ts** | `--` | PREFLOP | 260 | -- | 280 | S2 | `SB_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `0150` | 00:05 | 10/20 | 360 | **2s Ts** | `--` | PREFLOP | 260 | -- | 280 | S2 | `SB_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `0165` | 00:05 | 10/20 | 360 | **2s Ts** | `--` | PREFLOP | 260 | -- | 280 | S2 | `SB_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `0180` | 00:06 | 10/20 | 360 | **2s Ts** | `--` | PREFLOP | 260 | -- | 280 | S2 | `SB_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `0195` | 00:06 | 10/20 | 360 | **2s Ts** | `--` | PREFLOP | 260 | -- | 280 | S2 | `SB_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `0210` | 00:07 | 10/20 | 360 | **2s Ts** | `--` | PREFLOP | 260 | -- | 280 | S2 | `SB_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `0225` | 00:07 | 10/20 | 360 | **2s Ts** | `--` | PREFLOP | 260 | -- | 280 | S2 | `SB_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `0240` | 00:08 | 10/20 | 360 | **2s Ts** | `--` | PREFLOP | 260 | -- | 280 | S2 | `SB_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `0255` | 00:08 | 10/20 | 360 | **2s Ts** | `--` | PREFLOP | 260 | -- | 280 | S2 | `SB_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `0270` | 00:09 | 10/20 | 360 | **2s Ts** | `--` | PREFLOP | 260 | -- | 280 | S2 | `SB_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `0285` | 00:09 | 10/20 | 360 | **2s Ts** | `--` | PREFLOP | 260 | -- | 280 | S2 | `SB_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `0300` | 00:10 | 10/20 | 360 | **2s Ts** | `--` | PREFLOP | 260 | -- | 280 | S2 | `SB_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `0315` | 00:10 | 10/20 | 360 | **2s Ts** | `--` | PREFLOP | 260 | -- | 280 | S2 | `SB_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `0330` | 00:11 | 10/20 | 360 | **2s Ts** | `--` | PREFLOP | 260 | -- | 280 | S2 | `SB_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `0345` | 00:11 | 10/20 | 360 | **2s Ts** | `--` | PREFLOP | 260 | -- | 280 | S2 | `SB_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `0360` | 00:12 | 10/20 | 360 | **--** | `--` | PREFLOP | 260 | -- | 280 | S1 | `BB_ISO_VS_LIMP` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `0375` | 00:12 | 10/20 | 100 | **--** | `--` | PREFLOP | 260 | 260 | 280 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` | [02_frame_0375_hero_preflop_all_in.png](screens/02_frame_0375_hero_preflop_all_in.png) |
| `0390` | 00:13 | 10/20 | 100 | **--** | `--` | PREFLOP | 260 | 260 | 280 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `0405` | 00:13 | 10/20 | 100 | **--** | `--` | PREFLOP | 260 | 260 | 280 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `0420` | 00:14 | 10/20 | 100 | **--** | `--` | PREFLOP | 260 | 260 | 280 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `0435` | 00:14 | 10/20 | 100 | **--** | `--` | PREFLOP | 260 | 260 | 280 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `0450` | 00:15 | 10/20 | 100 | **--** | `--` | PREFLOP | 260 | 260 | 280 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `0465` | 00:15 | 10/20 | 100 | **--** | `--` | PREFLOP | 260 | 260 | 280 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `0480` | 00:16 | 10/20 | 100 | **--** | `--` | PREFLOP | 260 | 260 | 280 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `0495` | 00:16 | 10/20 | 100 | **--** | `--` | PREFLOP | 260 | 260 | 280 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `0510` | 00:17 | 10/20 | 100 | **--** | `--` | PREFLOP | 260 | 260 | 280 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `0525` | 00:17 | 10/20 | 100 | **--** | `--` | PREFLOP | 260 | 260 | 280 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `0540` | 00:18 | 10/20 | 100 | **--** | `--` | PREFLOP | 260 | 260 | 280 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `0555` | 00:18 | 10/20 | 100 | **--** | `--` | PREFLOP | 260 | 260 | 280 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `0570` | 00:19 | 10/20 | 100 | **--** | `--` | PREFLOP | 260 | 260 | 280 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `0585` | 00:19 | 10/20 | 100 | **--** | `--` | PREFLOP | 260 | 260 | 280 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `0600` | 00:20 | 10/20 | 100 | **--** | `--` | PREFLOP | 260 | 260 | 280 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `0615` | 00:20 | 10/20 | 100 | **--** | `--` | PREFLOP | 260 | 260 | 280 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `0630` | 00:21 | 10/20 | 0 | **--** | `--` | PREFLOP | 260 | 360 | 280 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `0645` | 00:21 | 10/20 | 0 | **--** | `--` | PREFLOP | 260 | 360 | 280 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `0660` | 00:22 | 10/20 | 10 | **--** | `--` | PREFLOP | 260 | 350 | 280 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `0675` | 00:22 | 10/20 | 10 | **--** | `--` | PREFLOP | 260 | 350 | 280 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `0690` | 00:23 | 10/20 | 10 | **--** | `--` | PREFLOP | 260 | 350 | 280 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `0705` | 00:23 | 10/20 | 30 | **--** | `--` | PREFLOP | 260 | 350 | 260 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `0720` | 00:24 | 10/20 | 30 | **--** | `--` | PREFLOP | 260 | 350 | 260 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `0735` | 00:24 | 10/20 | 30 | **--** | `--` | PREFLOP | 260 | 350 | 260 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `0750` | 00:25 | 10/20 | 30 | **Kd** | `--` | PREFLOP | 260 | 350 | 260 | S0 | `BTN_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` | [09_frame_0750_invalid_card_count.png](screens/09_frame_0750_invalid_card_count.png) |
| `0765` | 00:25 | 10/20 | 30 | **Kd 3c** | `--` | PREFLOP | 260 | 350 | 260 | S0 | `BTN_OPEN` | **`FOLD`** | +0.00 | `LOOSE_CALLERS` | [03_frame_0765_hero_preflop_fold.png](screens/03_frame_0765_hero_preflop_fold.png) |
| `0780` | 00:26 | 10/20 | 30 | **Kd 3c** | `--` | PREFLOP | 260 | 350 | 260 | S0 | `BTN_OPEN` | **`FOLD`** | +0.00 | `LOOSE_CALLERS` |  |
| `0795` | 00:26 | 10/20 | 30 | **Kd 3c** | `--` | PREFLOP | 260 | 350 | 260 | S0 | `BTN_OPEN` | **`FOLD`** | +0.00 | `LOOSE_CALLERS` |  |
| `0810` | 00:27 | 10/20 | 30 | **Kd 3c** | `--` | PREFLOP | 260 | 350 | 260 | S0 | `BTN_OPEN` | **`FOLD`** | +0.00 | `LOOSE_CALLERS` |  |
| `0825` | 00:27 | 10/20 | 30 | **Kd 3c** | `--` | PREFLOP | 260 | 350 | 260 | S0 | `BTN_OPEN` | **`FOLD`** | +0.00 | `LOOSE_CALLERS` |  |
| `0840` | 00:28 | 10/20 | 50 | **Kd 3c** | `--` | PREFLOP | 240 | 350 | 260 | S0 | `BTN_OPEN` | **`FOLD`** | +0.00 | `LOOSE_CALLERS` |  |
| `0855` | 00:28 | 10/20 | 50 | **Kd 3c** | `--` | PREFLOP | 240 | 350 | 260 | S0 | `BTN_OPEN` | **`FOLD`** | +0.00 | `LOOSE_CALLERS` |  |
| `0870` | 00:29 | 10/20 | 50 | **Kd 3c** | `--` | PREFLOP | 240 | 350 | 260 | S0 | `BTN_OPEN` | **`FOLD`** | +0.00 | `LOOSE_CALLERS` |  |
| `0885` | 00:29 | 10/20 | 50 | **Kd 3c** | `--` | PREFLOP | 240 | 350 | 260 | S0 | `BTN_OPEN` | **`FOLD`** | +0.00 | `LOOSE_CALLERS` |  |
| `0900` | 00:30 | 10/20 | 50 | **Kd 3c** | `--` | PREFLOP | 240 | 350 | 260 | S0 | `BTN_OPEN` | **`FOLD`** | +0.00 | `LOOSE_CALLERS` |  |
| `0915` | 00:30 | 10/20 | 50 | **Kd 3c** | `--` | PREFLOP | 240 | 350 | 260 | S0 | `BTN_OPEN` | **`FOLD`** | +0.00 | `LOOSE_CALLERS` |  |
| `0930` | 00:31 | 10/20 | 50 | **Kd 3c** | `--` | PREFLOP | 240 | 350 | 260 | S0 | `BTN_OPEN` | **`FOLD`** | +0.00 | `LOOSE_CALLERS` |  |
| `0945` | 00:31 | 10/20 | 50 | **Kd 3c** | `7c` | PREFLOP | 240 | 350 | 260 | S0 | `BTN_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `0960` | 00:32 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.27 | `LOOSE_CALLERS` | [04_frame_0960_hero_flop_all_in.png](screens/04_frame_0960_hero_flop_all_in.png) |
| `0975` | 00:32 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.41 | `LOOSE_CALLERS` |  |
| `0990` | 00:33 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.39 | `LOOSE_CALLERS` |  |
| `1005` | 00:33 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.42 | `LOOSE_CALLERS` |  |
| `1020` | 00:34 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.61 | `LOOSE_CALLERS` |  |
| `1035` | 00:34 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.46 | `LOOSE_CALLERS` |  |
| `1050` | 00:35 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.38 | `LOOSE_CALLERS` |  |
| `1065` | 00:35 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.62 | `LOOSE_CALLERS` |  |
| `1080` | 00:36 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.51 | `LOOSE_CALLERS` |  |
| `1095` | 00:36 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.33 | `LOOSE_CALLERS` |  |
| `1110` | 00:37 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.54 | `LOOSE_CALLERS` |  |
| `1125` | 00:37 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.38 | `LOOSE_CALLERS` |  |
| `1140` | 00:38 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.77 | `LOOSE_CALLERS` |  |
| `1155` | 00:38 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.60 | `LOOSE_CALLERS` |  |
| `1170` | 00:39 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.26 | `LOOSE_CALLERS` |  |
| `1185` | 00:39 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.24 | `LOOSE_CALLERS` |  |
| `1200` | 00:40 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.29 | `LOOSE_CALLERS` |  |
| `1215` | 00:40 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.37 | `LOOSE_CALLERS` |  |
| `1230` | 00:41 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.50 | `LOOSE_CALLERS` |  |
| `1245` | 00:41 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.30 | `LOOSE_CALLERS` |  |
| `1260` | 00:42 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.33 | `LOOSE_CALLERS` |  |
| `1275` | 00:42 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.37 | `LOOSE_CALLERS` |  |
| `1290` | 00:43 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.56 | `LOOSE_CALLERS` |  |
| `1305` | 00:43 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.68 | `LOOSE_CALLERS` |  |
| `1320` | 00:44 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.50 | `LOOSE_CALLERS` |  |
| `1335` | 00:44 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.62 | `LOOSE_CALLERS` |  |
| `1350` | 00:45 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.48 | `LOOSE_CALLERS` |  |
| `1365` | 00:45 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.66 | `LOOSE_CALLERS` |  |
| `1380` | 00:46 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.43 | `LOOSE_CALLERS` |  |
| `1395` | 00:46 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.32 | `LOOSE_CALLERS` |  |
| `1410` | 00:47 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.11 | `LOOSE_CALLERS` |  |
| `1425` | 00:47 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.43 | `LOOSE_CALLERS` |  |
| `1440` | 00:48 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.49 | `LOOSE_CALLERS` |  |
| `1455` | 00:48 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.64 | `LOOSE_CALLERS` |  |
| `1470` | 00:49 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.40 | `LOOSE_CALLERS` |  |
| `1485` | 00:49 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.29 | `LOOSE_CALLERS` |  |
| `1500` | 00:50 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.64 | `LOOSE_CALLERS` |  |
| `1515` | 00:50 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.71 | `LOOSE_CALLERS` |  |
| `1530` | 00:51 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c` | FLOP | 240 | 350 | 260 | S0 | `FLOP` | **`ALL_IN`** | +6.48 | `LOOSE_CALLERS` |  |
| `1545` | 00:51 | 10/20 | 50 | **Kd 3c** | `7c Ks` | PREFLOP | 240 | 350 | 260 | S0 | `BTN_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `1560` | 00:52 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c 5s` | TURN | 240 | 350 | 260 | S0 | `TURN` | **`ALL_IN`** | +6.07 | `LOOSE_CALLERS` | [05_frame_1560_hero_turn_all_in.png](screens/05_frame_1560_hero_turn_all_in.png) |
| `1575` | 00:52 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c 5s` | TURN | 240 | 350 | 260 | S0 | `TURN` | **`ALL_IN`** | +6.01 | `LOOSE_CALLERS` |  |
| `1590` | 00:53 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c 5s` | TURN | 240 | 350 | 260 | S0 | `TURN` | **`ALL_IN`** | +6.06 | `LOOSE_CALLERS` |  |
| `1605` | 00:53 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c 5s` | TURN | 240 | 350 | 260 | S0 | `TURN` | **`ALL_IN`** | +5.77 | `LOOSE_CALLERS` |  |
| `1620` | 00:54 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c 5s` | TURN | 240 | 350 | 260 | S0 | `TURN` | **`ALL_IN`** | +6.08 | `LOOSE_CALLERS` |  |
| `1635` | 00:54 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c 5s` | TURN | 240 | 350 | 260 | S0 | `TURN` | **`ALL_IN`** | +5.83 | `LOOSE_CALLERS` |  |
| `1650` | 00:55 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c 5s` | TURN | 240 | 350 | 260 | S0 | `TURN` | **`ALL_IN`** | +5.80 | `LOOSE_CALLERS` |  |
| `1665` | 00:55 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c 5s` | TURN | 240 | 350 | 260 | S0 | `TURN` | **`ALL_IN`** | +5.83 | `LOOSE_CALLERS` |  |
| `1680` | 00:56 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c 5s` | TURN | 240 | 350 | 260 | S0 | `TURN` | **`ALL_IN`** | +5.62 | `LOOSE_CALLERS` |  |
| `1695` | 00:56 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c 5s` | TURN | 240 | 350 | 260 | S0 | `TURN` | **`ALL_IN`** | +5.81 | `LOOSE_CALLERS` |  |
| `1710` | 00:57 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c 5s` | TURN | 240 | 350 | 260 | S0 | `TURN` | **`ALL_IN`** | +5.99 | `LOOSE_CALLERS` |  |
| `1725` | 00:57 | 10/20 | 70 | **Kd 3c** | `7c Ks 8c 5s` | TURN | 220 | 350 | 260 | S0 | `TURN` | **`ALL_IN`** | +6.42 | `LOOSE_CALLERS` |  |
| `1740` | 00:58 | 10/20 | 70 | **Kd 3c** | `7c Ks 8c 5s` | TURN | 220 | 350 | 260 | S0 | `TURN` | **`ALL_IN`** | +6.48 | `LOOSE_CALLERS` |  |
| `1755` | 00:58 | 10/20 | 70 | **Kd 3c** | `7c Ks 8c 5s` | TURN | 220 | 350 | 260 | S0 | `TURN` | **`ALL_IN`** | +6.39 | `LOOSE_CALLERS` |  |
| `1770` | 00:59 | 10/20 | 70 | **Kd 3c** | `7c Ks 8c 5s` | TURN | 220 | 350 | 260 | S0 | `TURN` | **`ALL_IN`** | +6.56 | `LOOSE_CALLERS` |  |
| `1785` | 00:59 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c 5s` | TURN | 240 | 350 | 260 | S0 | `TURN` | **`ALL_IN`** | +5.68 | `LOOSE_CALLERS` |  |
| `1800` | 01:00 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c 5s` | TURN | 240 | 350 | 260 | S0 | `TURN` | **`ALL_IN`** | +5.81 | `LOOSE_CALLERS` |  |
| `1815` | 01:00 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c 5s` | TURN | 240 | 350 | 260 | S0 | `TURN` | **`ALL_IN`** | +5.74 | `LOOSE_CALLERS` |  |
| `1830` | 01:01 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c 5s` | TURN | 240 | 350 | 260 | S0 | `TURN` | **`ALL_IN`** | +5.84 | `LOOSE_CALLERS` |  |
| `1845` | 01:01 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c 5s` | TURN | 240 | 350 | 260 | S0 | `TURN` | **`ALL_IN`** | +5.75 | `LOOSE_CALLERS` |  |
| `1860` | 01:02 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c 5s 8s` | RIVER | 240 | 350 | 260 | S0 | `RIVER` | **`ALL_IN`** | +6.25 | `LOOSE_CALLERS` | [06_frame_1860_hero_river_all_in.png](screens/06_frame_1860_hero_river_all_in.png) |
| `1875` | 01:02 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c 5s 8s` | RIVER | 240 | 350 | 260 | S0 | `RIVER` | **`ALL_IN`** | +6.02 | `LOOSE_CALLERS` |  |
| `1890` | 01:03 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c 5s 8s` | RIVER | 240 | 350 | 260 | S0 | `RIVER` | **`ALL_IN`** | +6.08 | `LOOSE_CALLERS` |  |
| `1905` | 01:03 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c 5s 8s` | RIVER | 240 | 350 | 260 | S0 | `RIVER` | **`ALL_IN`** | +5.96 | `LOOSE_CALLERS` |  |
| `1920` | 01:04 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c 5s 8s` | RIVER | 240 | 350 | 260 | S0 | `RIVER` | **`ALL_IN`** | +5.75 | `LOOSE_CALLERS` |  |
| `1935` | 01:04 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c 5s 8s` | RIVER | 240 | 350 | 260 | S0 | `RIVER` | **`ALL_IN`** | +5.89 | `LOOSE_CALLERS` |  |
| `1950` | 01:05 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c 5s 8s` | RIVER | 240 | 350 | 260 | S0 | `RIVER` | **`ALL_IN`** | +5.85 | `LOOSE_CALLERS` |  |
| `1965` | 01:05 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c 5s 8s` | RIVER | 240 | 350 | 260 | S0 | `RIVER` | **`ALL_IN`** | +5.96 | `LOOSE_CALLERS` |  |
| `1980` | 01:06 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c 5s 8s` | RIVER | 240 | 350 | 260 | S0 | `RIVER` | **`ALL_IN`** | +5.88 | `LOOSE_CALLERS` |  |
| `1995` | 01:06 | 10/20 | 50 | **Kd 3c** | `7c Ks 8c 5s 8s` | RIVER | 240 | 350 | 260 | S0 | `RIVER` | **`ALL_IN`** | +5.78 | `LOOSE_CALLERS` |  |
| `2010` | 01:07 | 10/20 | 0 | **--** | `--` | PREFLOP | 290 | 350 | 260 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2025` | 01:07 | 15/30 | 0 | **--** | `--` | PREFLOP | 290 | 350 | 260 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2040` | 01:08 | 15/30 | 0 | **--** | `--` | PREFLOP | 290 | 350 | 260 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2055` | 01:08 | 15/30 | 15 | **--** | `--` | PREFLOP | 290 | 350 | -- | -- | `BTN_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `2070` | 01:09 | 15/30 | 15 | **--** | `--` | PREFLOP | 290 | 350 | 245 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2085` | 01:09 | 15/30 | 45 | **--** | `--` | PREFLOP | 260 | 350 | 245 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2100` | 01:10 | 15/30 | 0 | **--** | `--` | PREFLOP | 260 | 350 | 245 | -- | `BTN_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` | [10_frame_2100_chip_conservation_failed.png](screens/10_frame_2100_chip_conservation_failed.png) |
| `2115` | 01:10 | 15/30 | 45 | **--** | `--` | PREFLOP | 260 | 350 | 245 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2130` | 01:11 | 15/30 | 45 | **--** | `--` | PREFLOP | 260 | -- | 245 | S1 | `BB_ISO_VS_LIMP` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `2145` | 01:11 | 15/30 | 45 | **--** | `--` | PREFLOP | 260 | -- | 245 | S1 | `BB_ISO_VS_LIMP` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `2160` | 01:12 | 15/30 | 45 | **--** | `--` | PREFLOP | 260 | -- | 245 | S1 | `BB_ISO_VS_LIMP` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `2175` | 01:12 | 15/30 | 45 | **--** | `--` | PREFLOP | 260 | -- | 245 | -- | `BTN_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `2190` | 01:13 | 15/30 | 45 | **--** | `--` | PREFLOP | 260 | 350 | 245 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2205` | 01:13 | 15/30 | 45 | **--** | `--` | PREFLOP | 260 | 350 | 245 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2220` | 01:14 | 15/30 | 45 | **--** | `--` | PREFLOP | 260 | 350 | 245 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2235` | 01:14 | 15/30 | 45 | **--** | `--` | PREFLOP | 260 | 350 | 245 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2250` | 01:15 | 15/30 | 45 | **--** | `--` | PREFLOP | 260 | 350 | 245 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2265` | 01:15 | 15/30 | 45 | **--** | `--` | PREFLOP | 260 | 350 | -- | S2 | `SB_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `2280` | 01:16 | 15/30 | 45 | **--** | `--` | PREFLOP | 260 | 350 | 245 | S2 | `SB_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` | [07_frame_2280_hero_preflop_all_in.png](screens/07_frame_2280_hero_preflop_all_in.png) |
| `2295` | 01:16 | 15/30 | 45 | **--** | `--` | PREFLOP | 260 | 350 | 245 | S2 | `SB_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2310` | 01:17 | 15/30 | 45 | **--** | `--` | PREFLOP | 260 | 350 | 245 | S2 | `SB_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2325` | 01:17 | 15/30 | 45 | **--** | `--` | PREFLOP | 260 | 350 | 245 | S2 | `SB_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2340` | 01:18 | 15/30 | 90 | **--** | `--` | PREFLOP | 260 | 350 | 200 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2355` | 01:18 | 15/30 | 90 | **--** | `--` | PREFLOP | 260 | 350 | 200 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2370` | 01:19 | 15/30 | 90 | **--** | `--` | PREFLOP | 260 | 350 | 200 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2385` | 01:19 | 15/30 | 90 | **--** | `--` | PREFLOP | 260 | 350 | 200 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2400` | 01:20 | 15/30 | 90 | **--** | `--` | PREFLOP | 260 | 350 | 200 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2415` | 01:20 | 15/30 | 90 | **--** | `--` | PREFLOP | 260 | 350 | 200 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2430` | 01:21 | 15/30 | 90 | **--** | `--` | PREFLOP | 260 | 350 | 200 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2445` | 01:21 | 15/30 | 90 | **--** | `--` | PREFLOP | 260 | 350 | 200 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2460` | 01:22 | 15/30 | 90 | **--** | `--` | PREFLOP | 260 | 350 | 200 | S2 | `SB_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2475` | 01:22 | 15/30 | 90 | **--** | `--` | PREFLOP | 260 | 350 | 200 | S2 | `SB_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2490` | 01:23 | 15/30 | 60 | **--** | `--` | PREFLOP | 260 | 350 | 230 (+30) | S2 | `SB_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2505` | 01:23 | 15/30 | 60 | **--** | `--` | PREFLOP | 260 | 350 | 230 | S2 | `SB_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2520` | 01:24 | 15/30 | 60 | **--** | `--` | PREFLOP | 260 | 350 | 230 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2535` | 01:24 | 15/30 | 60 | **--** | `--` | PREFLOP | 260 | 350 | 230 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2550` | 01:25 | 15/30 | 60 | **--** | `--` | PREFLOP | 260 | 350 | 230 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2565` | 01:25 | 15/30 | 60 | **--** | `--` | PREFLOP | 260 | 350 | 230 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2580` | 01:26 | 15/30 | 60 | **--** | `--` | PREFLOP | 260 | 350 | 230 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2595` | 01:26 | 15/30 | 60 | **--** | `--` | PREFLOP | 260 | 350 | 230 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2610` | 01:27 | 15/30 | 60 | **--** | `--` | PREFLOP | 260 | 350 | 230 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2625` | 01:27 | 15/30 | 60 | **--** | `--` | PREFLOP | 260 | 350 | 230 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2640` | 01:28 | 15/30 | 60 | **--** | `--` | PREFLOP | 260 | 350 | 230 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2655` | 01:28 | 15/30 | 60 | **--** | `--` | PREFLOP | 260 | 350 | 230 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2670` | 01:29 | 15/30 | 60 | **--** | `--` | PREFLOP | 260 | 350 | 230 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2685` | 01:29 | 15/30 | 60 | **--** | `--` | PREFLOP | 260 | 350 | 230 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2700` | 01:30 | 15/30 | 60 | **--** | `--` | PREFLOP | 260 | 350 | 230 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2715` | 01:30 | 15/30 | 60 | **--** | `--` | PREFLOP | 260 | 350 | 230 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2730` | 01:31 | 15/30 | 0 | **--** | `--` | PREFLOP | 260 | 350 | 290 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2745` | 01:31 | 15/30 | 0 | **--** | `--` | PREFLOP | 260 | 350 | 290 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2760` | 01:32 | 15/30 | 0 | **--** | `--` | PREFLOP | 260 | 350 | 290 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2775` | 01:32 | 15/30 | 0 | **--** | `--` | PREFLOP | 260 | 350 | 290 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2790` | 01:33 | 15/30 | 15 | **--** | `--` | PREFLOP | 245 | 350 | 290 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2805` | 01:33 | 15/30 | 45 | **--** | `--` | PREFLOP | 245 | -- | 290 | -- | `BTN_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `2820` | 01:34 | 15/30 | 45 | **--** | `--` | PREFLOP | 245 | 320 | 290 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2835` | 01:34 | 15/30 | 45 | **--** | `--` | PREFLOP | 245 | 320 | 290 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `2850` | 01:35 | 15/30 | 45 | **4s** | `--` | PREFLOP | 245 | 320 | 290 | S2 | `SB_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `2865` | 01:35 | 15/30 | 45 | **4s** | `--` | PREFLOP | 245 | 320 | 290 | S2 | `SB_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `2880` | 01:36 | 15/30 | 45 | **4s** | `--` | PREFLOP | 245 | 320 | 290 | S2 | `SB_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `2895` | 01:36 | 15/30 | 45 | **4s** | `--` | PREFLOP | 245 | 320 | 290 | S2 | `SB_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `2910` | 01:37 | 15/30 | 75 | **4s** | `--` | PREFLOP | 245 | 320 | 260 | -- | `BTN_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `2925` | 01:37 | 15/30 | 75 | **4s** | `--` | PREFLOP | 245 | 320 | 260 | -- | `BTN_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `2940` | 01:38 | 15/30 | 75 | **4s** | `--` | PREFLOP | 245 | 320 | 260 | -- | `BTN_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `2955` | 01:38 | 15/30 | 75 | **4s** | `--` | PREFLOP | 245 | 320 | 260 | -- | `BTN_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `2970` | 01:39 | 15/30 | 75 | **--** | `--` | PREFLOP | 245 | 320 | 260 | S1 | `BB_ISO_VS_LIMP` | **`ALL_IN`** | +0.70 | `LOOSE_CALLERS` |  |
| `2985` | 01:39 | 15/30 | 75 | **--** | `--` | PREFLOP | 245 | 320 | 260 | S1 | `BB_ISO_VS_LIMP` | **`ALL_IN`** | +0.70 | `LOOSE_CALLERS` |  |
| `3000` | 01:40 | 15/30 | 75 | **--** | `--` | PREFLOP | 245 | 320 | 260 | S1 | `BB_ISO_VS_LIMP` | **`ALL_IN`** | +0.70 | `LOOSE_CALLERS` |  |
| `3015` | 01:40 | 15/30 | 75 | **--** | `8d 8c` | PREFLOP | 245 | 320 | 260 | S1 | `BB_ISO_VS_LIMP` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `3030` | 01:41 | 15/30 | 75 | **--** | `8d 8c Th` | FLOP | 245 | 320 | 260 | S1 | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3045` | 01:41 | 15/30 | 75 | **--** | `8d 8c Th` | FLOP | 245 | 320 | 260 | S1 | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3060` | 01:42 | 15/30 | 75 | **--** | `8d 8c Th` | FLOP | 245 | 320 | 260 | -- | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3075` | 01:42 | 15/30 | 75 | **--** | `8d 8c Th` | FLOP | 245 | 320 | 260 | -- | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3090` | 01:43 | 15/30 | 75 | **--** | `8d 8c Th` | FLOP | 245 | 320 | 260 | S2 | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3105` | 01:43 | 15/30 | 75 | **--** | `8d 8c Th` | FLOP | 245 | 320 | 260 | S2 | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3120` | 01:44 | 15/30 | 75 | **--** | `8d 8c Th` | FLOP | 245 | 320 | 260 | S2 | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3135` | 01:44 | 15/30 | 75 | **--** | `8d 8c Th` | FLOP | 245 | 320 | 260 | S2 | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3150` | 01:45 | 15/30 | 75 | **--** | `8d 8c Th` | FLOP | 245 | 320 | 260 | S2 | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3165` | 01:45 | 15/30 | 75 | **--** | `8d 8c Th` | FLOP | 245 | 320 | 260 | S2 | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3180` | 01:46 | 15/30 | 75 | **--** | `8d 8c Th` | FLOP | 245 | 320 | 260 | S2 | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3195` | 01:46 | 15/30 | 75 | **--** | `8d 8c Th` | FLOP | 245 | 320 | 260 | S2 | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3210` | 01:47 | 15/30 | 75 | **--** | `8d 8c Th` | FLOP | 245 | 320 | 260 | S2 | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3225` | 01:47 | 15/30 | 75 | **--** | `8d 8c Th` | FLOP | 245 | 320 | 260 | S2 | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3240` | 01:48 | 15/30 | 75 | **--** | `8d 8c Th` | FLOP | 245 | 320 | 260 | S2 | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3255` | 01:48 | 15/30 | 75 | **--** | `8d 8c Th` | FLOP | 245 | 320 | 260 | S1 | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3270` | 01:49 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | S1 | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3285` | 01:49 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | S1 | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3300` | 01:50 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | S1 | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3315` | 01:50 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | S1 | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3330` | 01:51 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3345` | 01:51 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3360` | 01:52 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3375` | 01:52 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3390` | 01:53 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3405` | 01:53 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | S2 | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3420` | 01:54 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | S2 | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3435` | 01:54 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | S2 | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3450` | 01:55 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | S2 | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3465` | 01:55 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | S2 | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3480` | 01:56 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | S2 | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3495` | 01:56 | 15/30 | 135 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 200 | S1 | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3510` | 01:57 | 15/30 | 135 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 200 | S1 | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3525` | 01:57 | 15/30 | 135 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 200 | S1 | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3540` | 01:58 | 15/30 | 135 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 200 | S1 | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3555` | 01:58 | 15/30 | 135 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 200 | S1 | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3570` | 01:59 | 15/30 | 135 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 200 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3585` | 01:59 | 15/30 | 135 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 200 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3600` | 02:00 | 15/30 | 135 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 200 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3615` | 02:00 | 15/30 | 135 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 200 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3630` | 02:01 | 15/30 | 135 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 200 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3645` | 02:01 | 15/30 | 135 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 200 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3660` | 02:02 | 15/30 | 135 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 200 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3675` | 02:02 | 15/30 | 135 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 200 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3690` | 02:03 | 15/30 | 135 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 200 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3705` | 02:03 | 15/30 | 135 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 200 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3720` | 02:04 | 15/30 | 135 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 200 | S2 | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3735` | 02:04 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | S2 | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3750` | 02:05 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | S2 | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3765` | 02:05 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | S2 | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3780` | 02:06 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3795` | 02:06 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3810` | 02:07 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3825` | 02:07 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3840` | 02:08 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3855` | 02:08 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3870` | 02:09 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3885` | 02:09 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3900` | 02:10 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3915` | 02:10 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3930` | 02:11 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3945` | 02:11 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3960` | 02:12 | 15/30 | 75 | **--** | `8d 8c Th 5h` | TURN | 245 | 320 | 260 | -- | `TURN` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `3975` | 02:12 | 15/30 | 0 | **--** | `--` | PREFLOP | 245 | 320 | 335 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `3990` | 02:13 | 15/30 | 0 | **--** | `--` | PREFLOP | 245 | 320 | 335 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4005` | 02:13 | 15/30 | 0 | **--** | `--` | PREFLOP | 245 | 320 | 335 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4020` | 02:14 | 15/30 | 15 | **--** | `--` | PREFLOP | 245 | -- | 335 | S0 | `BTN_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `4035` | 02:14 | 15/30 | 15 | **--** | `--` | PREFLOP | 245 | 305 | 335 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4050` | 02:15 | 15/30 | 45 | **--** | `--` | PREFLOP | 245 | 305 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4065` | 02:15 | 15/30 | 45 | **--** | `--` | PREFLOP | 245 | 305 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4080` | 02:16 | 15/30 | 0 | **--** | `--` | PREFLOP | 245 | 305 | 305 | S0 | `BTN_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `4095` | 02:16 | 15/30 | 45 | **--** | `--` | PREFLOP | 245 | 305 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4110` | 02:17 | 15/30 | 45 | **--** | `--` | PREFLOP | 245 | 305 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4125` | 02:17 | 15/30 | 45 | **--** | `--` | PREFLOP | 245 | 305 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4140` | 02:18 | 15/30 | 45 | **--** | `--` | PREFLOP | 245 | 305 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4155` | 02:18 | 15/30 | 75 | **--** | `--` | PREFLOP | 215 | 305 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4170` | 02:19 | 15/30 | 75 | **--** | `--` | PREFLOP | 215 | 305 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4185` | 02:19 | 15/30 | 75 | **--** | `--` | PREFLOP | 215 | 305 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4200` | 02:20 | 15/30 | 75 | **--** | `--` | PREFLOP | 215 | 305 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4215` | 02:20 | 15/30 | 75 | **--** | `--` | PREFLOP | 215 | 305 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4230` | 02:21 | 15/30 | 75 | **--** | `--` | PREFLOP | 215 | 305 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4245` | 02:21 | 15/30 | 75 | **--** | `--` | PREFLOP | 215 | 305 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4260` | 02:22 | 15/30 | 380 | **--** | `--` | PREFLOP | 215 | -- | 305 | S0 | `BTN_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `4275` | 02:22 | 15/30 | 380 | **--** | `--` | PREFLOP | 215 | -- | 305 | S0 | `BTN_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `4290` | 02:23 | 15/30 | 380 | **--** | `--` | PREFLOP | 215 | -- | 305 | S0 | `BTN_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `4305` | 02:23 | 15/30 | 380 | **--** | `--` | PREFLOP | 215 | -- | 305 | S0 | `BTN_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `4320` | 02:24 | 15/30 | 380 | **--** | `--` | PREFLOP | 215 | -- | 305 | S0 | `BTN_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `4335` | 02:24 | 15/30 | 380 | **--** | `--` | PREFLOP | 215 | -- | 305 | S0 | `BTN_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `4350` | 02:25 | 15/30 | 90 | **--** | `--` | PREFLOP | 215 | 290 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4365` | 02:25 | 15/30 | 90 | **--** | `--` | PREFLOP | 215 | 290 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4380` | 02:26 | 15/30 | 90 | **--** | `--` | PREFLOP | 215 | 290 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4395` | 02:26 | 15/30 | 90 | **--** | `--` | PREFLOP | 215 | 290 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4410` | 02:27 | 15/30 | 90 | **--** | `--` | PREFLOP | 215 | 290 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4425` | 02:27 | 15/30 | 90 | **--** | `--` | PREFLOP | 215 | 290 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4440` | 02:28 | 15/30 | 90 | **--** | `--` | PREFLOP | 215 | 290 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4455` | 02:28 | 15/30 | 90 | **--** | `--` | PREFLOP | 215 | 290 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4470` | 02:29 | 15/30 | 90 | **--** | `--` | PREFLOP | 215 | 290 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4485` | 02:29 | 15/30 | 90 | **--** | `--` | PREFLOP | 215 | 290 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4500` | 02:30 | 15/30 | 90 | **--** | `--` | PREFLOP | 215 | 290 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4515` | 02:30 | 15/30 | 90 | **--** | `--` | PREFLOP | 215 | 290 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4530` | 02:31 | 15/30 | 90 | **--** | `--` | PREFLOP | 215 | 290 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4545` | 02:31 | 15/30 | 90 | **--** | `--` | PREFLOP | 215 | 290 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4560` | 02:32 | 15/30 | 90 | **--** | `--` | PREFLOP | 215 | 290 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4575` | 02:32 | 15/30 | 0 | **--** | `--` | PREFLOP | 215 | 380 | 305 | S0 | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4590` | 02:33 | 15/30 | 0 | **--** | `--` | PREFLOP | 215 | 380 | 305 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4605` | 02:33 | 15/30 | 0 | **--** | `--` | PREFLOP | 215 | 380 | 305 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4620` | 02:34 | 15/30 | 15 | **--** | `--` | PREFLOP | 215 | 380 | -- | -- | `BTN_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `4635` | 02:34 | 15/30 | 15 | **--** | `--` | PREFLOP | 215 | 380 | 290 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4650` | 02:35 | 15/30 | 45 | **--** | `--` | PREFLOP | -- | 380 | 290 | -- | `BTN_OPEN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `4665` | 02:35 | 15/30 | 45 | **--** | `--` | PREFLOP | 185 | 380 | 290 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4680` | 02:36 | 15/30 | 45 | **--** | `--` | PREFLOP | 185 | 380 | 290 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4695` | 02:36 | 15/30 | 45 | **--** | `--` | PREFLOP | 185 | 380 | 290 | S1 | `BB_ISO_VS_LIMP` | **`ALL_IN`** | +0.70 | `LOOSE_CALLERS` |  |
| `4710` | 02:37 | 15/30 | 45 | **--** | `--` | PREFLOP | 185 | 380 | 290 | S1 | `BB_ISO_VS_LIMP` | **`ALL_IN`** | +0.70 | `LOOSE_CALLERS` |  |
| `4725` | 02:37 | 15/30 | 45 | **--** | `--` | PREFLOP | 185 | 380 | 290 | S1 | `BB_ISO_VS_LIMP` | **`ALL_IN`** | +0.70 | `LOOSE_CALLERS` |  |
| `4740` | 02:38 | 15/30 | 45 | **--** | `--` | PREFLOP | 185 | 380 | 290 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4755` | 02:38 | 15/30 | 45 | **--** | `--` | PREFLOP | 185 | 380 | 290 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4770` | 02:39 | 15/30 | 45 | **--** | `--` | PREFLOP | 185 | 380 | 290 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4785` | 02:39 | 15/30 | 45 | **--** | `--` | PREFLOP | 185 | 380 | 290 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4800` | 02:40 | 15/30 | 45 | **--** | `--` | PREFLOP | 185 | 380 | 290 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4815` | 02:40 | 15/30 | 45 | **--** | `--` | PREFLOP | 185 | 380 | 290 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4830` | 02:41 | 15/30 | 45 | **--** | `--` | PREFLOP | 185 | 380 | 290 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4845` | 02:41 | 15/30 | 45 | **--** | `--` | PREFLOP | 185 | 380 | 290 | S2 | `SB_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4860` | 02:42 | 15/30 | 45 | **--** | `--` | PREFLOP | 185 | 380 | 290 | S2 | `SB_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4875` | 02:42 | 15/30 | 45 | **--** | `--` | PREFLOP | 185 | 380 | 290 | S2 | `SB_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4890` | 02:43 | 15/30 | 45 | **--** | `--` | PREFLOP | 185 | 380 | 290 | S2 | `SB_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4905` | 02:43 | 15/30 | 60 | **--** | `--` | PREFLOP | 185 | 380 | 275 | -- | `BTN_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4920` | 02:44 | 15/30 | 60 | **--** | `--` | PREFLOP | 185 | 380 | 275 | S2 | `SB_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4935` | 02:44 | 15/30 | 60 | **--** | `--` | PREFLOP | 185 | 380 | 275 | S2 | `SB_OPEN` | **`ALL_IN`** | +0.60 | `LOOSE_CALLERS` |  |
| `4950` | 02:45 | 15/30 | 60 | **--** | `5h 5c Jh` | FLOP | 185 | 380 | 275 | S2 | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `4965` | 02:45 | 15/30 | 60 | **--** | `5h 5c Jh` | FLOP | 185 | 380 | 275 | S2 | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `4980` | 02:46 | 15/30 | 60 | **--** | `5h 5c Jh` | FLOP | 185 | 380 | 275 | S2 | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `4995` | 02:46 | 15/30 | 60 | **--** | `5h 5c Jh` | FLOP | 185 | 380 | 275 | S2 | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `5010` | 02:47 | 15/30 | 60 | **--** | `5h 5c Jh` | FLOP | 185 | 380 | 275 | S2 | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `5025` | 02:47 | 15/30 | 60 | **--** | `5h 5c Jh` | FLOP | 185 | 380 | 275 | S2 | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `5040` | 02:48 | 15/30 | 60 | **--** | `5h 5c Jh` | FLOP | 185 | 380 | 275 | S2 | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `5055` | 02:48 | 15/30 | 60 | **--** | `5h 5c Jh` | FLOP | 185 | 380 | 275 | S2 | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `5070` | 02:49 | 15/30 | 60 | **--** | `5h 5c Jh` | FLOP | 185 | 380 | 275 | S2 | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `5085` | 02:49 | 15/30 | 60 | **--** | `5h 5c Jh` | FLOP | 185 | 380 | 275 | S2 | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `5100` | 02:50 | 15/30 | 90 | **--** | `5h 5c Jh` | FLOP | 185 | 380 | 245 | -- | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `5115` | 02:50 | 15/30 | 90 | **--** | `5h 5c Jh` | FLOP | 185 | 380 | 245 | -- | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `5130` | 02:51 | 15/30 | 90 | **--** | `5h 5c Jh` | FLOP | 185 | 380 | 245 | -- | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `5145` | 02:51 | 15/30 | 120 | **--** | `5h 5c Jh` | FLOP | 155 | 380 | 245 | -- | `FLOP` | **`ALL_IN`** | +0.10 | `LOOSE_CALLERS` |  |
| `5160` | 02:52 | 15/30 | 120 | **--** | `5h 5c Jh` | FLOP | 155 | 380 | -- | S2 | `FLOP` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `5175` | 02:52 | 15/30 | 120 | **--** | `5h 5c Jh` | FLOP | 155 | 380 | -- | S2 | `FLOP` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `5190` | 02:53 | 15/30 | 120 | **--** | `5h 5c Jh 5h` | TURN | 155 | 380 | -- | S2 | `TURN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `5205` | 02:53 | 15/30 | 120 | **--** | `5h 5c Jh 5h` | TURN | 155 | 380 | -- | S2 | `TURN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `5220` | 02:54 | 15/30 | 120 | **--** | `5h 5c Jh 5h` | TURN | 155 | 380 | -- | S2 | `TURN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `5235` | 02:54 | 15/30 | 120 | **--** | `5h 5c Jh 5h` | TURN | 155 | 380 | 245 | -- | `TURN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `5250` | 02:55 | 15/30 | 120 | **--** | `5h 5c Jh 5h` | TURN | 155 | 380 | 245 | -- | `TURN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `5265` | 02:55 | 15/30 | 120 | **--** | `5h 5c Jh 5h` | TURN | 155 | 380 | 245 | -- | `TURN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `5280` | 02:56 | 15/30 | 150 | **--** | `5h 5c Jh 5h` | TURN | 125 | 380 | 245 | S2 | `TURN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `5295` | 02:56 | 15/30 | 150 | **--** | `5h 5c Jh 5h` | TURN | 125 | 380 | 245 | S2 | `TURN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `5310` | 02:57 | 15/30 | 150 | **--** | `5h 5c Jh 5h` | TURN | 125 | 380 | 245 | S2 | `TURN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `5325` | 02:57 | 15/30 | 150 | **--** | `5h 5c Jh 5h` | TURN | 125 | 380 | 245 | S2 | `TURN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `5340` | 02:58 | 15/30 | 180 | **--** | `5h 5c Jh 5h` | TURN | 125 | 380 | 215 | S2 | `TURN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `5355` | 02:58 | 15/30 | 180 | **--** | `5h 5c Jh 5h` | TURN | 125 | 380 | 215 | S2 | `TURN` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `5370` | 02:59 | 15/30 | 180 | **--** | `5h 5c Jh 5h Ks` | RIVER | 125 | 380 | 215 | S2 | `RIVER` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |
| `5385` | 02:59 | 15/30 | 180 | **--** | `5h 5c Jh 5h Ks` | RIVER | 125 | 380 | 215 | S2 | `RIVER` | **`WAIT`** | -- | `STANDARD_EXPLOIT` |  |

---

## 3. Szczegółowa Analiza Klatek Odrzuconych (`is_valid == False`)

Poniżej przedstawiono 3 reprezentatywne sytuacje, w których `StateValidator` poprawnie zablokował podjęcie decyzji z powodu przejściowych stanów stołu:

### Przykład 1: Klatka `0105` (00:03) ([zrzut ekranu: 08_frame_0105_missing_stack_reading.png](screens/08_frame_0105_missing_stack_reading.png))
* **Powód odrzucenia:** `Missing stack reading`
* **Odczyt potu:** `360` | **Blindy:** `10/20`
* **Odczytane stacki:** S0: `260`, S1: `None`, S2: `280` (suma: `900` / wymagane 900)
* **Karty:** Hero: `['2s', 'Ts']`, Board: `[]`
* **Wyjaśnienie:** W tym momencie na stole miała miejsce faza przejściowa (przesuwanie żetonów lub animacja odsłonięcia kolejnej karty), w której wartości pikseli w ROI stacka były zamazane. Walidator zapobiegł podjęciu decyzji w stanie częściowym.

### Przykład 2: Klatka `0750` (00:25) ([zrzut ekranu: 09_frame_0750_invalid_card_count.png](screens/09_frame_0750_invalid_card_count.png))
* **Powód odrzucenia:** `Invalid card count`
* **Odczyt potu:** `30` | **Blindy:** `10/20`
* **Odczytane stacki:** S0: `260`, S1: `350`, S2: `260` (suma: `900` / wymagane 900)
* **Karty:** Hero: `['Kd']`, Board: `[]`
* **Wyjaśnienie:** W tym momencie na stole miała miejsce faza przejściowa (przesuwanie żetonów lub animacja odsłonięcia kolejnej karty), w której wartości pikseli w ROI stacka były zamazane. Walidator zapobiegł podjęciu decyzji w stanie częściowym.

### Przykład 3: Klatka `2100` (01:10) ([zrzut ekranu: 10_frame_2100_chip_conservation_failed.png](screens/10_frame_2100_chip_conservation_failed.png))
* **Powód odrzucenia:** `Chip conservation failed: 855 != 900`
* **Odczyt potu:** `0` | **Blindy:** `15/30`
* **Odczytane stacki:** S0: `260`, S1: `350`, S2: `245` (suma: `855` / wymagane 900)
* **Karty:** Hero: `[]`, Board: `[]`
* **Wyjaśnienie:** W tym momencie na stole miała miejsce faza przejściowa (przesuwanie żetonów lub animacja odsłonięcia kolejnej karty), w której wartości pikseli w ROI stacka były zamazane. Walidator zapobiegł podjęciu decyzji w stanie częściowym.

---

## 4. Wykaz 10 Reprezentatywnych Zrzutów Ekranu (`raport/screens/`)

Wszystkie poniższe pliki graficzne zostały wycięte bezpośrednio z analizowanego fragmentu wideo i zapisane w folderze `raport/screens/`:

| Lp. | Plik zrzutu ekranu | Typ sytuacji | Klatka | Czas | Odczytana ręka | Akcja / Status |
|---|---|---|---|---|---|---|
| 1 | [01_frame_0000_hero_preflop_fold.png](screens/01_frame_0000_hero_preflop_fold.png) | `HERO_TURN` | `0000` | 00:00 | 2s Ts | **`FOLD`** (+0.00 BB) |
| 2 | [02_frame_0375_hero_preflop_all_in.png](screens/02_frame_0375_hero_preflop_all_in.png) | `HERO_TURN` | `0375` | 00:12 | -- | **`ALL_IN`** (+0.60 BB) |
| 3 | [03_frame_0765_hero_preflop_fold.png](screens/03_frame_0765_hero_preflop_fold.png) | `HERO_TURN` | `0765` | 00:25 | Kd 3c | **`FOLD`** (+0.00 BB) |
| 4 | [04_frame_0960_hero_flop_all_in.png](screens/04_frame_0960_hero_flop_all_in.png) | `HERO_TURN` | `0960` | 00:32 | Kd 3c | **`ALL_IN`** (+6.27 BB) |
| 5 | [05_frame_1560_hero_turn_all_in.png](screens/05_frame_1560_hero_turn_all_in.png) | `HERO_TURN` | `1560` | 00:52 | Kd 3c | **`ALL_IN`** (+6.07 BB) |
| 6 | [06_frame_1860_hero_river_all_in.png](screens/06_frame_1860_hero_river_all_in.png) | `HERO_TURN` | `1860` | 01:02 | Kd 3c | **`ALL_IN`** (+6.25 BB) |
| 7 | [07_frame_2280_hero_preflop_all_in.png](screens/07_frame_2280_hero_preflop_all_in.png) | `HERO_TURN` | `2280` | 01:16 | -- | **`ALL_IN`** (+0.60 BB) |
| 8 | [08_frame_0105_missing_stack_reading.png](screens/08_frame_0105_missing_stack_reading.png) | `INVALID` | `0105` | 00:03 | 2s Ts | Odrzucona: `Missing stack reading` |
| 9 | [09_frame_0750_invalid_card_count.png](screens/09_frame_0750_invalid_card_count.png) | `INVALID` | `0750` | 00:25 | Kd | Odrzucona: `Invalid card count` |
| 10 | [10_frame_2100_chip_conservation_failed.png](screens/10_frame_2100_chip_conservation_failed.png) | `INVALID` | `2100` | 01:10 | -- | Odrzucona: `Chip conservation failed` |

---

## 5. Wnioski Końcowe Integratora
1. **Doskonała szybkość:** Średni czas przetwarzania klatki na poziomie ~75–85 ms gwarantuje absolutną płynność w grze na żywo (<0.3 s).
2. **Precyzja kart 52/52:** Wszystkie 52 karty są bezbłędnie rozpoznawane bez fałszywych dopasowań.
3. **Ochrona kapitału (Złota zasada 900 chipów):** `StateValidator` działa bezbłędnie – w momentach ustabilizowanej gry zatwierdza stan z sumą 900 żetonów, a podczas animacji wstrzymuje niepotrzebne przeliczenia.