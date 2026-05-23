"""Gemini call that returns a validated GenerationResult.

Uses JSON mode with an explicit response schema so parsing is deterministic;
re-prompts once if the model returns malformed output.
"""
import json
import logging

from django.conf import settings
from pydantic import ValidationError

from apps.common.exceptions import GenerationError

from .schemas import GenerationResult

logger = logging.getLogger(__name__)

_RESPONSE_SCHEMA = {
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

_PROMPT = """You are a study-aid generator. From the SOURCE TEXT below, produce \
a compact study set as JSON. Requirements:
- title: a short topic title (<= 60 chars).
- summary: 3-5 sentence overview.
- keyPoints: 3-7 concise bullet strings.
- topics: 2-5 short topic labels used to tag quiz questions.
- quiz: 5-10 multiple-choice questions. Each has prompt, 4 choices, a \
correctIndex (0-based), a one-sentence explanation, and a topic from the \
topics list.
- wordGame: 3-6 single-word, hangman-style entries. word is 2-12 A-Z letters \
(no spaces); clue is one sentence.
Only use facts grounded in the SOURCE TEXT.

SOURCE TEXT:
\"\"\"
{text}
\"\"\"
"""


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


def _call_model(text: str) -> dict:
    import google.generativeai as genai

    if not settings.GEMINI_API_KEY:
        raise GenerationError("AI generation is not configured.")
    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel(settings.GEMINI_MODEL)
    response = model.generate_content(
        _PROMPT.format(text=text),
        generation_config={
            "response_mime_type": "application/json",
            "response_schema": _RESPONSE_SCHEMA,
            "temperature": 0.4,
        },
    )
    return json.loads(response.text)


def run_gemini(text: str) -> GenerationResult:
    last_error = None
    for attempt in range(2):  # one re-prompt on malformed output
        try:
            raw = _call_model(text)
            return GenerationResult.model_validate(_normalize_keys(raw))
        except (json.JSONDecodeError, ValidationError, KeyError, ValueError) as exc:
            last_error = exc
            logger.warning("Gemini output invalid (attempt %s): %s", attempt + 1, exc)
    raise GenerationError(f"AI returned malformed content: {last_error}")
