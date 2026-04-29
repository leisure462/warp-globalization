from __future__ import annotations

import logging
import re
from pathlib import Path

from .utils import posix_path, save_json, load_json

log = logging.getLogger(__name__)

INCLUDE_ROOTS = ("app/src", "crates")
EXCLUDED_PARTS = {
    ".git",
    "target",
    "node_modules",
    "fixtures",
    "snapshots",
    "testdata",
    "tests",
    "benches",
}
EXCLUDED_SUFFIXES = ("_test.rs", "_tests.rs", "mod_test.rs", "mod_tests.rs")

CANDIDATE_RE = re.compile(
    r"("
    r"Text::new|text\(|label\(|title\(|tooltip|placeholder|"
    r"BindingDescription::new|with_description|with_custom_description|"
    r"Button|Menu|Dialog|Modal|Toast|SettingsSection|"
    r"menu_item|custom_item|description|header|subheader"
    r")",
    re.IGNORECASE,
)


def _is_under_included_root(path: Path) -> bool:
    normalized = posix_path(path)
    return any(normalized.startswith(root + "/") or normalized == root for root in INCLUDE_ROOTS)


def _is_excluded(path: Path) -> bool:
    parts = set(path.parts)
    if parts & EXCLUDED_PARTS:
        return True
    return path.name.endswith(EXCLUDED_SUFFIXES)


def find_rs_files(source_root: str | Path, scan_mode: str = "heuristic") -> list[Path]:
    root = Path(source_root)
    files: list[Path] = []
    for fp in root.rglob("*.rs"):
        rel = fp.relative_to(root)
        if not _is_under_included_root(rel) or _is_excluded(rel):
            continue
        if scan_mode == "all":
            files.append(rel)
            continue
        try:
            content = fp.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if CANDIDATE_RE.search(content):
            files.append(rel)
    files = sorted(files, key=lambda p: posix_path(p))
    log.info("scan selected %d Rust files (%s mode)", len(files), scan_mode)
    return files


def save_scan_result(path: str | Path, version: str, files: list[Path | str]) -> None:
    save_json(
        {
            "version": version,
            "files": [posix_path(f) for f in files],
        },
        path,
    )


def load_scan_result(path: str | Path) -> dict:
    return load_json(path, default={"version": "", "files": []})

