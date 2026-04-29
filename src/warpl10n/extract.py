from __future__ import annotations

import logging
import re
from pathlib import Path

from .utils import ContextDict, TranslationDict, posix_path, save_json

log = logging.getLogger(__name__)

STRING_RE = re.compile(r'"((?:\\.|[^"\\])*)"')
PUNCT_ONLY_RE = re.compile(r"^[\s\x20-\x2f\x3a-\x40\x5b-\x60\x7b-\x7e]+$")
LOWER_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
PATH_OR_URL_RE = re.compile(r"(^[./~]|://|^[A-Z]:\\|\\|/|^[\w.-]+\.(rs|toml|json|yaml|yml|md|png|svg|ico|dll|so|dylib)$)")
MIME_RE = re.compile(r"^[a-z]+/[a-z0-9.+-]+$")
ESCAPE_HEAVY_RE = re.compile(r"^(\\[nrtoxu0-9a-fA-F{}()[\];,._ -]+)+$")


def should_extract(text: str) -> bool:
    if not text or not text.strip():
        return False
    if len(text) > 240:
        return False
    if "\0" in text:
        return False
    if not re.search(r"[A-Za-z]", text):
        return False
    if PUNCT_ONLY_RE.match(text):
        return False
    if MIME_RE.match(text):
        return False
    if ESCAPE_HEAVY_RE.match(text):
        return False
    if PATH_OR_URL_RE.search(text):
        return False
    if LOWER_IDENTIFIER_RE.match(text):
        return False
    if re.fullmatch(r"[A-Z0-9_]{2,}", text):
        return False
    if re.fullmatch(r"[a-z0-9_.:-]+", text) and " " not in text:
        return False
    return True


def extract_file(source_root: Path, rel_path: str | Path, context_lines: int = 3) -> tuple[dict[str, str], dict[str, dict]]:
    rel = Path(rel_path)
    fp = source_root / rel
    try:
        content = fp.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        log.warning("failed to read %s: %s", fp, exc)
        return {}, {}

    lines = content.splitlines()
    strings: dict[str, str] = {}
    contexts: dict[str, dict] = {}
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("///") or stripped.startswith("//!"):
            continue
        for match in STRING_RE.finditer(line):
            value = match.group(1)
            if not should_extract(value):
                continue
            strings[value] = ""
            start = max(0, idx - context_lines)
            end = min(len(lines), idx + context_lines + 1)
            contexts[value] = {
                "line": idx + 1,
                "context": "\n".join(lines[start:end]),
            }
    return strings, contexts


def extract_all(
    source_root: str | Path,
    files: list[str | Path],
    output: str | Path = "string.json",
    context_output: str | Path = "string_context.json",
) -> TranslationDict:
    root = Path(source_root)
    result: TranslationDict = {}
    contexts: ContextDict = {}
    for rel in files:
        strings, ctx = extract_file(root, rel)
        if strings:
            key = posix_path(rel)
            result[key] = strings
            contexts[key] = ctx
    save_json(result, output)
    save_json(contexts, context_output)
    log.info("extracted %d files and %d strings", len(result), sum(len(v) for v in result.values()))
    return result

