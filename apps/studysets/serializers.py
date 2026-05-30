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
            "sections",
            "quiz",
            "word_game",
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
        if kind == StudySet.SourceKind.LINK:
            # Recover from paste artifacts where the URL is duplicated, either
            # cleanly (foo.pdf + foo.pdf) or with overlap that drops the
            # extension (foo. + foo.pdf). The complete URL is always the last
            # one, so keep everything from the last scheme onward.
            lower = ref.lower()
            last = max(lower.rfind("http://"), lower.rfind("https://"))
            if last > 0:
                ref = ref[last:]
            if not ref.lower().startswith(("http://", "https://")):
                raise serializers.ValidationError(
                    {"source_ref": "A valid http(s) URL is required for link sources."}
                )
        if kind == StudySet.SourceKind.TEXT and len(ref) < 20:
            raise serializers.ValidationError(
                {"source_ref": "Pasted text must be at least 20 characters."}
            )
        attrs["source_ref"] = ref
        return attrs
