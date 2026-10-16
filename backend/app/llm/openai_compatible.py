"""通过 LangChain 调用 OpenAI 兼容格式的模型中转站。"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, ValidationError


BACKEND_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_ROOT / ".env")


class TranslationOutput(BaseModel):
    translated_content: str = Field(min_length=1, description="完整的中文翻译")


class RewriteOutput(BaseModel):
    title: str = Field(min_length=1, description="中文新闻标题")
    content: str = Field(min_length=1, description="中文改写正文")


def llm_configuration() -> tuple[str, str, str]:
    """读取连接参数，不在错误消息或日志里暴露 API Key。"""
    base_url = os.getenv("LLM_BASE_URL", "").strip()
    api_key = os.getenv("LLM_API_KEY", "").strip()
    model = os.getenv("LLM_MODEL", "gpt-6-luna").strip()
    missing = [name for name, value in (
        ("LLM_BASE_URL", base_url), ("LLM_API_KEY", api_key), ("LLM_MODEL", model)
    ) if not value]
    if missing:
        raise RuntimeError("请先在 backend/.env 中配置：" + ", ".join(missing))
    return base_url, api_key, model


@lru_cache(maxsize=4)
def _make_chat_model(base_url: str, api_key: str, model: str) -> ChatOpenAI:
    return ChatOpenAI(
        base_url=base_url,
        api_key=api_key,
        model=model,
        temperature=0,
        timeout=90,
        max_retries=1,
    )


def _message_text(result: Any) -> str:
    content = getattr(result, "content", result)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        ).strip()
    return str(content).strip()


def _parse_output(text: str, schema: type[BaseModel]) -> BaseModel:
    """兼容模型返回纯 JSON 或 Markdown JSON 代码块，并由 Pydantic 校验字段。"""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    try:
        return schema.model_validate_json(cleaned)
    except (ValidationError, ValueError) as exc:
        raise ValueError("模型返回内容不是要求的有效 JSON，请检查中转站模型兼容性") from exc


def _invoke(system_prompt: str, user_prompt: str) -> str:
    base_url, api_key, model = llm_configuration()
    response = _make_chat_model(base_url, api_key, model).invoke([
        ("system", system_prompt),
        ("human", user_prompt),
    ])
    return _message_text(response)


def translate_article(system_prompt: str, user_prompt: str, english_content: str) -> tuple[str, str]:
    request = (
        f"{user_prompt.strip()}\n\n"
        "请把下面的英文新闻完整翻译为自然、通顺、符合中国读者阅读习惯的简体中文，避免逐词直译和生硬的英文语序。"
        "可以使用地道的中文新闻表达，但必须保持事实、数字、日期、地点、机构名称不变，不得增加原文没有的信息。"
        "只返回 JSON：{\"translated_content\": \"完整译文\"}。\n\n"
        f"英文正文：\n{english_content}"
    )
    raw = _invoke(system_prompt, request)
    parsed = _parse_output(raw, TranslationOutput)
    return parsed.translated_content, raw


def rewrite_article(
    system_prompt: str, user_prompt: str, original_title: str, translated_content: str
) -> tuple[str, str, str]:
    request = (
        f"{user_prompt.strip()}\n\n"
        "请以第三方新闻稿的角度改写标题和正文，先写客观、简洁的新闻导语，再展开事件经过和相关事实，"
        "不要像逐句朗读原文，也不要使用机构第一人称。语言要自然、简洁、接地气，符合中国新闻资讯的表达习惯。"
        "只有原文明确提供时间时，才可以使用‘近日’、‘当地时间’等时间表达；没有明确时间时不得自行补充。"
        "不得改变事实、数字、日期、地点、机构和政策内容，不得补充原文没有的信息。"
        "只返回 JSON：{\"title\": \"标题\", \"content\": \"正文\"}。\n\n"
        f"英文原标题（供理解，不要自行补充事实）：\n{original_title}\n\n"
        f"中文译文：\n{translated_content}"
    )
    raw = _invoke(system_prompt, request)
    parsed = _parse_output(raw, RewriteOutput)
    return parsed.title, parsed.content, raw
