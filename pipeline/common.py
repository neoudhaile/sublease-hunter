import json
import os
import sys
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "raw"
CACHE_DIR = ROOT / "cache"
OUT_DIR = ROOT / "out"
POSTS_PATH = CACHE_DIR / "posts.jsonl"
EXTRACTED_PATH = CACHE_DIR / "extracted.jsonl"


def _load_dotenv() -> None:
    """Put .env into the environment on import.

    run.sh sources .env for the steps it drives, but a module run directly
    (`python -m pipeline.search`, `-m pipeline.notion_status`) got no
    NOTION_TOKEN and bailed. Every documented command now works from a cold
    shell, which is what a new session actually types.
    """
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def log(msg: str) -> None:
    print(msg, flush=True)


# Your own settings. config.yaml is gitignored; copy config.example.yaml to it.
CONFIG_NAMES = ("config.yaml", "groups.yaml")


def config_path() -> Path:
    for name in CONFIG_NAMES:
        if (ROOT / name).exists():
            return ROOT / name
    raise SystemExit(
        "No config.yaml — copy config.example.yaml to config.yaml and fill it in."
    )


def load_config() -> dict:
    with open(config_path()) as f:
        cfg = yaml.safe_load(f)
    cfg.setdefault("listing", {})
    # No household preference unless the config states one, so an unconfigured
    # run labels gender and acts on nothing.
    cfg.setdefault("preferences", {}).setdefault("prefer_gender", "none")
    if cfg.get("groups_registry"):
        cfg["groups"] = load_registry_groups(Path(cfg["groups_registry"]).expanduser())
    w = cfg["window"]
    cfg["window"] = {
        "start": w["start"] if isinstance(w["start"], date) else date.fromisoformat(str(w["start"])),
        "end": w["end"] if isinstance(w["end"], date) else date.fromisoformat(str(w["end"])),
    }
    return cfg


def load_registry_groups(path: Path) -> list:
    """Groups to scrape, from the shared registry (groups/<city>.yaml): every
    active entry marked read: true that has a known id."""
    with open(path) as f:
        reg = yaml.safe_load(f)
    return [
        {"name": g["name"], "slug": str(g["id"]), "method": g.get("method", "forage")}
        for g in reg.get("groups", [])
        if g.get("read") and g.get("id") and g.get("status", "active") == "active"
    ]


def read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    print(f"warning: skipping bad line in {path}", file=sys.stderr)
    return records


def append_jsonl(path: Path, records: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
