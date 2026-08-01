#!/usr/bin/env python3
"""Convert PDF (including scanned Chinese pages) to searchable plain text via OCR."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np
from rapidocr_onnxruntime import RapidOCR
from tqdm import tqdm

# Project folders (relative to this script)
ROOT = Path(__file__).resolve().parent
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"

# If a page's embedded text has fewer characters than this, treat it as scanned and OCR.
TEXT_LAYER_MIN_CHARS = 30

# Short lines without clause/sentence punctuation are treated as titles / headers.
TITLE_MAX_LEN = 30
SENTENCE_END_CHARS = set("。！？!?…")
CLAUSE_END_CHARS = set("，、；：,;")
# Strip these after a sentence end before deciding whether the line finished a sentence.
_TRAILING_WRAP = set('”」』"\')）)〕】') | {chr(c) for c in range(0x2460, 0x2474)}  # ①–⑳
_FOOTNOTE_START = {chr(c) for c in range(0x2460, 0x2474)}

_PAGE_MARKER_RE = re.compile(
    r"^===== 第 \d+ 页 =====\s*$",
    re.MULTILINE,
)
_PAGE_NUM_RE = re.compile(r"^\d{1,4}$")
_HEADING_RE = re.compile(
    r"^("
    r"第[一二三四五六七八九十百千零〇两\d]+[章节篇回部卷]"
    r"|[一二三四五六七八九十百]+[、．.]"
    r"|[（(][一二三四五六七八九十百]+[）)]"
    r"|再版前言|前言|序言|序|后记|结语|附录|目录|参考文献"
    r")"
)


def resolve_pdf_path(pdf: Path) -> Path:
    """Resolve PDF path: absolute/relative as given, else fall back to input/."""
    if pdf.is_file():
        return pdf.resolve()
    candidate = INPUT_DIR / pdf.name
    if candidate.is_file():
        return candidate.resolve()
    candidate = INPUT_DIR / pdf
    if candidate.is_file():
        return candidate.resolve()
    return pdf


def default_output_path(pdf_path: Path) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR / f"{pdf_path.stem}.txt"


def _endswith_sentence(text: str) -> bool:
    s = text.rstrip()
    while s and s[-1] in _TRAILING_WRAP:
        s = s[:-1]
    return bool(s) and s[-1] in SENTENCE_END_CHARS


def _needs_space(left: str, right: str) -> bool:
    if not left or not right:
        return False
    a, b = left[-1], right[0]
    return a.isascii() and a.isalnum() and b.isascii() and b.isalnum()


def _join_fragments(parts: list[str]) -> str:
    if not parts:
        return ""
    out = parts[0]
    for nxt in parts[1:]:
        if _needs_space(out, nxt):
            out = f"{out} {nxt}"
        else:
            out = f"{out}{nxt}"
    return out


def is_heading_line(line: str) -> bool:
    """True for chapter/section titles and similar lines that should keep their newline."""
    s = line.strip()
    if not s:
        return False
    if _PAGE_NUM_RE.fullmatch(s):
        return True
    if _HEADING_RE.match(s):
        return True
    # Short standalone titles / running headers (e.g. 再版前言, 大动乱的年代)
    if len(s) <= TITLE_MAX_LEN and s[-1] not in SENTENCE_END_CHARS | CLAUSE_END_CHARS:
        return True
    return False


def merge_ocr_lines(text: str) -> str:
    """
    Merge visual OCR lines into copy-friendly paragraphs.

    - Body lines are joined (no mid-sentence newlines).
    - Chapter/section titles and other short headings keep their own line.
    - A new paragraph starts after sentence-ending punctuation, or at footnotes.
    """
    lines = [ln.strip() for ln in text.splitlines()]
    blocks: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            blocks.append(_join_fragments(buf))
            buf.clear()

    for raw in lines:
        if not raw:
            flush()
            continue

        if is_heading_line(raw):
            flush()
            blocks.append(raw)
            continue

        if raw[0] in _FOOTNOTE_START:
            flush()

        buf.append(raw)
        if _endswith_sentence(raw):
            flush()

    flush()
    return "\n".join(blocks).strip()


def reflow_document(text: str) -> str:
    """Reflow an existing multi-page txt (with ===== 第 N 页 ===== markers)."""
    parts = _PAGE_MARKER_RE.split(text)
    markers = _PAGE_MARKER_RE.findall(text)
    # split → [preamble, body1, body2, ...]; preamble usually empty
    out: list[str] = []
    bodies = parts[1:] if markers else []
    if not markers:
        return merge_ocr_lines(text)

    for marker, body in zip(markers, bodies):
        merged = merge_ocr_lines(body.strip())
        out.append(f"{marker}\n{merged}" if merged else marker)
    return "\n\n".join(out) + "\n"


def extract_text_layer(page: fitz.Page) -> str:
    return (page.get_text("text") or "").strip()


def render_page_to_bgr(page: fitz.Page, dpi: int) -> np.ndarray:
    """Render a PDF page to a BGR numpy array for RapidOCR."""
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    # PyMuPDF gives RGB; RapidOCR / OpenCV expect BGR
    return img[:, :, ::-1].copy()


def ocr_image(engine: RapidOCR, image_bgr: np.ndarray) -> str:
    result, _ = engine(image_bgr)
    if not result:
        return ""
    lines = [item[1] for item in result if item and len(item) >= 2 and item[1]]
    return merge_ocr_lines("\n".join(lines))


def page_to_text(page: fitz.Page, engine: RapidOCR, dpi: int) -> str:
    layer = extract_text_layer(page)
    if len(layer) >= TEXT_LAYER_MIN_CHARS:
        return merge_ocr_lines(layer)
    image = render_page_to_bgr(page, dpi)
    return ocr_image(engine, image)


def convert_pdf(
    pdf_path: Path,
    output_path: Path,
    dpi: int = 200,
    start_page: int = 1,
    max_pages: int | None = None,
) -> int:
    engine = RapidOCR()
    doc = fitz.open(pdf_path)
    try:
        total = len(doc)
        start_idx = max(0, start_page - 1)
        if start_idx >= total:
            raise ValueError(f"起始页 {start_page} 超出总页数 {total}")
        end_idx = total if max_pages is None else min(start_idx + max_pages, total)
        parts: list[str] = []

        for i in tqdm(range(start_idx, end_idx), desc="OCR", unit="page"):
            page = doc[i]
            text = page_to_text(page, engine, dpi)
            parts.append(f"===== 第 {i + 1} 页 =====\n{text}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
        return end_idx - start_idx
    finally:
        doc.close()


def list_input_pdfs() -> list[Path]:
    """All PDF files directly under input/, sorted by name."""
    if not INPUT_DIR.is_dir():
        return []
    return sorted(
        p for p in INPUT_DIR.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"
    )


def collect_pdf_paths(pdf_args: list[Path]) -> list[Path]:
    """
    Resolve PDF list:
    - No args → every *.pdf in input/
    - One or more args → those files (name looked up under input/ if needed)
    """
    if not pdf_args:
        return list_input_pdfs()

    resolved: list[Path] = []
    for arg in pdf_args:
        path = resolve_pdf_path(arg)
        if not path.is_file():
            raise FileNotFoundError(
                f"找不到文件 {arg}（已尝试 input/{Path(arg).name}）"
            )
        if path.suffix.lower() != ".pdf":
            raise ValueError(f"输入必须是 PDF 文件，收到 {path}")
        resolved.append(path)
    return resolved


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="将 PDF（含中文扫描件）转换为可搜索的纯文本 .txt。"
        "不传文件名时，自动转换 input/ 下全部 PDF。",
    )
    parser.add_argument(
        "pdfs",
        type=Path,
        nargs="*",
        default=None,
        help="可选：一个或多个 PDF 文件名/路径；省略则处理 input/ 下全部 PDF",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="输出 .txt 路径（仅单文件时可用；默认：output/<同名>.txt）",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="渲染分辨率，默认 200（越高越清晰也越慢）",
    )
    parser.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="从第 N 页开始（从 1 计，默认 1）",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="最多转换 N 页（调试大文件时有用）",
    )
    parser.add_argument(
        "--reflow",
        type=Path,
        default=None,
        help="不重新 OCR，只对已有 .txt 做段落合并（可与 -o 合用）",
    )
    return parser.parse_args(argv)


def _configure_console_utf8() -> None:
    """Avoid UnicodeEncodeError on Windows consoles (cp1252 etc.)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _resolve_output_arg(args: argparse.Namespace, pdf_path: Path | None) -> Path:
    if args.output:
        output_path = args.output
        if not output_path.is_absolute() and output_path.parent == Path("."):
            output_path = OUTPUT_DIR / output_path.name
        return output_path
    if pdf_path is not None:
        return default_output_path(pdf_path)
    raise ValueError("未指定输出路径")


