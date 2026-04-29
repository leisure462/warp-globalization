from __future__ import annotations

import logging
import re
from pathlib import Path

from .utils import TranslationDict, load_json, normalize_fullwidth, placeholders_match

log = logging.getLogger(__name__)

PUNCT_ONLY_RE = re.compile(r"^[\s\x20-\x2f\x3a-\x40\x5b-\x60\x7b-\x7e]+$")
LOWER_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
URL_OR_PATH_RE = re.compile(r"(^[./~]|://|^[A-Z]:\\|\\|/)")
MIME_RE = re.compile(r"^[a-z]+/[a-z0-9.+-]+$")
PROTECTED_RE = re.compile(
    r'br(#+)".*?"\1'
    r'|br"(?:[^"\\]|\\.)*"'
    r'|b"(?:[^"\\]|\\.)*"'
    r'|r(#+)".*?"\2'
    r'|r"(?:[^"\\]|\\.)*"'
    r'|#\[(?!error\b)[\w:]+\([^]]*?\)\]',
    re.DOTALL,
)
PROTECTED_BLOCK_MARKERS = (
    "impl FromStr for SettingsSection",
)
ZH_PUNCT_BETWEEN_STRINGS_RE = re.compile(r'(?<=\w")\s*[、，]\s*(?=")')
ZH_SEMICOLON_BETWEEN_STRINGS_RE = re.compile(r'(?<=\w")\s*[；]\s*(?=")')
RUST_ESCAPES = frozenset('nrtx0u\\"\'')

_file_do_not_translate: set[tuple[str, str]] = set()
_global_do_not_translate: set[str] = set()


def load_do_not_translate(path: str | Path) -> None:
    global _file_do_not_translate, _global_do_not_translate
    data = load_json(path, default={})
    _file_do_not_translate = {
        (entry.get("file", ""), entry.get("original", ""))
        for entry in data.get("entries", [])
        if entry.get("original")
    }
    _global_do_not_translate = {
        entry.get("original", "")
        for entry in data.get("global_entries", [])
        if entry.get("original")
    }
    log.info(
        "loaded do-not-translate rules: %d file rules, %d global rules",
        len(_file_do_not_translate),
        len(_global_do_not_translate),
    )


def _escape_for_rust(value: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\\":
            nxt = value[i + 1] if i + 1 < len(value) else ""
            if nxt in RUST_ESCAPES:
                out.append("\\")
                out.append(nxt)
                i += 2
                continue
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _protected_ranges(content: str) -> list[tuple[int, int]]:
    ranges = [(match.start(), match.end()) for match in PROTECTED_RE.finditer(content)]
    ranges.extend(_protected_block_ranges(content))
    return ranges


def _protected_block_ranges(content: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for marker in PROTECTED_BLOCK_MARKERS:
        search_from = 0
        while True:
            marker_pos = content.find(marker, search_from)
            if marker_pos == -1:
                break
            open_brace = content.find("{", marker_pos)
            if open_brace == -1:
                break
            depth = 0
            end = None
            for idx in range(open_brace, len(content)):
                ch = content[idx]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = idx + 1
                        break
            if end is None:
                break
            ranges.append((marker_pos, end))
            search_from = end
    return ranges


def _replace_outside_ranges(content: str, old: str, new: str, ranges: list[tuple[int, int]]) -> tuple[str, int]:
    if not ranges:
        return content.replace(old, new), content.count(old)
    out: list[str] = []
    count = 0
    pos = 0
    while True:
        idx = content.find(old, pos)
        if idx == -1:
            out.append(content[pos:])
            break
        out.append(content[pos:idx])
        if any(start <= idx < end for start, end in ranges):
            out.append(old)
        else:
            out.append(new)
            count += 1
        pos = idx + len(old)
    return "".join(out), count


def _skip(original: str, translated: str, file_path: str) -> bool:
    if not translated or translated == original:
        return True
    if original in _global_do_not_translate or (file_path, original) in _file_do_not_translate:
        return True
    if PUNCT_ONLY_RE.match(original) or LOWER_IDENTIFIER_RE.match(original):
        return True
    if MIME_RE.match(original) or URL_OR_PATH_RE.search(original):
        return True
    if not placeholders_match(original, translated):
        log.warning("placeholder mismatch, skipped: %r -> %r", original, translated)
        return True
    return False


def _resolve_path(source_root: Path, file_path: str) -> Path | None:
    candidate = source_root / file_path
    if candidate.exists():
        return candidate
    p = Path(file_path)
    if p.is_absolute() and p.exists():
        return p
    if p.exists():
        return p
    log.warning("missing source file: %s", file_path)
    return None


def replace_in_source(translations: TranslationDict, source_root: str | Path = ".") -> int:
    root = Path(source_root)
    total = 0
    for file_path, mapping in translations.items():
        fp = _resolve_path(root, file_path)
        if fp is None:
            continue
        try:
            content = fp.read_text(encoding="utf-8")
        except OSError as exc:
            log.warning("failed to read %s: %s", fp, exc)
            continue
        ranges = _protected_ranges(content)
        count = 0
        for original, translated in mapping.items():
            translated = normalize_fullwidth(translated)
            if _skip(original, translated, file_path):
                continue
            old = f'"{original}"'
            new = f'"{_escape_for_rust(translated)}"'
            content, changed = _replace_outside_ranges(content, old, new, ranges)
            if changed:
                count += changed
                ranges = _protected_ranges(content)
        if count:
            content = ZH_PUNCT_BETWEEN_STRINGS_RE.sub(", ", content)
            content = ZH_SEMICOLON_BETWEEN_STRINGS_RE.sub("; ", content)
            fp.write_text(content, encoding="utf-8", newline="\n")
            log.info("replaced %d strings in %s", count, file_path)
            total += count
    log.info("replacement complete: %d occurrences", total)
    return total


def run_replace(input_path: str | Path, source_root: str | Path, do_not_translate: str | Path = "") -> int:
    if do_not_translate:
        load_do_not_translate(do_not_translate)
    translations: TranslationDict = load_json(input_path)
    return replace_in_source(translations, source_root)
