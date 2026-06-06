#!/usr/bin/env python3
"""Command-line interface for the OCR system.

Examples:
    python cli.py ocr scan.png --lang eng+ara
    python cli.py ocr scan.png --lang ara --output result.txt
    python cli.py anpr car.jpg
    python cli.py kyc passport.jpg --json
    python cli.py info
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app import config
from app.core import engine
from app.features import anpr, kyc


def _read(path: str) -> bytes:
    p = Path(path)
    if not p.exists():
        sys.exit(f"error: file not found: {path}")
    return p.read_bytes()


def cmd_info(_: argparse.Namespace) -> None:
    print(f"Tesseract path     : {config.TESSERACT_PATH or 'NOT FOUND'}")
    print(f"Tesseract version  : {config.tesseract_version() or 'n/a'}")
    print(f"Installed languages: {', '.join(config.available_languages()) or 'n/a'}")


def cmd_ocr(args: argparse.Namespace) -> None:
    result = engine.run_ocr_bytes(
        _read(args.image), lang=args.lang, psm=args.psm,
        preprocess_image=not args.no_preprocess,
    )
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(result.text)
        print(f"\n[mean confidence: {result.mean_confidence:.1f}% · {len(result.words)} words]",
              file=sys.stderr)
    if args.output:
        Path(args.output).write_text(result.text, encoding="utf-8")
        print(f"saved -> {args.output}", file=sys.stderr)


def cmd_anpr(args: argparse.Namespace) -> None:
    result = anpr.recognize_plate(_read(args.image))
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    elif result.best:
        print(f"{result.best.text}  ({result.best.confidence:.1f}%)")
    else:
        print("no plate detected", file=sys.stderr)
        sys.exit(2)


def cmd_kyc(args: argparse.Namespace) -> None:
    result = kyc.extract_identity(_read(args.image), lang=args.lang)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ocr", description="Tesseract OCR system (AR/EN, ANPR, KYC).")
    sub = parser.add_subparsers(dest="command", required=True)

    p_info = sub.add_parser("info", help="Show engine / language status.")
    p_info.set_defaults(func=cmd_info)

    p_ocr = sub.add_parser("ocr", help="Extract text from an image.")
    p_ocr.add_argument("image")
    p_ocr.add_argument("--lang", default=config.DEFAULT_LANGUAGE)
    p_ocr.add_argument("--psm", type=int, default=3)
    p_ocr.add_argument("--no-preprocess", action="store_true")
    p_ocr.add_argument("--output", "-o")
    p_ocr.add_argument("--json", action="store_true")
    p_ocr.set_defaults(func=cmd_ocr)

    p_anpr = sub.add_parser("anpr", help="Recognize a vehicle license plate.")
    p_anpr.add_argument("image")
    p_anpr.add_argument("--json", action="store_true")
    p_anpr.set_defaults(func=cmd_anpr)

    p_kyc = sub.add_parser("kyc", help="Extract identity fields from an ID document.")
    p_kyc.add_argument("image")
    p_kyc.add_argument("--lang", default=config.DEFAULT_LANGUAGE)
    p_kyc.set_defaults(func=cmd_kyc)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        args.func(args)
    except engine.TesseractNotInstalled as exc:
        sys.exit(f"error: {exc}")


if __name__ == "__main__":
    main()
