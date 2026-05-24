import logging
import time

from celery import shared_task
from django.db import transaction
from django.db.models import F

from apps.common.exceptions import GenerationError
from apps.studysets.models import QuizQuestion, StudySet, WordChallenge
from apps.subscriptions.models import Subscription

from .extraction import extract_text
from .llm import run_llm

logger = logging.getLogger(__name__)


def _derive_title(source_kind, source_ref):
    if source_kind == "link":
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

        result = run_llm(text)

        with transaction.atomic():
            s = StudySet.objects.select_for_update().get(id=study_set_id)
            s.summary = result.summary
            s.key_points = result.key_points
            s.topics = result.topics
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
                        order=i,
                    )
                    for i, q in enumerate(result.quiz)
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
            "Generated StudySet %s in %.1fs (quiz=%d words=%d)",
            study_set_id,
            time.monotonic() - started,
            len(result.quiz),
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
