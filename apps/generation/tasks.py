import logging
import time
from concurrent.futures import ThreadPoolExecutor

from celery import shared_task
from django.conf import settings
from django.db import transaction

from apps.common.exceptions import GenerationError
from apps.studysets.models import QuizQuestion, StudySet, WordChallenge
from apps.subscriptions.services import consume_free_credit

from .extraction import _youtube_id, _youtube_title, extract_text
from .llm import generate
from .schemas import GenerationResult, Section

logger = logging.getLogger(__name__)

# Long source documents are split into chunks of roughly this many characters,
# then each chunk gets its own generation pass so the model can ask deeper
# questions about THAT chunk instead of cramming the whole doc into one call
# (which made the LLM bias toward the most surface-level facts).
#
# Chosen so that even with the coverage-first prompt (which can produce 30+
# quiz items per chunk), the model's output stays comfortably under the
# LLM_MAX_OUTPUT_TOKENS cap. Input-to-output ratio is ~3x in practice, so
# 8000 input chars maps to roughly 24000 output chars (~6000 tokens).
_CHUNK_CHARS = 8_000


def _derive_title(source_kind, source_ref):
    if source_kind == "link":
        # YouTube videos get their real title from oEmbed when possible.
        if (vid := _youtube_id(source_ref)) is not None:
            yt_title = _youtube_title(vid)
            if yt_title:
                return yt_title
        return source_ref.split("//", 1)[-1].split("/", 1)[0][:120] or "Study set"
    if source_kind == "text":
        return "Pasted notes"
    return "Uploaded document"


def _chunk_text(text: str, chunk_chars: int = _CHUNK_CHARS) -> list[str]:
    """Split *text* into ~chunk_chars segments at paragraph boundaries so each
    LLM pass sees a coherent slice. Returns a single-element list when the doc
    fits in one pass.
    """
    text = (text or "").strip()
    if len(text) <= chunk_chars:
        return [text] if text else []
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    # Prefer paragraph breaks, fall back to single newlines, then hard splits.
    seps = ("\n\n", "\n", " ")
    sep = next((s for s in seps if s in text), "\n")
    for part in text.split(sep):
        part_len = len(part) + len(sep)
        if current_len + part_len > chunk_chars and current:
            chunks.append(sep.join(current))
            current = []
            current_len = 0
        current.append(part)
        current_len += part_len
    if current:
        chunks.append(sep.join(current))
    # Safety: if a single paragraph blew past chunk_chars, hard-split it.
    out: list[str] = []
    for c in chunks:
        if len(c) <= chunk_chars * 1.5:
            out.append(c)
        else:
            for i in range(0, len(c), chunk_chars):
                out.append(c[i : i + chunk_chars])
    return out


def _merge_results(results: list[GenerationResult]) -> GenerationResult:
    """Combine per-chunk GenerationResults into one, deduping quiz items by
    prompt prefix and word-game entries by word."""
    if not results:
        raise GenerationError("LLM produced no usable output.")
    if len(results) == 1:
        return results[0]

    title = results[0].title
    all_sections: list[Section] = []
    seen_prompts: set[str] = set()
    for r in results:
        for sec in r.sections:
            dedup_quiz = []
            for q in sec.quiz:
                key = q.prompt.strip().lower()[:80]
                if key in seen_prompts:
                    continue
                seen_prompts.add(key)
                dedup_quiz.append(q)
            sec.quiz = dedup_quiz
            all_sections.append(sec)

    seen_words: set[str] = set()
    all_words = []
    for r in results:
        for w in r.word_game:
            if w.word in seen_words:
                continue
            seen_words.add(w.word)
            all_words.append(w)

    return GenerationResult(
        title=title,
        sections=all_sections,
        word_game=all_words[:10],
    )


