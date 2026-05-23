from django.contrib import admin

from .models import QuizQuestion, StudySet, WordChallenge


class QuizInline(admin.TabularInline):
    model = QuizQuestion
    extra = 0


class WordInline(admin.TabularInline):
    model = WordChallenge
    extra = 0


@admin.register(StudySet)
class StudySetAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "source_kind", "status", "created_at")
    list_filter = ("status", "source_kind")
    search_fields = ("title", "owner__email", "source_ref")
    readonly_fields = ("id", "created_at", "updated_at")
    inlines = [QuizInline, WordInline]
