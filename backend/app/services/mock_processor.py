"""本地模拟改写：不发出网络请求，也不声称生成了真实 AI 内容。"""
from __future__ import annotations

import json


def build_mock_result(title: str, cleaned_content: str, prompt_name: str, prompt_version: int) -> tuple[str, str, str]:
    """生成可用于验证保存流程的标记结果，正文事实保持原样。"""
    marked_title = f"[模拟处理] {title}"
    marked_content = f"[模拟处理结果：未调用真实模型；提示词 {prompt_name} v{prompt_version}]\n\n{cleaned_content}"
    metadata = json.dumps({"mode": "mock", "prompt_name": prompt_name,
                           "prompt_version": prompt_version}, ensure_ascii=False)
    return marked_title, marked_content, metadata


def build_mock_translation(cleaned_content: str) -> str:
    """生成明确标记的本地占位译文，避免误以为已经调用翻译模型。"""
    return "[模拟翻译占位：尚未调用模型，以下仍为英文清洗稿]\n\n" + cleaned_content
