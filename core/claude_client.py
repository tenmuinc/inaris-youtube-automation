"""Claude APIラッパー: Native Vibe / JLPT / 多言語タイトルを生成する。

設計の肝:
- AIには字幕番号(anchor_index)だけ返させる。タイムスタンプには触らせない。
- システムプロンプト(prompts/*.md)はprompt cachingでキャッシュする。
- 入出力ともに純粋JSONで型を縛る。
"""

from __future__ import annotations

import json

import anthropic

from .srt_utils import Segment, segments_to_indexed_lines


class ClaudeClient:
    def __init__(
        self,
        api_key: str,
        prompts: dict[str, str],
        model: str = "claude-sonnet-4-6",
    ):
        """prompts: {"native_vibe": "...", "jlpt": "...", "multilingual_titles": "..."}"""
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.prompts = prompts

    def _generate_json(self, system_prompt: str, user_content: str, max_tokens: int = 16000) -> dict:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_content}],
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.rsplit("```", 1)[0]
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"ClaudeのJSON応答をパースできませんでした: {e}\n受信内容: {text[:500]}"
            ) from e

    def generate_native_vibe(self, segments: list[Segment]) -> list[dict]:
        result = self._generate_json(
            self.prompts["native_vibe"], segments_to_indexed_lines(segments)
        )
        return result.get("items", [])

    def generate_jlpt(self, segments: list[Segment]) -> list[dict]:
        result = self._generate_json(
            self.prompts["jlpt"], segments_to_indexed_lines(segments)
        )
        return result.get("items", [])

    def generate_multilingual_titles(self, segments: list[Segment]) -> dict:
        return self._generate_json(
            self.prompts["multilingual_titles"], segments_to_indexed_lines(segments)
        )
