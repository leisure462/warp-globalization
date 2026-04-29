from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .utils import (
    AIConfig,
    Progress,
    TranslationDict,
    build_glossary,
    load_json,
    parse_json_response,
    parse_numbered_response,
    placeholders_match,
    save_json,
)

log = logging.getLogger(__name__)


def _chunks(items: list[tuple[str, str, str]], size: int) -> list[list[tuple[str, str, str]]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _build_prompt(lang: str, glossary: str, items: list[tuple[str, str, str]]) -> str:
    numbered = []
    for index, (file_path, source, context) in enumerate(items, 1):
        numbered.append(
            f"[{index}]\nfile: {file_path}\nsource: {source}\ncontext:\n{context[:1600]}\n"
        )
    return f"""You are localizing the Warp terminal app UI to {lang}.

Rules:
- Translate user-visible English UI text naturally.
- Preserve placeholders exactly: {{}}, {{name}}, {{0}}, {{:?}}, %s, %d, etc.
- Preserve product names, model names, file paths, URLs, shell commands, environment variables, JSON keys, and code identifiers.
- Keep keyboard shortcuts and command names readable.
- Return only a JSON object whose keys are the original source strings and whose values are translations.
- Do not add or remove keys.

{glossary}

Items:
{''.join(numbered)}
"""


def _translate_batch(
    batch: list[tuple[str, str, str]],
    lang: str,
    glossary: str,
    ai_cfg: AIConfig,
) -> dict[str, str]:
    from openai import OpenAI

    client = OpenAI(base_url=ai_cfg.base_url, api_key=ai_cfg.api_key)
    keys = [source for _, source, _ in batch]
    prompt = _build_prompt(lang, glossary, batch)
    response = client.chat.completions.create(
        model=ai_cfg.model,
        temperature=0.1,
        messages=[
            {"role": "system", "content": "You are a precise software localization engine."},
            {"role": "user", "content": prompt},
        ],
    )
    raw = response.choices[0].message.content or ""
    parsed = parse_json_response(raw)
    if not parsed:
        parsed = parse_numbered_response(raw, keys)
    clean: dict[str, str] = {}
    for key in keys:
        value = parsed.get(key, "").strip()
        if not value:
            continue
        if not placeholders_match(key, value):
            log.warning("placeholder mismatch, keeping untranslated: %r -> %r", key, value)
            continue
        clean[key] = value
    return clean


def translate_all(
    input_path: str | Path,
    output_path: str | Path,
    context_path: str | Path = "",
    glossary_path: str | Path = "config/glossary.yaml",
    lang: str = "zh-CN",
    mode: str = "incremental",
    batch_size: int = 30,
    ai_cfg: AIConfig | None = None,
) -> TranslationDict:
    ai_cfg = ai_cfg or AIConfig()
    ai_cfg.validate()
    source: TranslationDict = load_json(input_path)
    output: TranslationDict = load_json(output_path, default={})
    contexts = load_json(context_path, default={}) if context_path else {}
    glossary = build_glossary(glossary_path)

    pending: list[tuple[str, str, str]] = []
    for file_path, strings in source.items():
        output.setdefault(file_path, {})
        for original in strings:
            existing = output[file_path].get(original, "")
            if mode == "incremental" and existing:
                continue
            ctx = contexts.get(file_path, {}).get(original, {}).get("context", "")
            pending.append((file_path, original, ctx))

    if not pending:
        log.info("nothing to translate")
        save_json(output, output_path)
        return output

    batches = _chunks(pending, batch_size)
    progress = Progress(len(batches), "translate")
    with ThreadPoolExecutor(max_workers=ai_cfg.concurrency) as executor:
        futures = {
            executor.submit(_translate_batch, batch, lang, glossary, ai_cfg): batch
            for batch in batches
        }
        for future in as_completed(futures):
            batch = futures[future]
            try:
                translated = future.result()
            except Exception as exc:
                log.error("translation batch failed: %s", exc)
                translated = {}
            for file_path, original, _ctx in batch:
                output.setdefault(file_path, {})
                if original in translated:
                    output[file_path][original] = translated[original]
                else:
                    output[file_path].setdefault(original, "")
            save_json(output, output_path)
            progress.step(f"{len(translated)}/{len(batch)}")
    progress.finish()
    log.info("translation written to %s", output_path)
    return output

