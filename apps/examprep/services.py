"""Exam-prep domain logic: scheduling, spaced repetition, reminders.

The study guide *content* already exists on the StudySet (sections + quiz). A
plan just schedules it across the days up to the exam, layering in a Leitner
spaced-repetition bucket so missed questions resurface until learned.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction

from .models import DailyResult, PlanDay, PlanReminder, WrongAnswerCard

# Leitner box -> days until a card is due again. Higher box = seen less often.
INTERVALS = {1: 1, 2: 2, 3: 4, 4: 7, 5: 15}
RESOLVE_BOX = 3  # a card retires once it reaches this box


def user_today(user):
    tz = ZoneInfo(getattr(user, "timezone", "UTC") or "UTC")
    return datetime.now(tz).date()


def effective_questions_per_day(plan) -> int:
    return max(1, round(plan.questions_per_day * (plan.frequency_multiplier or 1.0)))


def _quiz_pool(plan):
    """QuizQuestion rows for the plan's material, minus excluded topics."""
    from apps.studysets.models import QuizQuestion

    excluded = set(plan.excluded_topics or [])
    qs = list(QuizQuestion.objects.filter(study_set=plan.study_set).order_by("order"))
    pool = [q for q in qs if q.topic not in excluded]
    return pool or qs  # never end up with zero questions


def _section_pool(plan):
    """(index, section) pairs from the study set, minus excluded titles."""
    excluded = set(plan.excluded_topics or [])
    sections = plan.study_set.sections or []
    pool = [(i, s) for i, s in enumerate(sections) if s.get("title") not in excluded]
    return pool or [(i, s) for i, s in enumerate(sections)]


@transaction.atomic
def build_schedule(plan, *, future_only=False):
    """(Re)build the day-by-day schedule. Idempotent.

    future_only keeps past days + their results intact (used when settings
    change mid-plan); otherwise the whole schedule is rebuilt.
    """
    today = user_today(plan.owner)
    start_index = 0
    if future_only:
        # Keep days up to and including today; rebuild the rest.
        kept = plan.days.filter(ymd__lte=today.isoformat())
        start_index = kept.count()
        plan.days.filter(ymd__gt=today.isoformat()).delete()
        start_day = today + timedelta(days=1)
    else:
        plan.days.all().delete()
        start_day = today

    span = max(1, (plan.exam_date - start_day).days)
    sections = _section_pool(plan)
    pool = _quiz_pool(plan)
    qpd = effective_questions_per_day(plan)

    rows = []
    for offset in range(span):
        i = start_index + offset
        ymd = (start_day + timedelta(days=offset)).isoformat()
        sec_index, sec = sections[i % len(sections)]
        if pool:
            qids = [
                str(pool[(i * qpd + j) % len(pool)].id) for j in range(qpd)
            ]
        else:
            qids = []
        rows.append(
            PlanDay(
                plan=plan,
                ymd=ymd,
                day_index=i,
                section_index=sec_index,
                section_title=sec.get("title", "") if isinstance(sec, dict) else "",
                question_ids=qids,
            )
        )
    PlanDay.objects.bulk_create(rows)
    return list(plan.days.all())


def create_reminders(plan):
    """One daily nudge per scheduled day + a deadline-approaching nudge."""
    for day in plan.days.all():
        PlanReminder.objects.get_or_create(
            plan=plan,
            ymd=day.ymd,
            kind="daily",
            defaults={"message": f"Study “{plan.exam_title}” — day {day.day_index + 1}"},
        )
    soon = (plan.exam_date - timedelta(days=3)).isoformat()
    PlanReminder.objects.get_or_create(
        plan=plan,
        ymd=soon,
        kind="deadline_soon",
        defaults={"message": f"“{plan.exam_title}” is in 3 days — keep going!"},
    )


def cards_due(plan, ymd):
    return list(
        plan.cards.filter(resolved=False, due_ymd__lte=ymd).order_by("box", "due_ymd")
    )


def apply_session_results(plan, ymd, wrong_ids, correct_ids):
    """Update the Leitner bucket from a day's answers."""
    base = datetime.strptime(ymd, "%Y-%m-%d").date()

    def due_after(box):
        d = base + timedelta(days=INTERVALS[box])
        return min(d, plan.exam_date).isoformat()

    pool = {str(q.id): q for q in _quiz_pool(plan)}

    for qid in wrong_ids or []:
        q = pool.get(str(qid))
        card, _ = WrongAnswerCard.objects.get_or_create(
            plan=plan,
            question_id=qid,
            defaults={"topic": q.topic if q else "General", "due_ymd": ymd},
        )
        card.box = max(1, card.box - 1)
        card.times_wrong += 1
        card.resolved = False
        card.due_ymd = due_after(card.box)
        card.save()

    for qid in correct_ids or []:
        card = plan.cards.filter(question_id=qid).first()
        if not card:
            continue  # only questions that were once wrong have cards
        card.times_right += 1
        card.box = min(5, card.box + 1)
        if card.box >= RESOLVE_BOX:
            card.resolved = True
        card.due_ymd = due_after(card.box)
        card.save()


def get_active_day(plan):
    """The day to show: today's row, else the next unfinished, else the last."""
    today = user_today(plan.owner).isoformat()
    day = plan.days.filter(ymd=today).first()
    if day:
        return day
    done = set(plan.results.values_list("ymd", flat=True))
    for d in plan.days.all():
        if d.ymd not in done:
            return d
    return plan.days.last()


def serialize_day(plan, day, *, include_review=True):
    """Build the daily-session payload for a PlanDay (snake keys; the response
    renderer camel-cases them)."""
    from apps.studysets.models import QuizQuestion
    from apps.studysets.serializers import QuizQuestionSerializer

    if day is None:
        return None

    sections = plan.study_set.sections or []
    sec = sections[day.section_index] if day.section_index < len(sections) else {}

    by_id = {
        str(q.id): q
        for q in QuizQuestion.objects.filter(id__in=day.question_ids)
    }
    questions = [by_id[qid] for qid in day.question_ids if qid in by_id]

    review = []
    if include_review:
        cap = max(1, effective_questions_per_day(plan) // 2)
        review_cards = cards_due(plan, day.ymd)[:cap]
        rids = [str(c.question_id) for c in review_cards]
        rmap = {
            str(q.id): q for q in QuizQuestion.objects.filter(id__in=rids)
        }
        review = [rmap[i] for i in rids if i in rmap]

    result = plan.results.filter(ymd=day.ymd).first()

    return {
        "date": day.ymd,
        "day_index": day.day_index,
        "status": plan.status,
        "section": {
            "title": sec.get("title", "") if isinstance(sec, dict) else "",
            "content": sec.get("content", "") if isinstance(sec, dict) else "",
            "example": sec.get("example", "") if isinstance(sec, dict) else "",
        },
        "questions": QuizQuestionSerializer(questions, many=True).data,
        "review_questions": QuizQuestionSerializer(review, many=True).data,
        "result": (
            {"correct": result.correct, "total": result.total, "completed": result.completed}
            if result
            else None
        ),
    }


def maybe_complete(plan):
    if plan.status != plan.Status.ACTIVE:
        return
    today = user_today(plan.owner)
    done = set(plan.results.values_list("ymd", flat=True))
    all_done = plan.days.exists() and all(d.ymd in done for d in plan.days.all())
    if today > plan.exam_date or all_done:
        plan.status = plan.Status.COMPLETED
        plan.save(update_fields=["status"])
