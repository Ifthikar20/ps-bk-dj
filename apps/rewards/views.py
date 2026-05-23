from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import RewardProfileSerializer
from .services import award, get_rewards_state


class ActivitySerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=64)
    context = serializers.DictField(required=False, default=dict)


class RewardsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = get_rewards_state(request.user)
        return Response(RewardProfileSerializer(profile).data)


class ActivityView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ActivitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = award(
            request.user,
            reason=serializer.validated_data["reason"],
            context=serializer.validated_data.get("context", {}),
        )
        return Response(RewardProfileSerializer(result["profile"]).data)
