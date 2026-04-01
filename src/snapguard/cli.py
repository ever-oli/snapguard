
import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import List, Dict, Optional

CONFIG_PATH = Path(os.path.expanduser("~/.config/snapshot-guard/config.json"))
LOG_PATH = Path(os.path.expanduser("~/.local/state/prune-snapshot-caches.log"))
WRAPPER_PATH = Path(os.path.expanduser("~/.local/bin/snapguard"))
CRON_MARKER = "# snapshot-guard"

DEFAULT_TARGETS = [
    {
        "name": "opencode_snapshot",
        "path": "~/.local/share/opencode/snapshot",
        "cap_gb": 5.0,
        "mode": "reset_dir",
    },
    {
        "name": "cursor_workspace_storage",
        "path": "~/Library/Application Support/Cursor/User/workspaceStorage",
        "cap_gb": 5.0,
        "mode": "prune_oldest_children",
    },
    {
        "name": "cursor_snapshots",
        "path": "~/Library/Application Support/Cursor/snapshots",
        "cap_gb": 5.0,
        "mode": "prune_oldest_children",
    },
    {
        "name": "cursor_global_storage",
        "path": "~/Library/Application Support/Cursor/User/globalStorage",
        "cap_gb": 8.0,
        "mode": "prune_oldest_children",
    },
]


# ---------- utils ----------

def fmt_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    x = float(n)
    for u in units:
        if x < 1024 or u == units[-1]:
            return f"{x:.1f}{u}"
        x /= 1024
    return f"{n}B"


def draw_bar(current: int, cap: int, width: int = 28) -> str:
    if cap <= 0:
        return "-" * width
    ratio = max(0.0, min(2.0, current / cap))
    filled = int(min(width, round((min(ratio, 1.0)) * width)))
    bar = "█" * filled + "░" * (width - filled)
    if ratio > 1.0:
        over = f" +{(ratio - 1.0) * 100:.0f}%"
    else:
        over = ""
    return f"{bar}{over}"


def dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for root, _, files in os.walk(path, onerror=lambda e: None):
        for f in files:
            fp = os.path.join(root, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


def remove_path(p: Path, dry_run: bool) -> int:
    s = dir_size(p) if p.is_dir() else (p.stat().st_size if p.exists() else 0)
    if dry_run:
        return s
    try:
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    except FileNotFoundError:
        pass
    return s


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


# ---------- prune logic ----------

def prune_oldest_children(path: Path, cap_bytes: int, dry_run: bool, target_ratio: float = 0.8) -> int:
    if not path.exists():
        return 0

    current = dir_size(path)
    if current <= cap_bytes:
        return 0

    target = int(cap_bytes * target_ratio)

    children = []
    for child in path.iterdir():
        try:
            st = child.stat()
            mtime = st.st_mtime
            size = dir_size(child) if child.is_dir() else st.st_size
        except OSError:
            mtime = time.time()
            size = 0
        children.append((mtime, size, child))

    children.sort(key=lambda x: x[0])  # oldest first

    freed = 0
    for _, _, child in children:
        if current - freed <= target:
            break
        freed += remove_path(child, dry_run=dry_run)

    return freed


def reset_dir_if_over_cap(path: Path, cap_bytes: int, dry_run: bool) -> int:
    current = dir_size(path)
    if current <= cap_bytes:
        return 0

    freed = remove_path(path, dry_run=dry_run)
    if not dry_run:
        ensure_dir(path)
    return freed


def run_target(t: dict, default_cap_gb: Optional[float], dry_run: bool) -> dict:
    path = Path(os.path.expanduser(t["path"]))
    cap_gb = float(default_cap_gb) if default_cap_gb is not None else float(t.get("cap_gb", 5.0))
    cap_bytes = int(cap_gb * 1024**3)

    before = dir_size(path)
    mode = t.get("mode", "reset_dir")

    if mode == "reset_dir":
        freed = reset_dir_if_over_cap(path, cap_bytes, dry_run)
    elif mode == "prune_oldest_children":
        freed = prune_oldest_children(path, cap_bytes, dry_run)
    else:
        freed = 0

    after = before if dry_run else dir_size(path)

    return {
        "name": t["name"],
        "path": str(path),
        "cap": cap_bytes,
        "before": before,
        "after": after,
        "freed": freed,
        "mode": mode,
        "exists": path.exists(),
    }


def run_once(cap_gb: Optional[float], dry_run: bool) -> List[Dict]:
    return [run_target(t, cap_gb, dry_run) for t in DEFAULT_TARGETS]


# ---------- config ----------

def load_config() -> dict:
    cfg = {"cap_gb": 5.0, "schedule": "hourly"}
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text())
            if isinstance(data, dict):
                cfg.update(data)
        except Exception:
            pass
    return cfg


