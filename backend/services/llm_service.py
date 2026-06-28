from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Optional

import requests


OPENAI_ENDPOINT = "https://api.openai.com/v1/responses"
GEMINI_ENDPOINT_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def resolve_provider() -> str:
    configured = os.getenv("AI_SHIELD_LLM_PROVIDER", "").strip().lower()
    if configured in {"openai", "gemini"}:
        return configured
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("GEMINI_API_KEY"):
        return "gemini"
    return ""


def build_agent_instructions(language: str, context: dict[str, Any]) -> str:
    current_page = context.get("current_page", "/")
    latest_result = context.get("latest_result")
    recent_analyses = context.get("recent_analyses") or []
    current_date = datetime.utcnow().strftime("%Y-%m-%d")

    instructions = [
        "You are AI Shield Assistant, the in-product assistant for AI Shield.",
        "Respond naturally, helpfully, and clearly, similar in quality and completeness to modern assistants like ChatGPT or Gemini.",
        "Sound warm, professional, and practical rather than robotic.",
        f"Reply in {'Hindi' if language == 'hi' else 'English'} unless the user clearly switches language.",
        "Be concise by default, but give richer detail when the user asks for explanation, steps, comparison, troubleshooting, or analysis.",
        "When the user asks about a result, explain what the numbers mean in practical terms instead of repeating raw fields only.",
        "When the user asks a general question, answer it directly in a conversational style before offering next-step help.",
        "Do not pretend a claim is verified if live corroboration is missing. Say when something still needs verification.",
        "You help with deepfake detection, synthetic voice detection, fake news analysis, reports, history, dashboard navigation, and troubleshooting.",
        f"Today's date is {current_date}.",
        f"The user is currently on: {current_page}.",
    ]

    if latest_result:
        instructions.append(f"Latest analysis result context: {latest_result}.")
    if recent_analyses:
        instructions.append(f"Recent analyses context: {recent_analyses[:3]}.")

    return "\n".join(instructions)


def extract_openai_text(payload: dict[str, Any]) -> Optional[str]:
    output_items = payload.get("output") or []
    fragments: list[str] = []
    for item in output_items:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "output_text" and content.get("text"):
                fragments.append(str(content["text"]).strip())
    if fragments:
        return "\n".join(fragment for fragment in fragments if fragment)
    return None


def call_openai(
    message: str,
    *,
    language: str,
    context: dict[str, Any],
    conversation: list[dict[str, str]],
    timeout_seconds: float,
) -> Optional[str]:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return None

    model = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    history_items = [
        {"role": item["role"], "content": item["text"]}
        for item in conversation[-8:]
        if item["role"] in {"user", "assistant"}
    ]
    payload = {
        "model": model,
        "instructions": build_agent_instructions(language, context),
        "input": history_items + [{"role": "user", "content": message}],
        "text": {"format": {"type": "text"}},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    response = requests.post(OPENAI_ENDPOINT, headers=headers, json=payload, timeout=timeout_seconds)
    response.raise_for_status()
    return extract_openai_text(response.json())


def call_gemini(
    message: str,
    *,
    language: str,
    context: dict[str, Any],
    conversation: list[dict[str, str]],
    timeout_seconds: float,
) -> Optional[str]:
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return None

    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    endpoint = GEMINI_ENDPOINT_TEMPLATE.format(model=model)
    history_items = [
        {
            "role": "user" if item["role"] == "user" else "model",
            "parts": [{"text": item["text"]}],
        }
        for item in conversation[-8:]
        if item["role"] in {"user", "assistant"}
    ]
    payload = {
        "systemInstruction": {"parts": [{"text": build_agent_instructions(language, context)}]},
        "contents": history_items + [{"role": "user", "parts": [{"text": message}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 700},
    }

    response = requests.post(
        GEMINI_ENDPOINT_TEMPLATE.format(model=model),
        params={"key": api_key},
        json=payload,
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        return None
    parts = ((candidates[0].get("content") or {}).get("parts") or [])
    text_parts = [str(part.get("text", "")).strip() for part in parts if part.get("text")]
    return "\n".join(part for part in text_parts if part) or None


def generate_external_reply(
    message: str,
    *,
    language: str,
    context: dict[str, Any],
    conversation: list[dict[str, str]],
) -> Optional[str]:
    provider = resolve_provider()
    timeout_seconds = float(os.getenv("AI_SHIELD_LLM_TIMEOUT_SECONDS", "12"))

    try:
        if provider == "openai":
            return call_openai(
                message,
                language=language,
                context=context,
                conversation=conversation,
                timeout_seconds=timeout_seconds,
            )
        if provider == "gemini":
            return call_gemini(
                message,
                language=language,
                context=context,
                conversation=conversation,
                timeout_seconds=timeout_seconds,
            )
    except Exception:
        return None

    return None
