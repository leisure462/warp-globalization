from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

TranslationDict = dict[str, dict[str, str]]
ContextDict = dict[str, dict[str, dict[str, Any]]]


@dataclass
class AIConfig:
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    concurrency: int = 8
    rpm: int = -1

    def __post_init__(self) -> None:
        self.base_url = self.base_url or os.getenv("AI_BASE_URL") or "https://api.openai.com/v1"
        self.api_key = self.api_key or os.getenv("AI_API_KEY", "")
        self.model = self.model or os.getenv("AI_MODEL") or "gpt-4o-mini"
        if self.concurrency <= 0:
            raw = os.getenv("AI_CONCURRENCY", "8")
            self.concurrency = int(raw) if raw.isdigit() else 8
        if self.rpm < 0:
            raw = os.getenv("AI_RPM", "60")
            self.rpm = int(raw) if raw.isdigit() else 60

    def validate(self) -> None:
        if not self.api_key:
            raise SystemExit("AI_API_KEY is required. Set it as a secret or pass --api-key.")


class RateLimiter:
    def __init__(self, rpm: int) -> None:
        self.interval = 0.0 if rpm <= 0 else 60.0 / rpm
        self._lock = threading.Lock()
        self._next_time = 0.0

    def wait(self) -> None:
        if self.interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            if now < self._next_time:
                time.sleep(self._next_time - now)
                now = time.monotonic()
            self._next_time = now + self.interval


class Progress:
    def __init__(self, total: int, label: str) -> None:
        self.total = max(total, 1)
        self.label = label
        self.done = 0
        self.start = time.time()

    def step(self, extra: str = "") -> None:
        self.done += 1
        elapsed = int(time.time() - self.start)
        msg = f"\r{self.label}: {self.done}/{self.total} {elapsed}s"
        if extra:
            msg += f" | {extra}"
        sys.stderr.write(msg + "\033[K")
        sys.stderr.flush()

    def finish(self) -> None:
        sys.stderr.write("\n")
        sys.stderr.flush()


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)


def load_json(path: str | Path, default: Any | None = None) -> Any:
    p = Path(path)
    if not p.exists():
        if default is not None:
            return default
        raise FileNotFoundError(path)
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: Any, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        f.write("\n")


def load_yaml(path: str | Path) -> Any:
    p = Path(path)
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def posix_path(path: str | Path) -> str:
    return str(path).replace("\\", "/")


def normalize_fullwidth(text: str) -> str:
    return text.translate(str.maketrans({chr(c): chr(c - 0xFEE0) for c in range(0xFF01, 0xFF5F)}))


def parse_json_response(raw: str) -> dict[str, str]:
    candidates: list[str] = [raw]
    block = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    if block:
        candidates.append(block.group(1).strip())
    obj = re.search(r"\{.*\}", raw, re.DOTALL)
    if obj:
        candidates.append(obj.group(0))
    for text in candidates:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items()}
    return {}


def parse_numbered_response(raw: str, keys: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    pattern = re.compile(r"\[##(\d+)##\](.*?)(?=\[##\d+##\]|\Z)", re.DOTALL)
    for match in pattern.finditer(raw):
        idx = int(match.group(1)) - 1
        if 0 <= idx < len(keys):
            result[keys[idx]] = match.group(2).strip()
    return result


def extract_placeholders(text: str) -> list[str]:
    masked = text.replace("{{", "\x00").replace("}}", "\x01")
    rust = re.findall(r"\{[^{}]*\}", masked)
    c_style = [m for m in re.findall(r"%(?:l{0,2}[diouxXeEfgGcs]|zu|[%])", masked) if m != "%%"]
    return rust + c_style


def placeholders_match(src: str, dst: str) -> bool:
    def positional(items: list[str]) -> list[str]:
        out: list[str] = []
        for item in items:
            if item.startswith("%"):
                out.append(item)
            else:
                inner = item[1:-1]
                if inner == "" or inner.startswith(":"):
                    out.append(item)
        return out

    src_ph = extract_placeholders(src)
    dst_ph = extract_placeholders(dst)
    if positional(src_ph) != positional(dst_ph):
        return False
    src_named = sorted(p for p in src_ph if p not in positional(src_ph))
    dst_named = sorted(p for p in dst_ph if p not in positional(dst_ph))
    return src_named == dst_named


def build_glossary(path: str | Path) -> str:
    data = load_yaml(path)
    lines: list[str] = []
    terms = data.get("terms", {})
    if terms:
        lines.append("Glossary. Follow these translations exactly:")
        for en, zh in terms.items():
            lines.append(f"- {en}: {zh}")
    keep = data.get("keep_original", [])
    if keep:
        lines.append("Keep these terms unchanged:")
        lines.append(", ".join(keep))
    return "\n".join(lines)
