from __future__ import annotations

import logging
from pathlib import Path

from .utils import TranslationDict, load_json, placeholders_match

log = logging.getLogger(__name__)


def validate_translation(path: str | Path) -> int:
    data: TranslationDict = load_json(path)
    errors = 0
    empty = 0
    for file_path, mapping in data.items():
        for original, translated in mapping.items():
            if not translated:
                empty += 1
                continue
            if not placeholders_match(original, translated):
                errors += 1
                log.error("placeholder mismatch in %s: %r -> %r", file_path, original, translated)
    log.info("validation complete: %d placeholder errors, %d empty translations", errors, empty)
    return errors

