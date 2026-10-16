"""The library: published study packages in this repository plus studies in other repositories listed in registry.json.

No server. Everything is a file in GitHub; remote studies are read from raw.githubusercontent.com with a short cache.
A registry entry is only a pointer: {"repo": "owner/name", "path": "studies/slug", "ref": "main"}.
"""
from __future__ import annotations

import io
import json
import time
from pathlib import Path

import httpx
import pandas as pd

RAW = "https://raw.githubusercontent.com"
_CACHE: dict[str, tuple[float, object]] = {}
TTL = 600


def _card(study: dict, where: str) -> dict:
    ests = study.get("estimates", [])
    conf = [e for e in ests if e.get("confirmatory")]
    return {"slug": study.get("slug"), "title": study.get("title"), "authors": study.get("authors", []),
            "created": study.get("created"), "design": study.get("design"), "n": study.get("n_analysis"),
            "constructs": study.get("constructs", []), "verdicts": study.get("verdicts", {}),
            "n_confirmatory": len(conf), "timing_status": study.get("timing_status"),
            "verified": bool((study.get("verification") or {}).get("ok")), "data_included": study.get("data_included", False),
            "summary": study.get("summary", ""), "where": where, "repo": study.get("repo", ""), "estimates": ests}


def scan_local(root: str | Path) -> list[dict]:
    cards = []
    for p in sorted(Path(root).glob("*/study.json")):
        try:
            cards.append(_card(json.loads(p.read_text(encoding="utf-8")), str(p.parent)))
        except (ValueError, OSError):
            continue
    return cards


def local_effects(root: str | Path) -> pd.DataFrame:
    frames = []
    for p in sorted(Path(root).glob("*/results/effects.csv")):
        d = pd.read_csv(p)
        d.insert(0, "study", p.parent.parent.name)
        frames.append(d)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _get(url: str, client: httpx.Client | None, ttl: int = TTL) -> bytes | None:
    now = time.time()
    hit = _CACHE.get(url)
    if hit and now - hit[0] < ttl:
        return hit[1]  # type: ignore[return-value]
    try:
        r = (client or httpx).get(url, timeout=10, follow_redirects=True)
    except httpx.HTTPError:
        return None
    data = r.content if r.status_code == 200 else None
    _CACHE[url] = (now, data)
    return data


def fetch_remote(entry: dict, client: httpx.Client | None = None) -> tuple[dict | None, pd.DataFrame | None]:
    base = f"{RAW}/{entry['repo']}/{entry.get('ref', 'main')}/{entry['path'].strip('/')}"
    s = _get(f"{base}/study.json", client)
    if not s:
        return None, None
    try:
        study = json.loads(s)
    except ValueError:
        return None, None
    e = _get(f"{base}/results/effects.csv", client)
    eff = pd.read_csv(io.BytesIO(e)) if e else None
    if eff is not None:
        eff.insert(0, "study", f"{entry['repo']}:{study.get('slug')}")
    return study, eff


def load_registry(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    try:
        return [e for e in json.loads(p.read_text()).get("studies", []) if e.get("repo") and e.get("path")]
    except ValueError:
        return []


def remote_cards(entries: list[dict], client: httpx.Client | None = None) -> tuple[list[dict], pd.DataFrame, list[str]]:
    cards, frames, broken = [], [], []
    for e in entries:
        study, eff = fetch_remote(e, client)
        if study is None:
            broken.append(f"{e['repo']}/{e['path']}")
            continue
        cards.append(_card(study, f"https://github.com/{e['repo']}/tree/{e.get('ref', 'main')}/{e['path'].strip('/')}"))
        if eff is not None:
            frames.append(eff)
    return cards, (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), broken


def similar(card: dict, cards: list[dict], n: int = 5) -> list[tuple[float, dict]]:
    """Jaccard overlap of constructs, plus a small bonus for the same design."""
    a = {c.lower() for c in card.get("constructs", [])}
    out = []
    for o in cards:
        if o["slug"] == card["slug"]:
            continue
        b = {c.lower() for c in o.get("constructs", [])}
        j = len(a & b) / len(a | b) if (a | b) else 0.0
        score = j + (0.1 if o.get("design") == card.get("design") else 0.0)
        if score > 0.1:
            out.append((round(score, 3), o))
    return sorted(out, key=lambda t: -t[0])[:n]


def registry_entry(repo: str, slug: str, ref: str = "main") -> dict:
    return {"repo": repo, "path": f"studies/{slug}", "ref": ref}
