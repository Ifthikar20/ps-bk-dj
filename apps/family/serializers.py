from rest_framework import serializers


class HeartbeatSerializer(serializers.Serializer):
    study_set_id = serializers.UUIDField()
    section_index = serializers.IntegerField(min_value=0)
    section_title = serializers.CharField(required=False, allow_blank=True, default="")
    seconds = serializers.IntegerField(min_value=0, max_value=600)


class CompleteSerializer(serializers.Serializer):
    study_set_id = serializers.UUIDField()
    section_index = serializers.IntegerField(min_value=0)
    section_title = serializers.CharField(required=False, allow_blank=True, default="")
    correct = serializers.IntegerField(min_value=0, default=0)
    total = serializers.IntegerField(min_value=0, default=0)


class RedeemSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=8)
