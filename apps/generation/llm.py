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

_PROMPT = """Turn the SOURCE TEXT into a study guide. Do NOT over-summarise: keep \
the real definitions, details and nuance — reorganise the material into readable \
sections and only shorten wordy passages so each section is easy to read.

COVERAGE IS THE PRIMARY GOAL. Every meaningful fact, definition, mechanism, \
date, name, formula, framework, or rule that appears in the SOURCE TEXT must be \
testable from your output. Do NOT cherry-pick "the most obvious" facts and \
ignore the rest. If the source has a list, table, or enumeration, EACH item \
in it deserves dedicated coverage. Aim wide; depth comes from the difficulty mix.

Return a single JSON object with EXACTLY these keys:
- "title": a short title for the whole set (<= 60 chars).
- "sections": array of 3-8 objects (split the material by sub-topic), each:
   - "title": a short section heading.
   - "content": 1-3 short paragraphs that PRESERVE the key definitions and \
details of this part of the source (readable chunks, NOT a one-line summary).
   - "example": a "Further understanding" anchor that helps the reader \
build intuition for the section. Either (a) one concrete, relatable \
real-world example that shows the section's idea in everyday life, OR \
(b) a single important key term from the section explained in 1-2 plain \
sentences with a tiny illustrative analogy. Pick whichever is more useful \
for THIS section. Start the sentence with the example/analogy directly — \
no preamble like "For example" or "In other words".
   - "quiz": as many items as it takes to cover EVERY important fact in \
this section. There is NO upper cap and NO fixed "3-per-difficulty" rule. \
Floor by section length: short (<300 chars) -> 5+ items, medium (300-900 \
chars) -> 8+, long/dense (900+ chars) -> 12+. Distribute across \
difficulties roughly 30% easy / 50% medium / 20% hard — but generate as \
many of EACH difficulty as the content supports, not a fixed quota. If \
the section involves a specific rule, law, theory, formula, framework or \
named principle, INCLUDE at least two "hard" application questions for \
it. Each item: {{"prompt", "choices" (4 strings, plausible distractors \
not obvious throwaways), "correctIndex" (0-based int), "explanation" \
(one sentence WHY the correct answer is right), "difficulty" (one of \
"easy" | "medium" | "hard")}}. \
Easy = direct recall of a fact stated in the section. Medium = a \
comparison, why, or how question. Hard = apply a rule, theory or \
principle to a new example, or pick the best inference among close options.
- "wordGame": array of 4-8 objects covering key terms from the source, \
each {{"word" (2-12 A-Z letters, no spaces), "clue" (one sentence)}}.
Only use facts grounded in the SOURCE TEXT. Output JSON only, no prose, no markdown.

SOURCE TEXT:
\"\"\"
{text}
\"\"\"
"""

# Gemini understands a response schema; OpenAI-compatible servers get json_object.
_QUIZ_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "choices": {"type": "array", "items": {"type": "string"}},
            "correctIndex": {"type": "integer"},
            "explanation": {"type": "string"},
            "difficulty": {
                "type": "string",
                "enum": ["easy", "medium", "hard"],
            },
        },
        "required": ["prompt", "choices", "correctIndex"],
    },
}
_GEMINI_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "example": {"type": "string"},
                    "quiz": _QUIZ_SCHEMA,
                },
                "required": ["title", "content"],
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
    "required": ["title", "sections"],
}


_DIFFICULTIES = ("easy", "medium", "hard")
_DIFFICULTY_ORDER = {"easy": 0, "medium": 1, "hard": 2}


def _clean_quiz(items, topic):
    """Keep only well-formed quiz items; clamp a bad correctIndex rather than
    failing the whole generation. Sort by difficulty (easy first) so the
    learner warms up before the hard / challenge items."""
    out = []
    for q in items or []:
        prompt = (q.get("prompt") or "").strip()
        choices = [str(c).strip() for c in (q.get("choices") or []) if c and str(c).strip()]
        if not prompt or len(choices) < 2:
            continue
        try:
            ci = int(q.get("correctIndex", q.get("correct_index", 0)) or 0)
        except (TypeError, ValueError):
            ci = 0
        if ci < 0 or ci >= len(choices):
            ci = 0
        diff = str(q.get("difficulty") or "medium").lower().strip()
        if diff not in _DIFFICULTIES:
            diff = "medium"
        out.append({
            "prompt": prompt,
            "choices": choices,
            "correct_index": ci,
            "explanation": q.get("explanation", "") or "",
            "topic": topic,
            "difficulty": diff,
        })
    out.sort(key=lambda x: _DIFFICULTY_ORDER[x["difficulty"]])
    return out


