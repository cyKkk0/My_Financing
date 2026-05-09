from datetime import date
from collections.abc import AsyncGenerator
import json

import httpx

from app.core.config import Settings
from app.schemas import PortfolioSummaryOut


SYSTEM_PROMPT = """你是一个谨慎的个人理财分析助手。
你的任务是基于用户的基金持仓、收益、仓位集中度和定投情况，给出风险提示和观察建议。
不要承诺收益，不要给出绝对化买卖指令，必须提醒用户自行决策。"""


async def generate_advice(settings: Settings, summary: PortfolioSummaryOut) -> str:
    if not settings.llm_api_key:
        return "未配置 LLM_API_KEY。当前仅完成收益计算，暂未生成 AI 建议。"

    payload = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "请基于以下基金组合数据，输出今日观察、主要风险、定投建议、需要人工确认的问题。"
                    f"\n日期：{date.today().isoformat()}"
                    f"\n组合数据：{summary.model_dump_json()}"
                ),
            },
        ],
        "temperature": 0.3,
    }
    url = settings.llm_api_base.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
    return data["choices"][0]["message"]["content"]


async def stream_chat_advice(
    settings: Settings,
    summary: PortfolioSummaryOut,
    messages: list[dict[str, str]],
) -> AsyncGenerator[str, None]:
    if not settings.llm_api_key:
        yield "未配置 LLM_API_KEY，暂时无法进行 AI 对话。"
        return

    system_content = (
        SYSTEM_PROMPT
        + "\n你正在和用户实时对话。回答要结合用户当前基金组合数据，先说明依据，再给出可执行的观察建议。"
        + "\n当前组合数据："
        + summary.model_dump_json()
    )
    payload = {
        "model": settings.llm_model,
        "messages": [{"role": "system", "content": system_content}, *messages],
        "temperature": 0.35,
        "stream": True,
    }
    url = settings.llm_api_base.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"}

    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line.removeprefix("data: ").strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = chunk["choices"][0].get("delta", {})
                content = delta.get("content")
                if content:
                    yield content
