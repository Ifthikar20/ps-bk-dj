from rest_framework import serializers

from apps.studysets.models import StudySet

from .models import ExamPlan


class ExamPlanSerializer(serializers.ModelSerializer):
    """Matches ExamPlan.toJson() / fromJson(), plus guide/state fields."""

    material_id = serializers.PrimaryKeyRelatedField(
        source="study_set",
        queryset=StudySet.objects.all(),
    )
    material_title = serializers.CharField(read_only=True)
    results = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()
    # Web guide flow opts in to start as a draft; mobile omits it -> active.
    start_as_draft = serializers.BooleanField(
        write_only=True, required=False, default=False
    )

    class Meta:
        model = ExamPlan
        fields = (
            "id",
            "material_id",
            "material_title",
            "exam_title",
            "exam_date",
            "questions_per_day",
            "topics",
            "status",
            "approved_at",
            "excluded_topics",
            "frequency_multiplier",
            "created_at",
            "results",
            "progress",
            "start_as_draft",
        )
        read_only_fields = (
            "id",
            "created_at",
            "material_title",
            "results",
            "progress",
            "status",
            "approved_at",
        )

    def get_results(self, obj):
        return {
            r.ymd: {"correct": r.correct, "total": r.total, "completed": r.completed}
            for r in obj.results.all()
        }

    def get_progress(self, obj):
        total = obj.days.count()
        done = obj.results.filter(completed=True).count()
        return {"totalDays": total, "completedDays": min(done, total) if total else done}

    def validate_material_id(self, study_set):
        request = self.context["request"]
        if study_set.owner_id != request.user.id:
            raise serializers.ValidationError("Study set not found.")
        return study_set

    def create(self, validated_data):
        as_draft = validated_data.pop("start_as_draft", False)
        validated_data["owner"] = self.context["request"].user
        validated_data["material_title"] = validated_data["study_set"].title
        validated_data["status"] = (
            ExamPlan.Status.DRAFT if as_draft else ExamPlan.Status.ACTIVE
        )
        return super().create(validated_data)


class SessionSerializer(serializers.Serializer):
    day = serializers.CharField(max_length=10)  # "yyyy-MM-dd"
    correct = serializers.IntegerField(min_value=0)
    total = serializers.IntegerField(min_value=0)
    wrong_question_ids = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )
    correct_question_ids = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )

    def validate(self, attrs):
        if attrs["correct"] > attrs["total"]:
            raise serializers.ValidationError("correct cannot exceed total.")
        return attrs


class SettingsSerializer(serializers.Serializer):
    frequency_multiplier = serializers.FloatField(
        required=False, min_value=0.25, max_value=4.0
    )
    excluded_topics = serializers.ListField(
        child=serializers.CharField(), required=False
    )
    questions_per_day = serializers.IntegerField(
        required=False, min_value=1, max_value=50
    )
