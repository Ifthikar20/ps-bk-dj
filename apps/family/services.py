"""Progress recording + parent-analytics aggregation."""
from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from apps.studysets.models import StudySet

from .models import GuardianLink, SectionProgress

# A single heartbeat can't add more than this many seconds — stops a client
# from forging huge "time spent" numbers in one call.
MAX_HEARTBEAT_SECONDS = 120


def record_heartbeat(student, study_set, section_index, section_title, seconds):
    seconds = max(0, min(int(seconds or 0), MAX_HEARTBEAT_SECONDS))
    with transaction.atomic():
        row, _ = SectionProgress.objects.select_for_update().get_or_create(
            student=student,
            study_set=study_set,
            section_index=section_index,
            defaults={"section_title": section_title or ""},
        )
        row.seconds_spent += seconds
        if section_title and not row.section_title:
            row.section_title = section_title
        row.save(update_fields=["seconds_spent", "section_title", "updated_at"])
    return row


def mark_complete(student, study_set, section_index, section_title, correct, total):
    with transaction.atomic():
        row, _ = SectionProgress.objects.select_for_update().get_or_create(
            student=student,
            study_set=study_set,
            section_index=section_index,
            defaults={"section_title": section_title or ""},
        )
        row.completed = True
        row.completed_at = row.completed_at or timezone.now()
        row.quiz_correct = max(row.quiz_correct, int(correct or 0))
        row.quiz_total = max(row.quiz_total, int(total or 0))
        if section_title:
            row.section_title = section_title
        row.save()
    return row


def _is_linked(parent, student) -> bool:
    return GuardianLink.objects.filter(parent=parent, student=student).exists()


def student_analytics(student) -> dict:
    """Aggregate a student's learning progress for the analytics board."""
    rows = list(
        SectionProgress.objects.filter(student=student).select_related("study_set")
    )

    # Group progress rows by study set.
    by_set: dict = {}
    for r in rows:
        by_set.setdefault(r.study_set_id, []).append(r)

    sets_out = []
    total_seconds = 0
    total_completed = 0
    total_sections = 0

    # Iterate the student's study sets so we know the true section count even
    # for sets they've barely touched.
    for s in StudySet.objects.filter(owner=student).order_by("-created_at"):
        section_total = len(s.sections or []) or 0
        prog = by_set.get(s.id, [])
        seconds = sum(p.seconds_spent for p in prog)
        completed = sum(1 for p in prog if p.completed)
        scored = [p for p in prog if p.quiz_total > 0]
        avg_pct = (
            round(
                100
                * sum(p.quiz_correct for p in scored)
                / max(1, sum(p.quiz_total for p in scored))
            )
            if scored
            else None
        )
        total_seconds += seconds
        total_completed += completed
        total_sections += section_total
        sets_out.append(
            {
                "id": str(s.id),
                "title": s.title,
                "sectionsTotal": section_total,
                "sectionsCompleted": completed,
                "secondsSpent": seconds,
                "avgScorePct": avg_pct,
                "sections": [
                    {
                        "index": p.section_index,
                        "title": p.section_title,
                        "secondsSpent": p.seconds_spent,
                        "completed": p.completed,
                        "scorePct": (
                            round(100 * p.quiz_correct / p.quiz_total)
                            if p.quiz_total
                            else None
                        ),
                    }
                    for p in sorted(prog, key=lambda x: x.section_index)
                ],
            }
        )

    rewards = getattr(student, "rewards", None)
    return {
        "student": {
            "id": str(student.id),
            "name": student.name or student.email.split("@")[0],
            "email": student.email,
        },
        "totals": {
            "secondsSpent": total_seconds,
            "sectionsCompleted": total_completed,
            "sectionsTotal": total_sections,
            "completionPct": (
                round(100 * total_completed / total_sections)
                if total_sections
                else 0
            ),
            "points": getattr(rewards, "points", 0),
            "streak": getattr(rewards, "streak", 0),
            "studySets": len(sets_out),
        },
        "studySets": sets_out,
    }
