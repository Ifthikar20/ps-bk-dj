import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class SectionProgress(models.Model):
    """Per-student progress + time spent on a single study-set section.

    One row per (student, study_set, section_index). Time is accumulated from
    client heartbeats so the parent analytics board can show how long a student
    spends on each section and how far they've completed.
    """

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="section_progress",
    )
    study_set = models.ForeignKey(
        "studysets.StudySet",
        on_delete=models.CASCADE,
        related_name="section_progress",
    )
    section_index = models.PositiveIntegerField()
    section_title = models.CharField(max_length=160, blank=True, default="")

    seconds_spent = models.PositiveIntegerField(default=0)
    completed = models.BooleanField(default=False)
    quiz_correct = models.PositiveIntegerField(default=0)
    quiz_total = models.PositiveIntegerField(default=0)

    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "study_set", "section_index"],
                name="unique_student_section",
            )
        ]
        indexes = [models.Index(fields=["student", "study_set"])]

    def __str__(self):
        return f"{self.student_id} {self.study_set_id}#{self.section_index}"


class GuardianLink(models.Model):
    """A parent account linked to a student account (read-only analytics access)."""

    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="guardian_of",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="guardians",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["parent", "student"], name="unique_parent_student"
            )
        ]

    def __str__(self):
        return f"{self.parent_id} -> {self.student_id}"


class LinkCode(models.Model):
    """Short, expiring code a student generates; a parent redeems it to link."""

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="link_codes",
    )
    code = models.CharField(max_length=8, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    # Unambiguous alphabet (no O/0/I/1) for codes the user types in.
    _ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

    @classmethod
    def issue(cls, student, ttl_minutes: int = 30) -> "LinkCode":
        cls.objects.filter(student=student).delete()  # one active code per student
        for _ in range(10):
            code = "".join(secrets.choice(cls._ALPHABET) for _ in range(6))
            if not cls.objects.filter(code=code).exists():
                return cls.objects.create(
                    student=student,
                    code=code,
                    expires_at=timezone.now() + timedelta(minutes=ttl_minutes),
                )
        raise RuntimeError("Could not allocate a unique link code.")

    @property
    def is_valid(self) -> bool:
        return timezone.now() < self.expires_at