def _clean_words(items):
    """Drop word-game entries that can't be a 2-12 letter A-Z puzzle word, so a
    single over-long word (e.g. ANTICONVULSANT) doesn't fail the whole set."""
    out = []
    for w in items or []:
        word = "".join(ch for ch in str(w.get("word", "")).upper() if ch.isalpha())
        clue = (w.get("clue") or "").strip()
        if 2 <= len(word) <= 12 and clue:
            out.append({"word": word, "clue": clue})
    return out


def _normalize_keys(raw: dict) -> dict:
    """Map the LLM's camelCase section JSON to our snake_case pydantic schema,
    pre-cleaning so a few malformed items never discard a good study set."""
    sections = []
    for s in raw.get("sections", []) or []:
        sections.append(
            {
                "title": s.get("title", "") or "Section",
                "content": s.get("content", "") or "",
                "example": s.get("example", "") or "",
                "quiz": _clean_quiz(s.get("quiz", []), s.get("title", "General") or "General"),
            }
        )
    return {
        "title": raw.get("title", "") or "Study set",
        "sections": sections,
        "word_game": _clean_words(raw.get("wordGame", raw.get("word_game", []))),
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
    try:
        message = client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
            temperature=settings.LLM_TEMPERATURE,
            system=_SYSTEM,
            messages=[{"role": "user", "content": _PROMPT.format(text=text)}],
        )
    except anthropic.AuthenticationError as exc:
        raise GenerationError(
            "Anthropic rejected the API key (401). Check ANTHROPIC_API_KEY in "
            "the backend .env — no spaces/comments, and a current active key."
        ) from exc
    except anthropic.PermissionDeniedError as exc:
        raise GenerationError(
            "Anthropic denied access (403). Check the key's workspace and that "
            "the model is enabled for your organization."
        ) from exc
    raw = next((b.text for b in message.content if b.type == "text"), "")
    usage = {
        "provider": "anthropic",
        "model": settings.ANTHROPIC_MODEL,
        "input_tokens": int(getattr(message.usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(message.usage, "output_tokens", 0) or 0),
    }
    stop = getattr(message, "stop_reason", None)
    logger.info(
        "LLM(anthropic) model=%s stop=%s in=%s out=%s chars=%s max_tokens=%s",
        settings.ANTHROPIC_MODEL, stop,
        usage["input_tokens"], usage["output_tokens"], len(raw),
        settings.LLM_MAX_OUTPUT_TOKENS,
    )
    cleaned = _strip_json_fence(raw)
    try:
        return json.loads(cleaned), usage
    except json.JSONDecodeError as exc:
        tail = cleaned[-400:]
        logger.warning(
            "LLM(anthropic) JSON parse failed (stop=%s, out_tokens=%s, chars=%s): %s | tail=%r",
            stop, usage["output_tokens"], len(cleaned), exc, tail,
        )
        if stop == "max_tokens":
            raise GenerationError(
                f"AI response was cut off at the token limit "
                f"({usage['output_tokens']} output tokens). "
                f"Raise LLM_MAX_OUTPUT_TOKENS (currently {settings.LLM_MAX_OUTPUT_TOKENS}) "
                f"or shorten the input."
            ) from exc
        raise


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


# Large uploads are split so the model sees the whole thing (nothing dropped),
# then the per-chunk sections are merged into one study set.
CHUNK_CHARS = 12000


def _chunk(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks, buf = [], ""
    for para in text.split("\n\n"):
        if buf and len(buf) + len(para) + 2 > limit:
            chunks.append(buf)
            buf = ""
        # A single mammoth paragraph still has to be hard-split.
        while len(para) > limit:
            chunks.append(para[:limit])
            para = para[limit:]
        buf = f"{buf}\n\n{para}" if buf else para
    if buf:
        chunks.append(buf)
    return chunks


def generate(text: str) -> tuple[GenerationResult, dict]:
    """Generate a sectioned study set, chunking large source text and merging.

    Returns (GenerationResult, aggregated token-usage dict).
    """
    chunks = _chunk(text)
    if len(chunks) == 1:
        return run_llm(chunks[0])

    sections, words, title = [], [], ""
    usage = {"provider": "", "model": "", "input_tokens": 0, "output_tokens": 0}
    for ch in chunks:
        res, u = run_llm(ch)
        title = title or res.title
        sections.extend(res.sections)
        words.extend(res.word_game)
        usage["provider"] = u.get("provider", usage["provider"])
        usage["model"] = u.get("model", usage["model"])
        usage["input_tokens"] += u.get("input_tokens", 0)
        usage["output_tokens"] += u.get("output_tokens", 0)

    seen, deduped = set(), []
    for w in words:
        if w.word not in seen:
            seen.add(w.word)
            deduped.append(w)

    merged = GenerationResult(
        title=title or "Study set", sections=sections, word_game=deduped
    )
    return merged, usage


_EXTRA_QUIZ_PROMPT = """You already wrote some quiz questions for a study set. \
The learner has now finished them and wants MORE. Write {n} NEW quiz items \
about the same SOURCE TEXT below, MIXED in difficulty (easy / medium / hard), \
with at least 2 hard "challenge" items that ask the learner to APPLY a rule \
or principle. The new prompts MUST NOT repeat (or be paraphrases of) any \
prompt in the EXISTING list below.

Output a single JSON object with exactly one key "quiz" whose value is an array \
of {n} items, each {{"prompt", "choices" (4 plausible strings), \
"correctIndex" (0-based int), "explanation" (one sentence), "difficulty" \
(one of "easy" | "medium" | "hard")}}.
Only use facts grounded in the SOURCE TEXT. Output JSON only, no prose.

EXISTING (do not repeat these prompts):
{exclude}

SOURCE TEXT:
\"\"\"
{text}
\"\"\"
"""


def generate_extra_quiz(
    source_text: str, exclude_prompts: list, n: int = 10, topic: str = "More"
) -> list:
    """Ask the LLM for [n] additional quiz items distinct from
    [exclude_prompts]. Returns a list of normalized quiz dicts ready to
    persist via QuizQuestion.objects.create. Raises GenerationError on
    failure.
    """
    if not source_text or not source_text.strip():
        raise GenerationError("This study set has no readable content to draw from.")
    excl_lines = "\n".join(f"- {p[:200]}" for p in (exclude_prompts or [])[:80])
    user = _EXTRA_QUIZ_PROMPT.format(
        text=source_text[:18_000],
        exclude=excl_lines or "(none)",
        n=max(3, min(int(n), 20)),
    )

    import anthropic

    if not settings.ANTHROPIC_API_KEY:
        raise GenerationError("Anthropic (Claude) is not configured.")
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=90)
    try:
        message = client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
            temperature=settings.LLM_TEMPERATURE,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.AuthenticationError as exc:
        raise GenerationError("Anthropic rejected the API key.") from exc
    raw = next((b.text for b in message.content if b.type == "text"), "")
    cleaned = _strip_json_fence(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning("Extra-quiz JSON parse failed: %s", exc)
        raise GenerationError("AI returned malformed extra-quiz content.") from exc
    items = data.get("quiz") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise GenerationError("AI did not return any new quiz items.")
    cleaned_items = _clean_quiz(items, topic)
    # Drop any items whose prompt collides with the exclude list (case
    # insensitive, trimmed) as a final safety net.
    excl_lower = {p.strip().lower() for p in (exclude_prompts or [])}
    out = [q for q in cleaned_items if q["prompt"].strip().lower() not in excl_lower]
    if not out:
        raise GenerationError("AI couldn't produce questions that aren't repeats.")
    return out
