from rest_framework import serializers

from .models import QuizQuestion, StudySet, WordChallenge


class QuizQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuizQuestion
        fields = ("id", "prompt", "choices", "correct_index", "explanation", "topic")


class WordChallengeSerializer(serializers.ModelSerializer):
    class Meta:
        model = WordChallenge
        fields = ("word", "clue")


class StudySetSerializer(serializers.ModelSerializer):
    """Full shape consumed by LearningMaterial.fromJson."""

    quiz = QuizQuestionSerializer(many=True, read_only=True)
    word_game = WordChallengeSerializer(many=True, read_only=True)

    class Meta:
        model = StudySet
        fields = (
            "id",
            "title",
            "source_kind",
            "source_ref",
            "summary",
            "key_points",
            "topics",
            "quiz",
            "word_game",
            "status",
            "created_at",
        )


class StudySetListSerializer(serializers.ModelSerializer):
    """Lightweight library row — omits the heavy quiz/word-game arrays.

    The client lazy-loads those via the detail endpoint when a set is opened.
    """

    class Meta:
        model = StudySet
        fields = (
            "id",
            "title",
            "source_kind",
            "source_ref",
            "summary",
            "topics",
            "status",
            "created_at",
        )


class StudySetStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudySet
        fields = ("id", "status", "error")


class StudySetCreateSerializer(serializers.Serializer):
    """Input for POST /studysets/ (the generate call)."""

    source_kind = serializers.ChoiceField(choices=StudySet.SourceKind.values)
    source_ref = serializers.CharField()
    title = serializers.CharField(required=False, allow_blank=True, max_length=255)

    def validate(self, attrs):
        kind = attrs["source_kind"]
        ref = attrs["source_ref"].strip()
        if not ref:
            raise serializers.ValidationError({"source_ref": "This field is required."})
        if kind == StudySet.SourceKind.LINK and not ref.lower().startswith(
            ("http://", "https://")
        ):
            raise serializers.ValidationError(
                {"source_ref": "A valid http(s) URL is required for link sources."}
            )
        if kind == StudySet.SourceKind.TEXT and len(ref) < 20:
            raise serializers.ValidationError(
                {"source_ref": "Pasted text must be at least 20 characters."}
            )
        attrs["source_ref"] = ref
        return attrs
