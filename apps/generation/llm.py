"""Pluggable LLM layer: turn source text into a validated GenerationResult.

Provider is selected by ``settings.LLM_PROVIDER``:
- ``deepseek``  — DeepSeek's OpenAI-compatible API (default)
- ``local``     — any OpenAI-compatible server (Ollama / vLLM / LM Studio)
- ``gemini``    — Google Gemini
- ``anthropic`` — Anthropic Claude (e.g. claude-haiku-4-5)

All providers are asked for strict JSON; the output is normalized, validated
with Pydantic, and re-prompted once on malformed output.
"""
import json
import logging

from django.conf import settings
from pydantic import ValidationError

from apps.common.exceptions import GenerationError

from .schemas import GenerationResult

logger = logging.getLogger(__name__)

_SYSTEM = "You are a study-aid generator. You only output valid JSON."

_PROMPT = """From the SOURCE TEXT below, produce a compact study set as a single \
JSON object with EXACTLY these keys:
- "title": a short topic title (<= 60 chars).
- "summary": a 3-5 sentence overview.
- "keyPoints": array of 3-7 concise bullet strings.
- "topics": array of 2-5 short topic labels used to tag quiz questions.
- "quiz": array of 5-10 objects, each {{"prompt", "choices" (4 strings), \
"correctIndex" (0-based int), "explanation" (one sentence), "topic" (from topics)}}.
- "wordGame": array of 3-6 objects, each {{"word" (2-12 A-Z letters, no spaces), \
"clue" (one sentence)}}.
Only use facts grounded in the SOURCE TEXT. Output JSON only, no prose, no markdown.

SOURCE TEXT:
\"\"\"
{text}
\"\"\"
"""

# Gemini understands a response schema; OpenAI-compatible servers get json_object.
_GEMINI_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "keyPoints": {"type": "array", "items": {"type": "string"}},
        "topics": {"type": "array", "items": {"type": "string"}},
        "quiz": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "choices": {"type": "array", "items": {"type": "string"}},
                    "correctIndex": {"type": "integer"},
                    "explanation": {"type": "string"},
                    "topic": {"type": "string"},
                },
                "required": ["prompt", "choices", "correctIndex"],
            },
        },
        "wordGame": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "word": {"type": "string"},
                    "clue": {"type": "string"},
                },
                "required": ["word", "clue"],
            },
        },
    },
    "required": ["title", "summary", "quiz"],
}


def _normalize_keys(raw: dict) -> dict:
    """Map camelCase LLM keys to the snake_case our pydantic schema expects."""
    quiz = []
    for q in raw.get("quiz", []) or []:
        quiz.append(
            {
                "prompt": q.get("prompt", ""),
                "choices": q.get("choices", []),
                "correct_index": q.get("correctIndex", q.get("correct_index", 0)),
                "explanation": q.get("explanation", "") or "",
                "topic": q.get("topic", "General") or "General",
            }
        )
    return {
        "title": raw.get("title", ""),
        "summary": raw.get("summary", ""),
        "key_points": raw.get("keyPoints", raw.get("key_points", [])) or [],
        "topics": raw.get("topics", []) or [],
        "quiz": quiz,
        "word_game": raw.get("wordGame", raw.get("word_game", [])) or [],
    }


# --------------------------------------------------------------------------- #
# Providers — each returns a raw dict parsed from the model's JSON output.
# --------------------------------------------------------------------------- #
def _call_openai_compatible(text: str, *, base_url, api_key, model, provider):
    from openai import OpenAI

    client = OpenAI(base_url=base_url, api_key=api_key, timeout=90)
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _PROMPT.format(text=text)},
        ],
        response_format={"type": "json_object"},
        temperature=settings.LLM_TEMPERATURE,
        max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
        stream=False,
    )
    raw = json.loads(completion.choices[0].message.content)
    u = completion.usage
    usage = {
        "provider": provider,
        "model": model,
        "input_tokens": int(getattr(u, "prompt_tokens", 0) or 0),
        "output_tokens": int(getattr(u, "completion_tokens", 0) or 0),
    }
    return raw, usage


