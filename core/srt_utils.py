"""SRTパース・ルビ検知・タイムスタンプ厳守でのSRT再構築。

設計上の重要事項:
- AIは絶対にタイムスタンプに触らせない。AIには字幕番号(anchor_index)だけを返させ、
  タイムスタンプはこのモジュール側で原本SRTから引っ張ってくる。
- これにより「Native Vibeの時間ずれ」は構造的に発生しなくなる。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import srt


RUBY_PATTERNS = [
    re.compile(r"《[^》]*》"),
    re.compile(r"\|[^\|]+《[^》]*》"),
    re.compile(r"<ruby>"),
    re.compile(r"<rt>"),
    re.compile(r"\[ruby="),
]


class RubyContaminationError(Exception):
    """Vrewルビ振り後のSRTが渡された時に投げる。"""


@dataclass
class Segment:
    index: int
    start: timedelta
    end: timedelta
    text: str


def parse_srt(srt_text: str) -> list[Segment]:
    subs = list(srt.parse(srt_text))
    return [Segment(index=s.index, start=s.start, end=s.end, text=s.content) for s in subs]


def detect_ruby(srt_text: str) -> list[str]:
    """ルビ記法が混入していたら、検出された記法サンプルを返す。空ならクリーン。"""
    found = []
    for pat in RUBY_PATTERNS:
        m = pat.search(srt_text)
        if m:
            found.append(m.group(0))
    return found


def assert_no_ruby(srt_text: str) -> None:
    found = detect_ruby(srt_text)
    if found:
        raise RubyContaminationError(
            f"このSRTにはルビ記法が混入しています: {found[:3]}\n"
            "Vrewでルビ振りした後のSRTは使えません。"
            "ルビ振り前にダウンロードした日本語SRTを使ってください。"
        )


def segments_to_indexed_lines(segments: list[Segment]) -> str:
    """AIに渡す形式: '[1] テキスト' の行リスト。タイムスタンプは含めない。"""
    return "\n".join(f"[{s.index}] {s.text}" for s in segments)


def build_native_vibe_srt(segments: list[Segment], items: list[dict]) -> str:
    """Native VibeのJSON結果から、原本SRTのタイムスタンプを引いてSRTを構築する。

    items: [{"anchor_index": int, "japanese": str, "english": str, "tip": str}, ...]
    """
    by_index = {s.index: s for s in segments}
    out_subs = []
    for i, item in enumerate(items, start=1):
        anchor = by_index.get(item["anchor_index"])
        if anchor is None:
            continue
        text = f"{item['japanese']}\n{item['english']}\n{item['tip']}"
        out_subs.append(
            srt.Subtitle(index=i, start=anchor.start, end=anchor.end, content=text)
        )
    return srt.compose(out_subs)


def build_jlpt_srt(segments: list[Segment], items: list[dict]) -> str:
    """JLPTのJSON結果から、原本SRTのタイムスタンプを引いてSRTを構築する。

    items: [{"anchor_index": int, "word": str, "reading": str, "meaning": str, "level": str}, ...]
    """
    by_index = {s.index: s for s in segments}
    out_subs = []
    for i, item in enumerate(items, start=1):
        anchor = by_index.get(item["anchor_index"])
        if anchor is None:
            continue
        text = f"{item['word']}（{item['reading']}）\n{item['meaning']} [{item['level']}]"
        out_subs.append(
            srt.Subtitle(index=i, start=anchor.start, end=anchor.end, content=text)
        )
    return srt.compose(out_subs)


def load_srt_file(path: str | Path) -> tuple[str, list[Segment]]:
    """SRTファイル読み込み + ルビ混入チェック。返り値は (raw_text, segments)。"""
    raw = Path(path).read_text(encoding="utf-8-sig")
    assert_no_ruby(raw)
    return raw, parse_srt(raw)
