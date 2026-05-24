from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from .serializers import RewardProfileSerializer
from .services import CLIENT_REPORTABLE_REASONS, award, get_rewards_state


class RewardsActivityThrottle(UserRateThrottle):
    scope = "rewards"


class ActivitySerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=sorted(CLIENT_REPORTABLE_REASONS))
    context = serializers.DictField(required=False, default=dict)


class RewardsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = get_rewards_state(request.user)
        return Response(RewardProfileSerializer(profile).data)


class ActivityView(APIView):
    """Records in-app gameplay rewards the server can't directly observe
    (quiz / word game / Super Dash). Creation and exam-session rewards are
    granted server-side on the real event and are rejected here.
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [RewardsActivityThrottle]

    def post(self, request):
        serializer = ActivitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = award(
            request.user,
            reason=serializer.validated_data["reason"],
            context=serializer.validated_data.get("context", {}),
        )
        return Response(RewardProfileSerializer(result["profile"]).data)