def main(argv: list[str] | None = None) -> int:
    _configure_console_utf8()
    args = parse_args(argv)

    # Post-process an existing txt without OCR
    if args.reflow is not None:
        src = args.reflow
        if not src.is_file():
            candidate = OUTPUT_DIR / src.name
            if candidate.is_file():
                src = candidate
        if not src.is_file():
            print(f"错误：找不到文件 {args.reflow}", file=sys.stderr)
            return 1
        out = args.output
        if out is None:
            out = src
        elif not out.is_absolute() and out.parent == Path("."):
            out = OUTPUT_DIR / out.name
        text = src.read_text(encoding="utf-8")
        out.write_text(reflow_document(text), encoding="utf-8")
        print(f"已合并换行：{src} → {out}")
        return 0

    if args.dpi < 72:
        print("错误：--dpi 不能小于 72", file=sys.stderr)
        return 1
    if args.start_page < 1:
        print("错误：--start-page 至少为 1", file=sys.stderr)
        return 1
    if args.max_pages is not None and args.max_pages < 1:
        print("错误：--max-pages 至少为 1", file=sys.stderr)
        return 1

    pdf_args = list(args.pdfs or [])
    try:
        pdf_paths = collect_pdf_paths(pdf_args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    if not pdf_paths:
        print(
            f"错误：input/ 下没有 PDF。请把文件放入 {INPUT_DIR} 后运行：python convert.py",
            file=sys.stderr,
        )
        return 1

    if args.output is not None and len(pdf_paths) > 1:
        print(
            "错误：批量转换时不能使用 -o/--output（每个 PDF 会生成同名 .txt）",
            file=sys.stderr,
        )
        return 1

    total_files = len(pdf_paths)
    print(f"待转换：{total_files} 个 PDF")
    print(f"DPI: {args.dpi}  起始页: {args.start_page}", end="")
    if args.max_pages:
        print(f"  最多: {args.max_pages} 页")
    else:
        print()

    failed = 0
    for idx, pdf_path in enumerate(pdf_paths, start=1):
        output_path = (
            _resolve_output_arg(args, pdf_path)
            if args.output is not None
            else default_output_path(pdf_path)
        )
        print(f"\n[{idx}/{total_files}] {pdf_path.name}")
        print(f"  → {output_path}")
        try:
            pages = convert_pdf(
                pdf_path,
                output_path,
                dpi=args.dpi,
                start_page=args.start_page,
                max_pages=args.max_pages,
            )
        except Exception as exc:
            failed += 1
            print(f"  失败：{exc}", file=sys.stderr)
            continue
        print(f"  完成：{pages} 页")

    print(f"\n全部结束：成功 {total_files - failed}/{total_files}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())