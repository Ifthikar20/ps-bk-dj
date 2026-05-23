from django.contrib import admin

from .models import DailyResult, ExamPlan


class ResultInline(admin.TabularInline):
    model = DailyResult
    extra = 0


@admin.register(ExamPlan)
class ExamPlanAdmin(admin.ModelAdmin):
    list_display = ("exam_title", "owner", "exam_date", "questions_per_day")
    search_fields = ("exam_title", "owner__email")
    inlines = [ResultInline]