@shared_task(bind=True, max_retries=2, default_retry_delay=10)
def generate_study_set(self, study_set_id):
    started = time.monotonic()
    try:
        study_set = StudySet.objects.get(id=study_set_id)
    except StudySet.DoesNotExist:
        logger.error("StudySet %s vanished before generation.", study_set_id)
        return

    if study_set.status == StudySet.Status.READY:
        return  # idempotent — already done

    StudySet.objects.filter(id=study_set_id).update(
        status=StudySet.Status.PROCESSING
    )

    try:
        text = extract_text(study_set.source_kind, study_set.source_ref)
        if len(text) < 50:
            raise GenerationError("Not enough readable content to generate from.")

        # Long docs are split into ~12k-char chunks so each LLM pass can do
        # justice to its slice instead of producing surface-only questions
        # over the whole document. One chunk -> one call; N chunks -> N calls.
        chunks = _chunk_text(text)
        usage = {
            "provider": "",
            "model": "",
            "input_tokens": 0,
            "output_tokens": 0,
        }
        logger.info(
            "Generating %d chunk(s) for StudySet %s", len(chunks), study_set_id
        )

        # LLM calls are network-bound, so for multi-chunk docs we run them
        # concurrently: wall-clock drops from N x latency toward ~1 x latency
        # instead of waiting on each chunk in turn. ThreadPoolExecutor.map
        # preserves input order, which _merge_results relies on. A single
        # chunk skips the pool entirely.
        if len(chunks) <= 1:
            pairs = [generate(c) for c in chunks]
        else:
            workers = min(settings.GENERATION_MAX_PARALLEL_CHUNKS, len(chunks))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                pairs = list(pool.map(generate, chunks))

        results: list[GenerationResult] = []
        for r, u in pairs:
            results.append(r)
            usage["provider"] = u.get("provider", usage["provider"])
            usage["model"] = u.get("model", usage["model"])
            usage["input_tokens"] += u.get("input_tokens", 0)
            usage["output_tokens"] += u.get("output_tokens", 0)
        result = _merge_results(results)

        # Flatten sections for the legacy/flat fields + build the sections JSON.
        sections_json = [
            {
                "title": sec.title,
                "content": sec.content,
                "example": sec.example,
                "keyTerms": sec.key_terms,
                "quiz": [
                    {
                        "prompt": q.prompt,
                        "choices": q.choices,
                        "correctIndex": q.correct_index,
                        "explanation": q.explanation,
                        "topic": q.topic,
                        "difficulty": q.difficulty,
                    }
                    for q in sec.quiz
                ],
            }
            for sec in result.sections
        ]
        all_quiz = [q for sec in result.sections for q in sec.quiz]
        section_titles = [sec.title for sec in result.sections]
        # Short preview for the library card (first section, trimmed).
        summary_preview = (result.sections[0].content[:280] if result.sections else "")

        # Track token spend for this user (best-effort; never fail generation).
        try:
            from .models import TokenUsage

            TokenUsage.objects.create(
                user=study_set.owner,
                study_set=study_set,
                provider=usage.get("provider", ""),
                model=usage.get("model", ""),
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            )
        except Exception:  # usage logging must never break generation
            logger.warning("Failed to record token usage for %s", study_set_id)

        with transaction.atomic():
            s = StudySet.objects.select_for_update().get(id=study_set_id)
            s.sections = sections_json
            s.summary = summary_preview
            s.key_points = section_titles
            s.topics = section_titles
            s.title = s.title or result.title or _derive_title(
                s.source_kind, s.source_ref
            )
            s.status = StudySet.Status.READY
            s.error = ""
            s.save()

            s.quiz.all().delete()
            s.word_game.all().delete()
            QuizQuestion.objects.bulk_create(
                [
                    QuizQuestion(
                        study_set=s,
                        prompt=q.prompt,
                        choices=q.choices,
                        correct_index=q.correct_index,
                        explanation=q.explanation,
                        topic=q.topic,
                        difficulty=q.difficulty,
                        order=i,
                    )
                    for i, q in enumerate(all_quiz)
                ]
            )
            WordChallenge.objects.bulk_create(
                [
                    WordChallenge(
                        study_set=s, word=w.word, clue=w.clue, order=i
                    )
                    for i, w in enumerate(result.word_game)
                ]
            )

            # Consume one free credit only on success. Counts against the
            # current monthly window (premium users are exempt).
            consume_free_credit(s.owner)

        # Award creation points server-side, idempotently (one award per set)
        # so it can't be farmed by replaying a client request.
        from apps.rewards.services import award

        award(
            study_set.owner,
            reason="Created a study set",
            dedupe_key=f"studyset:{study_set_id}",
        )

        logger.info(
            "Generated StudySet %s in %.1fs (sections=%d quiz=%d words=%d)",
            study_set_id,
            time.monotonic() - started,
            len(result.sections),
            len(all_quiz),
            len(result.word_game),
        )

    except GenerationError as exc:
        StudySet.objects.filter(id=study_set_id).update(
            status=StudySet.Status.FAILED, error=str(exc)
        )
        logger.warning("Generation failed for %s: %s", study_set_id, exc)
    except Exception as exc:  # transient/infra error — retry, then mark failed
        logger.exception("Unexpected generation error for %s", study_set_id)
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            StudySet.objects.filter(id=study_set_id).update(
                status=StudySet.Status.FAILED,
                error="Generation failed after retries.",
            )
