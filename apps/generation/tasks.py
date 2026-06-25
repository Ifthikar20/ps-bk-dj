import logging
import time

from celery import shared_task
from django.db import transaction
from django.db.models import F

from apps.common.exceptions import GenerationError
from apps.studysets.models import QuizQuestion, StudySet, WordChallenge
from apps.subscriptions.models import Subscription

from .extraction import _youtube_id, _youtube_title, extract_text
from .llm import generate

logger = logging.getLogger(__name__)


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

        result, usage = generate(text)

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

            # Consume one free credit only on success.
            Subscription.objects.filter(user=s.owner, is_premium=False).update(
                usage_count=F("usage_count") + 1
            )

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
