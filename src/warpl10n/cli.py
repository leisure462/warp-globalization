from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .utils import AIConfig, load_json, setup_logging


def _add_ai_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", default="", help="OpenAI-compatible base URL")
    parser.add_argument("--api-key", default="", help="OpenAI-compatible API key")
    parser.add_argument("--model", default="", help="model name")
    parser.add_argument("--concurrency", type=int, default=0, help="translation concurrency")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="warpl10n")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")

    p_extract = sub.add_parser("extract", help="scan Warp source and extract strings")
    p_extract.add_argument("--source-root", required=True)
    p_extract.add_argument("--output", default="string.json")
    p_extract.add_argument("--context-output", default="string_context.json")
    p_extract.add_argument("--scan-result", default="scan_result.json")
    p_extract.add_argument("--version", default="unknown")
    p_extract.add_argument("--scan-mode", choices=["heuristic", "all"], default="heuristic")
    p_extract.add_argument("--files", nargs="*")

    p_translate = sub.add_parser("translate", help="translate extracted strings")
    p_translate.add_argument("--input", required=True)
    p_translate.add_argument("--output", required=True)
    p_translate.add_argument("--context", default="string_context.json")
    p_translate.add_argument("--glossary", default="config/glossary.yaml")
    p_translate.add_argument("--lang", default="zh-CN")
    p_translate.add_argument("--mode", choices=["incremental", "full"], default="incremental")
    p_translate.add_argument("--batch-size", type=int, default=30)
    _add_ai_args(p_translate)

    p_pipeline = sub.add_parser("pipeline", help="extract and translate")
    p_pipeline.add_argument("--source-root", required=True)
    p_pipeline.add_argument("--version", default="unknown")
    p_pipeline.add_argument("--lang", default="zh-CN")
    p_pipeline.add_argument("--mode", choices=["incremental", "full"], default="incremental")
    p_pipeline.add_argument("--scan-mode", choices=["heuristic", "all"], default="heuristic")
    p_pipeline.add_argument("--glossary", default="config/glossary.yaml")
    _add_ai_args(p_pipeline)

    p_replace = sub.add_parser("replace", help="replace strings in Warp source")
    p_replace.add_argument("--input", required=True)
    p_replace.add_argument("--source-root", default=".")
    p_replace.add_argument("--do-not-translate", default="")

    p_validate = sub.add_parser("validate", help="validate translation placeholders")
    p_validate.add_argument("--input", required=True)

    p_select = sub.add_parser("select-translation", help="select best translation JSON")
    p_select.add_argument("--i18n-root", default="i18n")
    p_select.add_argument("--version", required=True)
    p_select.add_argument("--lang", default="zh-CN")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    setup_logging(args.verbose)
    if not args.command:
        parser.print_help()
        return

    if args.command == "extract":
        from .extract import extract_all
        from .scan import find_rs_files, save_scan_result

        if args.files:
            files = [Path(f) for f in args.files]
        else:
            files = find_rs_files(args.source_root, args.scan_mode)
        save_scan_result(args.scan_result, args.version, files)
        extract_all(args.source_root, files, args.output, args.context_output)

    elif args.command == "translate":
        from .translate import translate_all

        cfg = AIConfig(args.base_url, args.api_key, args.model, args.concurrency)
        translate_all(
            args.input,
            args.output,
            args.context,
            args.glossary,
            args.lang,
            args.mode,
            args.batch_size,
            cfg,
        )

    elif args.command == "pipeline":
        from .extract import extract_all
        from .scan import find_rs_files, save_scan_result
        from .translate import translate_all

        files = find_rs_files(args.source_root, args.scan_mode)
        save_scan_result("scan_result.json", args.version, files)
        extract_all(args.source_root, files, "string.json", "string_context.json")
        output = f"i18n/{args.version}/{args.lang}.json"
        cfg = AIConfig(args.base_url, args.api_key, args.model, args.concurrency)
        translate_all("string.json", output, "string_context.json", args.glossary, args.lang, args.mode, 30, cfg)

    elif args.command == "replace":
        from .replace import run_replace

        run_replace(args.input, args.source_root, args.do_not_translate)

    elif args.command == "validate":
        from .validate import validate_translation

        errors = validate_translation(args.input)
        sys.exit(1 if errors else 0)

    elif args.command == "select-translation":
        from .select_translation import select_translation

        selected = select_translation(args.i18n_root, args.version, args.lang)
        if not selected:
            raise SystemExit(f"no translation file found for {args.version} {args.lang}")
        print(selected.as_posix())


if __name__ == "__main__":
    main()

