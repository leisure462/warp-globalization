from __future__ import annotations

from pathlib import Path


def _version_key(value: str) -> list[tuple[int, object]]:
    out: list[tuple[int, object]] = []
    token = ""
    is_digit = False
    for ch in value:
        if ch.isdigit() != is_digit and token:
            out.append((0, int(token)) if is_digit else (1, token))
            token = ""
        token += ch
        is_digit = ch.isdigit()
    if token:
        out.append((0, int(token)) if is_digit else (1, token))
    return out


def select_translation(i18n_root: str | Path, version: str, lang: str) -> Path | None:
    root = Path(i18n_root)
    exact = root / version / f"{lang}.json"
    if exact.exists():
        return exact
    dirs = [p for p in root.iterdir() if p.is_dir()] if root.exists() else []
    versions = sorted((p.name for p in dirs), key=_version_key)
    older = [v for v in versions if v <= version and (root / v / f"{lang}.json").exists()]
    if older:
        return root / older[-1] / f"{lang}.json"
    newer = [v for v in versions if v > version and (root / v / f"{lang}.json").exists()]
    if newer:
        return root / newer[0] / f"{lang}.json"
    flat = root / f"{lang}.json"
    if flat.exists():
        return flat
    return None
