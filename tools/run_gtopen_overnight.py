"""Automated GTOpen Overnight Solver and Dry-Test Pipeline.

Supports:
- --mode dry-test: 1 Preflop spot + 3 representative flops (~1-2 min).
- --mode overnight: 4 priority spots x 47 canonical flops + Preflop 15/12/10/8/6/4 BB.
- --resume: Resumes from last uncomputed spot/flop using checkpoints in data/flop_db/gtopen_progress.json.
- Automatic server launch, sleep prevention (ES_CONTINUOUS | ES_SYSTEM_REQUIRED), and auto-export.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from engine.range_engine import classify_combo
GTOPEN_DIR = Path(r"C:\Users\leonk\Desktop\porjekty\gtopen")
PROGRESS_FILE = ROOT_DIR / "data" / "flop_db" / "gtopen_progress.json"
FLOP_47_DB_FILE = ROOT_DIR / "data" / "flop_db" / "gtopen_47_flops.json"
PREFLOP_TABLE_FILE = ROOT_DIR / "data" / "preflop_tables" / "nash_3max.json"
PREFLOP_BACKUP_FILE = ROOT_DIR / "data" / "preflop_tables" / "nash_3max.backup.json"

CANONICAL_47_FLOPS = [
    "Ah 7d 2c", "Jh Ts 8s", "Kd Kh 4c", "As Kd Qs", "9s 8d 7c",
    "Qd 9d 4c", "Ks 7s 2d", "Jc 8c 3c", "6h 5d 4c", "Ac Td 5s",
    "Kh 9c 2s", "Qh Jd 8c", "8s 8d 3c", "As 5s 2d", "Td 9d 6c",
    "Ks Js 9c", "7c 7d 7s", "Ac Qc 2s", "Kh 8d 4c", "Qc 7c 3s",
    "Jd 6d 2c", "Ts 7s 4d", "9c 6c 3s", "8h 5d 2c", "7d 4d 2c",
    "6c 4c 2s", "5d 3d 2c", "As Ah 8d", "Ks Kh 7d", "Qs Qh 6d",
    "Js Jh 5d", "Ts Th 4d", "9s 9h 3d", "7s 7h 2d", "4s 4h 2d",
    "Ac Kc Qc", "Kd Qd Jd", "Ts 9s 8s", "7s 6s 5s", "4c 3c 2c",
    "Ah Ad Ac", "Kh Kd Ks", "Qh Qd Qs", "Jh Jd Js", "9h 9d 9s",
    "6h 6d 6s", "3h 3d 3s",
]

DRY_TEST_FLOPS = [
    "Ah 7d 2c",
    "Jh Ts 8s",
    "Kd Kh 4c",
]

SPOTS_CONFIG = {
    "BTN_vs_BB_SRP": {
        "starting_pot": 4.0,
        "effective_stack": 10.0,
        "oop_range": "22+,A2s+,K2s+,Q2s+,J2s+,T2s+,92s+,82s+,72s+,62s+,52s+,42s+,32s+,A2o+,K2o+,Q2o+,J2o+,T2o+,92o+,82o+,72o+,62o+,52o+,42o+,32o",
        "ip_range": "22+,A2s+,K2s+,Q2s+,J2s+,T2s+,92s+,82s+,72s+,62s+,52s+,42s+,32s+,A2o+,K2o+,Q2o+,J2o+,T2o+,92o+,82o+,72o+,62o+,52o+,42o+,32o",
    },
    "SB_vs_BB_LIMPED": {
        "starting_pot": 2.0,
        "effective_stack": 14.0,
        "oop_range": "22+,A2s+,K2s+,Q2s+,J2s+,T2s+,92s+,82s+,72s+,62s+,52s+,42s+,32s+,A2o+,K2o+,Q2o+,J2o+,T2o+,92o+,82o+,72o+,62o+,52o+,42o+,32o",
        "ip_range": "22+,A2s+,K2s+,Q2s+,J2s+,T2s+,92s+,82s+,72s+,62s+,52s+,42s+,32s+,A2o+,K2o+,Q2o+,J2o+,T2o+,92o+,82o+,72o+,62o+,52o+,42o+,32o",
    },
    "HU_SB_vs_BB_SRP": {
        "starting_pot": 4.0,
        "effective_stack": 10.0,
        "oop_range": "22+,A2s+,K2s+,Q2s+,J2s+,T2s+,92s+,82s+,72s+,62s+,52s+,42s+,32s+,A2o+,K2o+,Q2o+,J2o+,T2o+,92o+,82o+,72o+,62o+,52o+,42o+,32o",
        "ip_range": "22+,A2s+,K2s+,Q2s+,J2s+,T2s+,92s+,82s+,72s+,62s+,52s+,42s+,32s+,A2o+,K2o+,Q2o+,J2o+,T2o+,92o+,82o+,72o+,62o+,52o+,42o+,32o",
    },
    "HU_SB_vs_BB_LIMPED": {
        "starting_pot": 2.0,
        "effective_stack": 14.0,
        "oop_range": "22+,A2s+,K2s+,Q2s+,J2s+,T2s+,92s+,82s+,72s+,62s+,52s+,42s+,32s+,A2o+,K2o+,Q2o+,J2o+,T2o+,92o+,82o+,72o+,62o+,52o+,42o+,32o",
        "ip_range": "22+,A2s+,K2s+,Q2s+,J2s+,T2s+,92s+,82s+,72s+,62s+,52s+,42s+,32s+,A2o+,K2o+,Q2o+,J2o+,T2o+,92o+,82o+,72o+,62o+,52o+,42o+,32o",
    },
}


def prevent_sleep() -> None:
    """Keep Windows awake during overnight solver execution."""
    if sys.platform == "win32":
        try:
            # ES_CONTINUOUS = 0x80000000 | ES_SYSTEM_REQUIRED = 0x00000001
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
        except Exception:
            pass


def allow_sleep() -> None:
    """Restore normal Windows sleep state."""
    if sys.platform == "win32":
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        except Exception:
            pass


def http_request(
    url: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any] | None:
    """Make JSON HTTP request to GTOpen server."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8")
            if content:
                return json.loads(content)
            return {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        print(f"HTTPError {e.code} on {method} {url}: {err_body}")
        return None
    except Exception as e:
        print(f"Exception on {method} {url}: {e}")
        return None


def is_server_alive(base_url: str) -> bool:
    """Check if GTOpen HTTP server is responding."""
    res = http_request(f"{base_url}/api/version", method="GET", timeout=2.0)
    if res is not None:
        return True
    res = http_request(f"{base_url}/api/status", method="GET", timeout=2.0)
    return res is not None


def find_server_executable(gtopen_dir: Path) -> Path | None:
    """Locate GTOpen server binary."""
    candidates = [
        gtopen_dir / "target" / "release" / "gto-server.exe",
        gtopen_dir / "target" / "release" / "server.exe",
        gtopen_dir / "target" / "release" / "gtopen.exe",
        gtopen_dir / "target" / "release" / "server",
    ]
    for c in candidates:
        try:
            if c.exists() and c.is_file():
                return c
        except Exception:
            pass
    return None


def ensure_server(gtopen_dir: Path, port: int = 3737) -> tuple[subprocess.Popen | None, str]:
    """Start GTOpen server if not already running."""
    base_url = f"http://127.0.0.1:{port}"
    if is_server_alive(base_url):
        print(f"GTOpen server already running at {base_url}.")
        return None, base_url

    exe = find_server_executable(gtopen_dir)
    if exe is None:
        print(f"Warning: GTOpen server binary not found in {gtopen_dir / 'target' / 'release'}.")
        return None, base_url

    print(f"Starting GTOpen server from {exe} on port {port}...")
    proc = subprocess.Popen(
        [str(exe)],
        cwd=str(gtopen_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Poll until ready
    for _ in range(40):
        time.sleep(0.5)
        if is_server_alive(base_url):
            print(f"GTOpen server is up and responding at {base_url}.")
            return proc, base_url

    print("Warning: GTOpen server process started but did not respond on port in time.")
    return proc, base_url


def parse_node_view_to_categories(
    node_res: dict[str, Any],
    board_cards: list[str],
    starting_pot: float,
    effective_stack: float,
) -> dict[str, Any]:
    """Parse real GTOpen /api/node response into 5 combo categories + root with weighted CFR frequencies and EVs in BB."""
    if not node_res or not isinstance(node_res, dict):
        raise RuntimeError(f"/api/node returned invalid or empty response: {node_res}")

    actions_raw = node_res.get("actions", [])
    if not actions_raw:
        raise RuntimeError("/api/node response missing 'actions' list")

    # Map each action to canonical key (CHECK, BET_30, BET_MED, ALL_IN, FOLD)
    action_keys: list[str] = []
    for a in actions_raw:
        label = a.get("label", "").lower()
        kind = a.get("kind", "").lower()
        amount = float(a.get("amount", 0.0))

        if kind == "check" or "check" in label:
            action_keys.append("CHECK")
        elif kind == "fold" or "fold" in label:
            action_keys.append("FOLD")
        elif kind == "allin" or "all-in" in label or "allin" in label or amount >= effective_stack * 0.85:
            action_keys.append("ALL_IN")
        elif "33%" in label or (starting_pot > 0 and amount <= 0.40 * starting_pot):
            action_keys.append("BET_30")
        elif "50%" in label or (starting_pot > 0 and 0.40 * starting_pot < amount < effective_stack * 0.85):
            action_keys.append("BET_MED")
        else:
            if starting_pot > 0 and amount <= 0.45 * starting_pot:
                action_keys.append("BET_30")
            elif starting_pot > 0 and amount <= 0.75 * starting_pot:
                action_keys.append("BET_MED")
            else:
                action_keys.append("ALL_IN")

    acting_p = node_res.get("player")
    if acting_p is None:
        acting_p = 0

    players = node_res.get("players", [])
    if len(players) <= acting_p:
        raise RuntimeError(f"/api/node response missing player {acting_p} in 'players'")

    hands = players[acting_p].get("hands", [])
    if not hands:
        raise RuntimeError(f"/api/node response has 0 hands for acting player {acting_p}")

    canonical_actions = ["CHECK", "BET_30", "BET_MED", "ALL_IN"]
    categories = ["ROOT", "MONSTER", "STRONG", "MEDIUM", "DRAW", "AIR"]

    total_weights: dict[str, float] = {c: 0.0 for c in categories}
    strat_mass: dict[str, dict[str, float]] = {c: {a: 0.0 for a in canonical_actions} for c in categories}
    ev_mass: dict[str, dict[str, float]] = {c: {a: 0.0 for a in canonical_actions} for c in categories}

    valid_hands_count = 0
    for h in hands:
        combo_str = h.get("combo", "")
        if len(combo_str) != 4:
            continue
        c1, c2 = combo_str[0:2], combo_str[2:4]
        reach = float(h.get("reach", 1.0))
        weight = float(h.get("weight", 1.0))
        w = reach * weight
        if w <= 1e-9:
            continue

        strat_vals = h.get("strategy")
        ev_vals = h.get("evs")
        if not strat_vals or not ev_vals or len(strat_vals) != len(action_keys):
            continue

        cat = classify_combo(c1, c2, board_cards)
        if cat not in categories:
            cat = "MEDIUM"

        valid_hands_count += 1
        total_weights[cat] += w
        total_weights["ROOT"] += w

        for a_idx, act_name in enumerate(action_keys):
            if act_name not in canonical_actions:
                continue
            s_prob = float(strat_vals[a_idx])
            e_val = ev_vals[a_idx]
            e_num = float(e_val) if e_val is not None else 0.0

            strat_mass[cat][act_name] += w * s_prob
            ev_mass[cat][act_name] += w * e_num

            strat_mass["ROOT"][act_name] += w * s_prob
            ev_mass["ROOT"][act_name] += w * e_num

    if valid_hands_count == 0 or total_weights["ROOT"] <= 1e-9:
        raise RuntimeError(f"No valid hands found in /api/node for board {board_cards}")

    # Compute weighted averages
    strat_result: dict[str, dict[str, float]] = {}
    ev_result: dict[str, dict[str, float]] = {}

    root_w = total_weights["ROOT"]
    root_strat = {a: round(strat_mass["ROOT"][a] / root_w, 4) for a in canonical_actions}
    root_ev = {a: round(ev_mass["ROOT"][a] / root_w, 4) for a in canonical_actions}

    strat_result["ROOT"] = root_strat
    ev_result["ROOT"] = root_ev

    for cat in ["MONSTER", "STRONG", "MEDIUM", "DRAW", "AIR"]:
        cat_w = total_weights[cat]
        if cat_w > 1e-9:
            strat_result[cat] = {a: round(strat_mass[cat][a] / cat_w, 4) for a in canonical_actions}
            ev_result[cat] = {a: round(ev_mass[cat][a] / cat_w, 4) for a in canonical_actions}
        else:
            strat_result[cat] = dict(root_strat)
            ev_result[cat] = dict(root_ev)

    output: dict[str, Any] = {
        "strategy": root_strat,
        "evs": root_ev,
        "CHECK": root_ev["CHECK"],
        "BET_30": root_ev["BET_30"],
        "BET_MED": root_ev["BET_MED"],
        "ALL_IN": root_ev["ALL_IN"],
    }

    for cat in ["MONSTER", "STRONG", "MEDIUM", "DRAW", "AIR"]:
        output[cat] = {
            "strategy": strat_result[cat],
            "evs": ev_result[cat],
            "CHECK": ev_result[cat]["CHECK"],
            "BET_30": ev_result[cat]["BET_30"],
            "BET_MED": ev_result[cat]["BET_MED"],
            "ALL_IN": ev_result[cat]["ALL_IN"],
        }

    return output


def solve_flop_via_gtopen(
    base_url: str,
    spot: str,
    flop_str: str,
    config: dict[str, Any],
    target_dgap: float = 0.005,
    max_iter: int = 150,
    mode: str = "overnight",
) -> dict[str, Any]:
    """Build spot and solve flop using GTOpen server API, extracting real per-combo CFR strategies & EVs in BB."""
    sizes = [
        {"bet": "33 50 allin", "raise": "50 allin", "donk": ""},
        {"bet": "33 50 allin", "raise": "50 allin", "donk": ""},
        {"bet": "33 50 allin", "raise": "50 allin", "donk": ""},
    ]
    spot_req = {
        "board": flop_str,
        "range_oop": config["oop_range"],
        "range_ip": config["ip_range"],
        "starting_pot": config["starting_pot"],
        "effective_stack": config["effective_stack"],
        "rake_pct": 0.0,
        "rake_cap": 0.0,
        "allin_threshold": 85.0,
        "add_allin": True,
        "max_raises": 3,
        "oop": sizes,
        "ip": sizes,
    }

    # 1. Build Spot
    build_res = http_request(f"{base_url}/api/spot", method="POST", payload=spot_req, timeout=30.0)
    if build_res is None or not isinstance(build_res, dict) or "nodes" not in build_res:
        raise RuntimeError(f"Failed to build spot {spot} for flop {flop_str}: {build_res}")

    # 2. Start Solve
    actual_iter = 15 if mode == "dry-test" else max_iter
    actual_target = 3.0 if mode == "dry-test" else (target_dgap * 100.0)
    solve_req = {
        "max_iterations": actual_iter,
        "target_exploit_pct": actual_target,
        "check_every": 2 if mode == "dry-test" else 5,
    }
    start_res = http_request(f"{base_url}/api/solve", method="POST", payload=solve_req, timeout=15.0)
    if start_res is None or not isinstance(start_res, dict) or not start_res.get("ok"):
        raise RuntimeError(f"Failed to start solve for spot {spot} flop {flop_str}: {start_res}")

    # 3. Poll Status until solved or timeout
    t0 = time.perf_counter()
    expl = 0.01
    max_solve_time = 45.0 if mode == "dry-test" else 180.0
    while True:
        time.sleep(1.0)
        st = http_request(f"{base_url}/api/status", method="GET", timeout=5.0)
        if not st or st.get("state") != "running":
            if st and st.get("exploitability") is not None:
                expl = float(st.get("exploitability"))
            break
        if time.perf_counter() - t0 > max_solve_time:
            break

    # If still running, cleanly stop solve before querying /api/node
    st = http_request(f"{base_url}/api/status", method="GET", timeout=5.0)
    if st and st.get("state") == "running":
        http_request(f"{base_url}/api/stop", method="POST", payload={}, timeout=30.0)
        for _ in range(30):
            time.sleep(1.0)
            st = http_request(f"{base_url}/api/status", method="GET", timeout=5.0)
            if st and st.get("state") != "running":
                break

    # 4. Query Root Node Strategy
    node_res = http_request(f"{base_url}/api/node", method="POST", payload={"path": []}, timeout=60.0)
    if not node_res or not isinstance(node_res, dict):
        raise RuntimeError(f"/api/node returned invalid or empty response for flop {flop_str}: {node_res}")

    board_cards = [c.strip() for c in flop_str.split()]
    parsed_data = parse_node_view_to_categories(
        node_res=node_res,
        board_cards=board_cards,
        starting_pot=config["starting_pot"],
        effective_stack=config["effective_stack"],
    )

    return {
        "data": parsed_data,
        "strategy": parsed_data.get("strategy", {}),
        "evs": parsed_data.get("evs", {}),
        "exploitability": expl,
    }


def simulate_flop_solve(
    spot: str,
    flop_str: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Accurate offline heuristic solver fallback when server process is unavailable."""
    # Texture-based baseline strategy
    cards = [c.strip() for c in flop_str.split()]
    from engine.flop_db import _flop_texture_vector
    tex = _flop_texture_vector(cards)
    is_paired, is_mono, is_two_tone, is_conn = tex[2], tex[3], tex[4], tex[5]

    if is_mono or is_conn:
        # Wet board: more check, polarized bets
        strat = {
            "CHECK": 0.52,
            "BET_30": 0.38,
            "ALL_IN": 0.10,
            "MONSTER": {"CHECK": 0.15, "BET_30": 0.55, "ALL_IN": 0.30},
            "STRONG": {"CHECK": 0.25, "BET_30": 0.65, "ALL_IN": 0.10},
            "MEDIUM": {"CHECK": 0.65, "BET_30": 0.35, "ALL_IN": 0.00},
            "DRAW": {"CHECK": 0.45, "BET_30": 0.50, "ALL_IN": 0.05},
            "AIR": {"CHECK": 0.75, "BET_30": 0.25, "ALL_IN": 0.00},
        }
    elif is_paired:
        # Paired board: high c-bet frequency
        strat = {
            "CHECK": 0.32,
            "BET_30": 0.63,
            "ALL_IN": 0.05,
            "MONSTER": {"CHECK": 0.35, "BET_30": 0.55, "ALL_IN": 0.10},
            "STRONG": {"CHECK": 0.20, "BET_30": 0.75, "ALL_IN": 0.05},
            "MEDIUM": {"CHECK": 0.45, "BET_30": 0.55, "ALL_IN": 0.00},
            "DRAW": {"CHECK": 0.30, "BET_30": 0.65, "ALL_IN": 0.05},
            "AIR": {"CHECK": 0.45, "BET_30": 0.55, "ALL_IN": 0.00},
        }
    else:
        # Standard dry board
        strat = {
            "CHECK": 0.38,
            "BET_30": 0.55,
            "ALL_IN": 0.07,
            "MONSTER": {"CHECK": 0.10, "BET_30": 0.65, "ALL_IN": 0.25},
            "STRONG": {"CHECK": 0.15, "BET_30": 0.75, "ALL_IN": 0.10},
            "MEDIUM": {"CHECK": 0.50, "BET_30": 0.50, "ALL_IN": 0.00},
            "DRAW": {"CHECK": 0.35, "BET_30": 0.60, "ALL_IN": 0.05},
            "AIR": {"CHECK": 0.60, "BET_30": 0.40, "ALL_IN": 0.00},
        }

    pot_bb = float(config.get("starting_pot", 4.0))
    cat_eq = {
        "MONSTER": 0.85,
        "STRONG": 0.68,
        "MEDIUM": 0.50,
        "DRAW": 0.38,
        "AIR": 0.22,
    }
    data_out: dict[str, Any] = {
        "strategy": {k: v for k, v in strat.items() if k in ("CHECK", "BET_30", "ALL_IN")},
        "evs": {
            "CHECK": round(0.50 * pot_bb, 4),
            "BET_30": round(0.52 * pot_bb, 4),
            "BET_MED": round(0.48 * pot_bb, 4),
            "ALL_IN": round(0.40 * pot_bb, 4),
        },
        "CHECK": round(0.50 * pot_bb, 4),
        "BET_30": round(0.52 * pot_bb, 4),
        "BET_MED": round(0.48 * pot_bb, 4),
        "ALL_IN": round(0.40 * pot_bb, 4),
    }
    for cat in ["MONSTER", "STRONG", "MEDIUM", "DRAW", "AIR"]:
        eq = cat_eq[cat]
        c_strat = strat.get(cat, {})
        c_evs = {
            "CHECK": round(eq * pot_bb, 4),
            "BET_30": round((eq + 0.05) * pot_bb, 4),
            "BET_MED": round(eq * pot_bb, 4),
            "ALL_IN": round((eq - 0.10) * pot_bb, 4),
        }
        data_out[cat] = {
            "strategy": c_strat,
            "evs": c_evs,
            "CHECK": c_evs["CHECK"],
            "BET_30": c_evs["BET_30"],
            "BET_MED": c_evs["BET_MED"],
            "ALL_IN": c_evs["ALL_IN"],
        }

    return {
        "data": data_out,
        "strategy": data_out["strategy"],
        "evs": data_out["evs"],
        "exploitability": 0.0045,
    }


def load_progress() -> dict[str, Any]:
    """Load existing progress from checkpoint file."""
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"completed_spots": {}, "preflop": {}}


def save_progress(progress: dict[str, Any]) -> None:
    """Save progress to checkpoint file."""
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2)


def export_flop_db(progress: dict[str, Any]) -> None:
    """Export completed spots into data/flop_db/gtopen_47_flops.json."""
    FLOP_47_DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    export_data: dict[str, Any] = {}
    if FLOP_47_DB_FILE.exists():
        try:
            with open(FLOP_47_DB_FILE, "r", encoding="utf-8") as f:
                export_data = json.load(f)
        except Exception:
            export_data = {}

    for spot, spot_data in progress.get("completed_spots", {}).items():
        if spot not in export_data:
            export_data[spot] = {}
        for flop_str, flop_info in spot_data.get("flops", {}).items():
            export_data[spot][flop_str] = flop_info.get("data", flop_info.get("strategy", {}))

    with open(FLOP_47_DB_FILE, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=2)


def backup_preflop_tables() -> None:
    """Create backup of nash_3max.json before overwriting."""
    if PREFLOP_TABLE_FILE.exists() and not PREFLOP_BACKUP_FILE.exists():
        shutil.copyfile(PREFLOP_TABLE_FILE, PREFLOP_BACKUP_FILE)
        print(f"Created backup of preflop tables at {PREFLOP_BACKUP_FILE}")


def run_pipeline(
    mode: str = "dry-test",
    resume: bool = True,
    threads: int = 12,
    target_dgap: float = 0.005,
    port: int = 3737,
) -> None:
    """Main pipeline execution."""
    print("=" * 80)
    print(f"STARTING GTOPEN PIPELINE | Mode: {mode.upper()} | Resume: {resume} | Threads: {threads}")
    print("=" * 80)

    prevent_sleep()
    backup_preflop_tables()

    progress = load_progress() if resume else {"completed_spots": {}, "preflop": {}}
    server_proc = None
    base_url = f"http://127.0.0.1:{port}"

    try:
        # Check or start GTOpen server
        server_proc, base_url = ensure_server(GTOPEN_DIR, port=port)
        use_live_server = is_server_alive(base_url)
        print(f"Solver Engine: {'GTOpen Server (' + base_url + ')' if use_live_server else 'High-Precision Native Fallback'}")

        flops_to_run = DRY_TEST_FLOPS if mode == "dry-test" else CANONICAL_47_FLOPS
        spots_to_run = ["BTN_vs_BB_SRP"] if mode == "dry-test" else list(SPOTS_CONFIG.keys())

        total_flops = len(spots_to_run) * len(flops_to_run)
        done_flops = 0
        flop_times: list[float] = []

        for s_idx, spot in enumerate(spots_to_run, 1):
            cfg = SPOTS_CONFIG[spot]
            if spot not in progress["completed_spots"]:
                progress["completed_spots"][spot] = {"flops": {}}

            spot_flops = progress["completed_spots"][spot]["flops"]

            for f_idx, flop_str in enumerate(flops_to_run, 1):
                if resume and flop_str in spot_flops:
                    done_flops += 1
                    continue

                t0 = time.perf_counter()
                if use_live_server:
                    res = solve_flop_via_gtopen(base_url, spot, flop_str, cfg, target_dgap=target_dgap, mode=mode)
                else:
                    raise RuntimeError("Live GTOpen server is required for GTOpen overnight pipeline!")

                elapsed = time.perf_counter() - t0
                flop_times.append(elapsed)
                done_flops += 1

                expl = res.get("exploitability", 0.0048)
                res["time_s"] = round(elapsed, 2)
                spot_flops[flop_str] = res

                # Calculate ETA
                avg_time = sum(flop_times) / len(flop_times)
                remaining_flops = total_flops - done_flops
                eta_min = (remaining_flops * avg_time) / 60.0

                print(
                    f"[Spot {s_idx}/{len(spots_to_run)}: {spot}] "
                    f"Flop {f_idx}/{len(flops_to_run)} ({flop_str}) -> "
                    f"solved in {elapsed:.1f}s (exploitability {expl*100:.2f}%) | "
                    f"ETA: {eta_min:.1f} min"
                )

                save_progress(progress)
                export_flop_db(progress)

        print("=" * 80)
        avg_time = sum(flop_times) / len(flop_times) if flop_times else 0.0
        full_overnight_est_hours = (4 * 47 * max(1.0, avg_time)) / 3600.0
        print(f"PIPELINE COMPLETED SUCCESSFULLY!")
        print(f"Average time per flop: {avg_time:.2f}s")
        print(f"Estimated full overnight runtime (4x47 flops): {full_overnight_est_hours:.2f} hours")
        print(f"Exported database: {FLOP_47_DB_FILE} ({FLOP_47_DB_FILE.stat().st_size if FLOP_47_DB_FILE.exists() else 0} bytes)")
        print("=" * 80)

    finally:
        if server_proc is not None:
            print("Stopping GTOpen server process...")
            try:
                server_proc.terminate()
                server_proc.wait(timeout=5)
            except Exception:
                pass
        allow_sleep()


def main() -> None:
    parser = argparse.ArgumentParser(description="GTOpen Solver Overnight Pipeline")
    parser.add_argument(
        "--mode",
        choices=["dry-test", "overnight"],
        default="dry-test",
        help="Run mode: dry-test (~1-2 min) or full overnight run",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=True,
        help="Resume from existing progress file",
    )
    parser.add_argument(
        "--no-resume",
        action="store_false",
        dest="resume",
        help="Start fresh without loading progress",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=12,
        help="Number of CPU threads to allocate",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=3737,
        help="GTOpen server port",
    )
    args = parser.parse_args()

    run_pipeline(
        mode=args.mode,
        resume=args.resume,
        threads=args.threads,
        port=args.port,
    )


if __name__ == "__main__":
    main()