def _call_deepseek(text: str):
    if not settings.DEEPSEEK_API_KEY:
        raise GenerationError("DeepSeek is not configured.")
    return _call_openai_compatible(
        text,
        base_url=settings.DEEPSEEK_BASE_URL,
        api_key=settings.DEEPSEEK_API_KEY,
        model=settings.DEEPSEEK_MODEL,
        provider="deepseek",
    )


def _call_local(text: str):
    return _call_openai_compatible(
        text,
        base_url=settings.LOCAL_LLM_BASE_URL,
        api_key=settings.LOCAL_LLM_API_KEY,
        model=settings.LOCAL_LLM_MODEL,
        provider="local",
    )


def _call_gemini(text: str):
    import google.generativeai as genai

    if not settings.GEMINI_API_KEY:
        raise GenerationError("Gemini is not configured.")
    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel(settings.GEMINI_MODEL)
    response = model.generate_content(
        _PROMPT.format(text=text),
        generation_config={
            "response_mime_type": "application/json",
            "response_schema": _GEMINI_SCHEMA,
            "temperature": settings.LLM_TEMPERATURE,
            "max_output_tokens": settings.LLM_MAX_OUTPUT_TOKENS,
        },
    )
    meta = getattr(response, "usage_metadata", None)
    usage = {
        "provider": "gemini",
        "model": settings.GEMINI_MODEL,
        "input_tokens": int(getattr(meta, "prompt_token_count", 0) or 0),
        "output_tokens": int(getattr(meta, "candidates_token_count", 0) or 0),
    }
    return json.loads(response.text), usage


def _strip_json_fence(raw: str) -> str:
    """Claude is asked for raw JSON, but tolerate an accidental ```json fence."""
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()


def _call_anthropic(text: str):
    import anthropic

    if not settings.ANTHROPIC_API_KEY:
        raise GenerationError("Anthropic (Claude) is not configured.")
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=90)
    message = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
        temperature=settings.LLM_TEMPERATURE,
        system=_SYSTEM,
        messages=[{"role": "user", "content": _PROMPT.format(text=text)}],
    )
    raw = next((b.text for b in message.content if b.type == "text"), "")
    usage = {
        "provider": "anthropic",
        "model": settings.ANTHROPIC_MODEL,
        "input_tokens": int(getattr(message.usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(message.usage, "output_tokens", 0) or 0),
    }
    return json.loads(_strip_json_fence(raw)), usage


_PROVIDERS = {
    "deepseek": _call_deepseek,
    "local": _call_local,
    "gemini": _call_gemini,
    "anthropic": _call_anthropic,
}


def _provider():
    provider = (settings.LLM_PROVIDER or "anthropic").lower()
    if provider not in _PROVIDERS:
        raise GenerationError(f"Unknown LLM provider: {provider}")
    return _PROVIDERS[provider], provider


def run_llm(text: str) -> tuple[GenerationResult, dict]:
    """Returns (validated result, token-usage dict).

    usage = {provider, model, input_tokens, output_tokens}.
    """
    call, name = _provider()
    last_error = None
    for attempt in range(2):  # one re-prompt on malformed output
        try:
            raw, usage = call(text)
            return GenerationResult.model_validate(_normalize_keys(raw)), usage
        except GenerationError:
            raise
        except (json.JSONDecodeError, ValidationError, KeyError, ValueError, TypeError) as exc:
            last_error = exc
            logger.warning(
                "LLM(%s) output invalid (attempt %s): %s", name, attempt + 1, exc
            )
        except Exception as exc:  # network / provider errors
            last_error = exc
            logger.warning("LLM(%s) call failed (attempt %s): %s", name, attempt + 1, exc)
    raise GenerationError(f"AI returned malformed content: {last_error}")
