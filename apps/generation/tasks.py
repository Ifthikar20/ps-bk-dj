import logging
import time

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import Max

from apps.common.exceptions import GenerationError
from apps.studysets.models import QuizQuestion, StudySet, WordChallenge
from apps.subscriptions.services import consume_free_credit

from .extraction import _youtube_id, _youtube_title, extract_text
from .llm import generate
from .preview import build_preview

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

# Cap how many word-game entries a set keeps across all batches combined.
_MAX_WORDS = 10


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


def _sections_to_json(sections) -> list[dict]:
    """Serialize the schema Sections of one batch into the StudySet.sections
    JSON shape (camelCase, matching what the app already reads)."""
    return [
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
        for sec in sections
    ]


# --------------------------------------------------------------------------- #
# Orchestrator: prepare the document, then fan out one task per batch.
# --------------------------------------------------------------------------- #
@shared_task(bind=True, max_retries=2, default_retry_delay=10)
def generate_study_set(self, study_set_id):
    """Extract + chunk the source, then fan out a `process_batch` task per
    chunk. Each batch runs in its OWN task (its own time budget) and persists
    its slice the moment it finishes, so the set turns PARTIAL and becomes
    readable long before the final batch lands — instead of one mega-task that
    had to finish every chunk inside a single 120s window.
    """
    try:
        study_set = StudySet.objects.get(id=study_set_id)
    except StudySet.DoesNotExist:
        logger.error("StudySet %s vanished before generation.", study_set_id)
        return

    if study_set.status == StudySet.Status.READY:
        return  # idempotent — already done

    try:
        text = extract_text(study_set.source_kind, study_set.source_ref)
        if len(text) < 50:
            raise GenerationError("Not enough readable content to generate from.")

        chunks = _chunk_text(text)
        max_batches = settings.GENERATION_MAX_BATCHES
        if len(chunks) > max_batches:
            logger.warning(
                "StudySet %s: %d chunks exceeds GENERATION_MAX_BATCHES=%d; "
                "processing the first %d.",
                study_set_id, len(chunks), max_batches, max_batches,
            )
            chunks = chunks[:max_batches]
        total = len(chunks)
        if total == 0:
            raise GenerationError("Not enough readable content to generate from.")

        # Instant, no-LLM preview from the raw text so the app has something to
        # show in the first few seconds while the AI batches run.
        preview = build_preview(text)

        # Reset the set for a clean run and record how many batches to expect.
        # Done up front so a mid-flight GET / status poll sees accurate progress.
        with transaction.atomic():
            s = StudySet.objects.select_for_update().get(id=study_set_id)
            s.status = StudySet.Status.PROCESSING
            s.sections = []
            s.key_points = []
            s.topics = []
            s.summary = ""
            s.error = ""
            s.preview = preview
            s.batches_total = total
            s.batches_done = 0
            s.save(update_fields=[
                "status", "sections", "key_points", "topics", "summary",
                "error", "preview", "batches_total", "batches_done",
            ])
            s.quiz.all().delete()
            s.word_game.all().delete()

        # Fan out. Batch 0 is enqueued first so first content shows fastest.
        # Each batch is independent: a failure retries only that slice, and
        # the rest of the document is unaffected.
        for index, chunk in enumerate(chunks):
            process_batch.delay(str(study_set_id), index, total, chunk)

        logger.info(
            "StudySet %s fanned out into %d batch(es).", study_set_id, total
        )

    except GenerationError as exc:
        StudySet.objects.filter(id=study_set_id).update(
            status=StudySet.Status.FAILED, error=str(exc)
        )
        logger.warning("Generation setup failed for %s: %s", study_set_id, exc)
    except Exception as exc:  # transient/infra error — retry, then mark failed
        logger.exception("Unexpected error preparing generation for %s", study_set_id)
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            StudySet.objects.filter(id=study_set_id).update(
                status=StudySet.Status.FAILED,
                error="Generation failed after retries.",
            )


