"""保守清理文本格式，不改写新闻事实或删除非重复段落。"""
from __future__ import annotations

import html
import re
import unicodedata


_PROMOTION_PATTERNS = (
    re.compile(r"^\s*follow\s+(?:the\s+)?(?:director|cbp|us|our)\b", re.IGNORECASE),
    re.compile(r"^\s*connect with (?:cbp|us)\b", re.IGNORECASE),
    re.compile(r"^\s*breaking news,?\s+current events,?\s+human interest stories", re.IGNORECASE),
)


def is_promotional_paragraph(paragraph: str) -> bool:
    """识别正文末尾的账号关注和社交媒体推广段。"""
    return any(pattern.search(paragraph) for pattern in _PROMOTION_PATTERNS)


def clean_article_text(content: str) -> str:
    """规范空白和编码字符，并移除相邻的完全重复段落。"""
    normalized = unicodedata.normalize("NFC", html.unescape(content or ""))
    normalized = normalized.replace("\u00a0", " ").replace("\u200b", "")
    paragraphs: list[str] = []
    for raw_paragraph in re.split(r"\n\s*\n|\r\n?|\u2028|\u2029", normalized):
        paragraph = re.sub(r"[\t\f\v ]+", " ", raw_paragraph).strip()
        if paragraph and is_promotional_paragraph(paragraph):
            break
        if paragraph and (not paragraphs or paragraph != paragraphs[-1]):
            paragraphs.append(paragraph)
    return "\n\n".join(paragraphs)
