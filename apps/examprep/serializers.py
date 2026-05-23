from rest_framework import serializers

from apps.studysets.models import StudySet

from .models import ExamPlan


class ExamPlanSerializer(serializers.ModelSerializer):
    """Matches ExamPlan.toJson() / fromJson() exactly."""

    material_id = serializers.PrimaryKeyRelatedField(
        source="study_set",
        queryset=StudySet.objects.all(),
    )
    material_title = serializers.CharField(read_only=True)
    results = serializers.SerializerMethodField()

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
            "created_at",
            "results",
        )
        read_only_fields = ("id", "created_at", "material_title", "results")

    def get_results(self, obj):
        # { "2026-05-23": {"correct":4,"total":5,"completed":true} }
        return {
            r.ymd: {
                "correct": r.correct,
                "total": r.total,
                "completed": r.completed,
            }
            for r in obj.results.all()
        }

    def validate_material_id(self, study_set):
        request = self.context["request"]
        if study_set.owner_id != request.user.id:
            raise serializers.ValidationError("Study set not found.")
        return study_set

    def create(self, validated_data):
        validated_data["owner"] = self.context["request"].user
        validated_data["material_title"] = validated_data["study_set"].title
        return super().create(validated_data)


class SessionSerializer(serializers.Serializer):
    day = serializers.CharField(max_length=10)  # "yyyy-MM-dd"
    correct = serializers.IntegerField(min_value=0)
    total = serializers.IntegerField(min_value=0)

    def validate(self, attrs):
        if attrs["correct"] > attrs["total"]:
            raise serializers.ValidationError("correct cannot exceed total.")
        return attrs