# --------------------------------------------------------------------------- #
# Per-batch worker: generate one chunk and persist it incrementally.
# --------------------------------------------------------------------------- #
@shared_task(bind=True, max_retries=2, default_retry_delay=10)
def process_batch(self, study_set_id, index, total, chunk):
    started = time.monotonic()
    try:
        study_set = StudySet.objects.get(id=study_set_id)
    except StudySet.DoesNotExist:
        return
    if study_set.status == StudySet.Status.FAILED:
        return  # the run was already abandoned; don't pile on

    try:
        result, usage = generate(chunk)
    except Exception as exc:
        # Retry just this slice. If it's exhausted, still tick the counter so
        # the set can finalize on whatever the other batches produced.
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            logger.warning(
                "Batch %d/%d failed for StudySet %s: %s",
                index + 1, total, study_set_id, exc,
            )
            finalized, ready = _record_batch(
                study_set_id, sections=[], quiz=[], words=[], title=""
            )
            _finalize_if_done(finalized, ready, study_set_id, study_set.owner)
            return

    # Best-effort token logging — one row per batch (LLM call).
    try:
        from .models import TokenUsage

        TokenUsage.objects.create(
            user_id=study_set.owner_id,
            study_set_id=study_set_id,
            provider=usage.get("provider", ""),
            model=usage.get("model", ""),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )
    except Exception:  # usage logging must never break generation
        logger.warning("Failed to record token usage for %s", study_set_id)

    finalized, ready = _record_batch(
        study_set_id,
        sections=_sections_to_json(result.sections),
        quiz=[q for sec in result.sections for q in sec.quiz],
        words=list(result.word_game),
        title=result.title,
    )
    _finalize_if_done(finalized, ready, study_set_id, study_set.owner)

    logger.info(
        "Batch %d/%d done for StudySet %s in %.1fs",
        index + 1, total, study_set_id, time.monotonic() - started,
    )


def _record_batch(study_set_id, *, sections, quiz, words, title):
    """Append one batch's results to the set under a row lock, deduping quiz
    items and words against what is already saved. Returns (finalized, ready):
    `finalized` is True for the single batch that completes the set, `ready`
    True when that finalized set has usable content.

    The slow LLM call happens BEFORE this — the lock is held only for the short
    append, so parallel batches barely contend.
    """
    with transaction.atomic():
        s = StudySet.objects.select_for_update().get(id=study_set_id)

        merged_sections = list(s.sections or [])
        merged_sections.extend(sections)
        s.sections = merged_sections

        # Title + summary come from the first batch that yields content.
        if not s.title:
            s.title = title or _derive_title(s.source_kind, s.source_ref)
        if not s.summary and sections:
            s.summary = (sections[0].get("content") or "")[:280]
        s.key_points = [sec["title"] for sec in merged_sections]
        s.topics = s.key_points

        # Dedup quiz against prompts already on the set, then append in order.
        seen = {
            (p or "").strip().lower()[:80]
            for p in s.quiz.values_list("prompt", flat=True)
        }
        next_order = (s.quiz.aggregate(m=Max("order"))["m"] or -1) + 1
        new_quiz = []
        for q in quiz:
            key = (q.prompt or "").strip().lower()[:80]
            if key in seen:
                continue
            seen.add(key)
            new_quiz.append(QuizQuestion(
                study_set=s,
                prompt=q.prompt,
                choices=q.choices,
                correct_index=q.correct_index,
                explanation=q.explanation,
                topic=q.topic,
                difficulty=q.difficulty,
                order=next_order,
            ))
            next_order += 1
        QuizQuestion.objects.bulk_create(new_quiz)

        # Words: dedup by word and cap the set's total at _MAX_WORDS.
        seen_words = set(s.word_game.values_list("word", flat=True))
        word_order = (s.word_game.aggregate(m=Max("order"))["m"] or -1) + 1
        new_words = []
        for w in words:
            if len(seen_words) >= _MAX_WORDS:
                break
            if w.word in seen_words:
                continue
            seen_words.add(w.word)
            new_words.append(
                WordChallenge(study_set=s, word=w.word, clue=w.clue, order=word_order)
            )
            word_order += 1
        WordChallenge.objects.bulk_create(new_words)

        # Progress + status. The increment is under the row lock, so exactly
        # one batch observes the set as complete and triggers finalize.
        s.batches_done = (s.batches_done or 0) + 1
        finalized = s.batches_done >= s.batches_total
        if finalized:
            if s.sections:
                s.status = StudySet.Status.READY
                s.error = ""
            else:
                s.status = StudySet.Status.FAILED
                s.error = "Generation produced no usable content."
        else:
            # PARTIAL only once there is something worth reading.
            s.status = (
                StudySet.Status.PARTIAL if s.sections else StudySet.Status.PROCESSING
            )
        s.save()
        ready = finalized and s.status == StudySet.Status.READY

    return finalized, ready


def _finalize_if_done(finalized, ready, study_set_id, owner):
    """Run once-per-set side effects after the last batch: consume a free
    credit and award creation points. Guarded by `finalized` (exactly one
    batch sees it) so neither can be double-counted."""
    if not (finalized and ready):
        return
    # Consume one free credit only on a set that actually produced content.
    consume_free_credit(owner)
    # Award creation points idempotently (one award per set) so replaying a
    # client request can't farm them.
    from apps.rewards.services import award

    award(
        owner,
        reason="Created a study set",
        dedupe_key=f"studyset:{study_set_id}",
    )
