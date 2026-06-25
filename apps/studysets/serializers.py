from rest_framework import serializers

from .models import QuizQuestion, StudySet, WordChallenge


class QuizQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuizQuestion
        fields = (
            "id",
            "prompt",
            "choices",
            "correct_index",
            "explanation",
            "topic",
            "difficulty",
        )


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
    progress = serializers.SerializerMethodField()

    class Meta:
        model = StudySet
        fields = (
            "id",
            "status",
            "error",
            "batches_total",
            "batches_done",
            "progress",
        )

    def get_progress(self, obj):
        """0.0–1.0 fraction of batches complete (0.0 until fan-out begins)."""
        if not obj.batches_total:
            return 0.0
        return round(obj.batches_done / obj.batches_total, 3)


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
            # Forgive a missing scheme on a bare hostname like
            # "files.eric.ed.gov/x.pdf" — assume https.
            if not ref.lower().startswith(("http://", "https://")):
                bare = ref.split("/", 1)[0]
                if "." in bare and " " not in bare and bare[0].isalnum():
                    ref = "https://" + ref
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