def save_config(cfg: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")


# ---------- cron ----------

def cron_spec_for_schedule(schedule: str) -> Optional[str]:
    mapping = {
        "30m": "*/30 * * * *",
        "hourly": "0 * * * *",
        "daily": "0 3 * * *",
        "off": None,
    }
    return mapping.get(schedule)


def read_crontab_lines() -> List[str]:
    p = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if p.returncode != 0:
        return []
    return [ln for ln in p.stdout.splitlines() if ln.strip()]


def write_crontab_lines(lines: List[str]):
    txt = "\n".join(lines).strip() + "\n"
    subprocess.run(["crontab", "-"], input=txt, text=True, check=True)


def managed_cron_line(cap_gb: float, schedule: str) -> Optional[str]:
    spec = cron_spec_for_schedule(schedule)
    if spec is None:
        return None
    cmd = f"{WRAPPER_PATH} --cap-gb {cap_gb:g} >> {LOG_PATH} 2>&1"
    return f"{spec} {cmd} {CRON_MARKER}"


def current_managed_cron() -> Optional[str]:
    lines = read_crontab_lines()
    for ln in lines:
        if CRON_MARKER in ln:
            return ln
    return None


def apply_managed_schedule(cap_gb: float, schedule: str):
    lines = [ln for ln in read_crontab_lines() if CRON_MARKER not in ln]
    new_line = managed_cron_line(cap_gb, schedule)
    if new_line:
        lines.append(new_line)
    write_crontab_lines(lines)


# ---------- reporting ----------

def print_report(results: List[Dict], dry_run: bool):
    total_freed = sum(r["freed"] for r in results)
    mode_text = "DRY-RUN" if dry_run else "APPLY"
    print(f"[{mode_text}] snapshot/cache prune report")
    for r in results:
        print(
            f"- {r['name']}: cap={fmt_bytes(r['cap'])} | {fmt_bytes(r['before'])} -> {fmt_bytes(r['after'])} | freed={fmt_bytes(r['freed'])} | mode={r['mode']}"
        )
    print(f"Total freed: {fmt_bytes(total_freed)}")


def print_status(cap_gb: float):
    cap_bytes = int(cap_gb * 1024**3)
    print(f"Snapshot Guard status (cap={cap_gb:g}GB)")
    for t in DEFAULT_TARGETS:
        p = Path(os.path.expanduser(t["path"]))
        sz = dir_size(p)
        pct = (sz / cap_bytes * 100) if cap_bytes else 0
        print(f"- {t['name']}: {fmt_bytes(sz)} ({pct:.1f}% of cap)")
        print(f"  {draw_bar(sz, cap_bytes)}")
    cron = current_managed_cron()
    print(f"Cron: {cron if cron else 'not configured by snapshot-guard'}")
    if LOG_PATH.exists():
        print(f"Log: {LOG_PATH}")


# ---------- interactive dashboard ----------

def tail_log(lines: int = 20):
    if not LOG_PATH.exists():
        print("No log yet.")
        return
    data = LOG_PATH.read_text(errors="ignore").splitlines()
    print("\n".join(data[-lines:]))


def dashboard():
    cfg = load_config()
    cap_gb = float(cfg.get("cap_gb", 5.0))
    schedule = str(cfg.get("schedule", "hourly"))

    while True:
        os.system("clear")
        cap_bytes = int(cap_gb * 1024**3)
        print("Snapshot Guard Dashboard")
        print("=" * 60)
        print(f"Cap: {cap_gb:g}GB | Schedule: {schedule}")
        cron = current_managed_cron()
        print(f"Cron: {cron if cron else 'not configured'}")
        print("-" * 60)

        total = 0
        for t in DEFAULT_TARGETS:
            p = Path(os.path.expanduser(t["path"]))
            sz = dir_size(p)
            total += sz
            pct = (sz / cap_bytes * 100) if cap_bytes else 0.0
            print(f"{t['name']:<28} {fmt_bytes(sz):>9}  ({pct:5.1f}%)")
            print(f"  {draw_bar(sz, cap_bytes)}")

        print("-" * 60)
        print(f"Tracked total: {fmt_bytes(total)}")
        print("Commands: [r]efresh  [p]rune now  [d]ry-run  [c]ap  [s]chedule  [l]og  [q]uit")

        choice = input("> ").strip().lower()

        if choice in ("q", "quit", "exit"):
            cfg["cap_gb"] = cap_gb
            cfg["schedule"] = schedule
            save_config(cfg)
            print("Saved config. Bye.")
            break

        if choice in ("r", "refresh", ""):
            continue

        if choice in ("p", "prune"):
            results = run_once(cap_gb=cap_gb, dry_run=False)
            print_report(results, dry_run=False)
            input("\nPress Enter to continue...")
            continue

        if choice in ("d", "dry", "dry-run"):
            results = run_once(cap_gb=cap_gb, dry_run=True)
            print_report(results, dry_run=True)
            input("\nPress Enter to continue...")
            continue

        if choice in ("c", "cap"):
            raw = input("New cap in GB (e.g. 5): ").strip()
            try:
                new_cap = float(raw)
                if new_cap <= 0:
                    raise ValueError("cap must be > 0")
                cap_gb = new_cap
                cfg["cap_gb"] = cap_gb
                save_config(cfg)
                # keep cron command in sync with new cap
                apply_managed_schedule(cap_gb, schedule)
            except Exception:
                print("Invalid cap.")
                input("Press Enter...")
            continue

        if choice in ("s", "schedule"):
            print("Schedule options: 30m | hourly | daily | off")
            raw = input("Choose schedule: ").strip().lower()
            if raw in ("30m", "hourly", "daily", "off"):
                schedule = raw
                cfg["schedule"] = schedule
                save_config(cfg)
                apply_managed_schedule(cap_gb, schedule)
            else:
                print("Invalid schedule.")
                input("Press Enter...")
            continue

        if choice in ("l", "log"):
            tail_log(30)
            input("\nPress Enter to continue...")
            continue

        print("Unknown command.")
        input("Press Enter...")


def main():
    parser = argparse.ArgumentParser(description="Prune opencode/cursor snapshot & cache directories when they exceed a cap.")
    parser.add_argument("--cap-gb", type=float, default=None, help="Override cap (GB) for all targets.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting.")
    parser.add_argument("--status", action="store_true", help="Show current usage bars and cron status.")
    parser.add_argument("--interactive", action="store_true", help="Open interactive dashboard.")
    parser.add_argument("--schedule", choices=["30m", "hourly", "daily", "off"], help="Set managed cron schedule.")
    args = parser.parse_args()

    cfg = load_config()
    cap_gb = args.cap_gb if args.cap_gb is not None else float(cfg.get("cap_gb", 5.0))

    if args.schedule:
        cfg["schedule"] = args.schedule
        cfg["cap_gb"] = cap_gb
        save_config(cfg)
        apply_managed_schedule(cap_gb, args.schedule)

    if args.interactive:
        dashboard()
        return

    if args.status:
        print_status(cap_gb)
        return

    results = run_once(cap_gb=cap_gb, dry_run=args.dry_run)
    print_report(results, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
