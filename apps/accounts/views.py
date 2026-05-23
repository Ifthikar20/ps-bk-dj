from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.common.exceptions import DomainError
from apps.common.throttles import AuthThrottle

from .serializers import (
    EmailAuthSerializer,
    ProviderAuthSerializer,
    RefreshSerializer,
    SignOutSerializer,
    UserSerializer,
    run_password_validators,
)
from .social import verify_id_token

User = get_user_model()


def tokens_for(user):
    refresh = RefreshToken.for_user(user)
    return {"access_token": str(refresh.access_token), "refresh_token": str(refresh)}


def auth_payload(user):
    return {**tokens_for(user), "user": UserSerializer(user).data}


class InvalidCredentials(DomainError):
    status_code = 401
    default_code = "invalid_credentials"
    default_detail = "Email or password is incorrect."


class EmailAuthView(APIView):
    """Single endpoint for login + sign-up (mirrors the app's one auth call).

    If the account exists, the password is checked. If it doesn't, a new
    account is created with full password-strength validation.
    """

    permission_classes = [AllowAny]
    throttle_classes = [AuthThrottle]
    throttle_scope = "auth"

    def post(self, request):
        serializer = EmailAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].lower()
        password = serializer.validated_data["password"]
        name = serializer.validated_data.get("name", "")

        user = User.objects.filter(email=email).first()
        if user is not None:
            if user.provider != User.Provider.EMAIL or not user.check_password(password):
                raise InvalidCredentials()
            return Response(auth_payload(user))

        # New account — enforce real password rules.
        run_password_validators(password)
        with transaction.atomic():
            user = User.objects.create_user(
                email=email,
                password=password,
                name=name or email.split("@")[0],
                provider=User.Provider.EMAIL,
            )
        return Response(auth_payload(user), status=status.HTTP_201_CREATED)


class ProviderAuthView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AuthThrottle]
    throttle_scope = "auth"

    def post(self, request):
        serializer = ProviderAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        provider = serializer.validated_data["provider"]
        identity = verify_id_token(provider, serializer.validated_data["id_token"])

        with transaction.atomic():
            user = (
                User.objects.select_for_update()
                .filter(provider=provider, provider_sub=identity.sub)
                .first()
            )
            if user is None:
                # Link by email if a matching account already exists.
                user = User.objects.filter(email=identity.email.lower()).first()
                if user is None:
                    user = User.objects.create_user(
                        email=identity.email.lower() or f"{identity.sub}@{provider}.local",
                        name=identity.name or "Student",
                        provider=provider,
                        provider_sub=identity.sub,
                    )
                else:
                    user.provider = provider
                    user.provider_sub = identity.sub
                    if not user.name and identity.name:
                        user.name = identity.name
                    user.save(update_fields=["provider", "provider_sub", "name"])

        return Response(auth_payload(user))


class RefreshView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AuthThrottle]
    throttle_scope = "auth"

    def post(self, request):
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            refresh = RefreshToken(serializer.validated_data["refresh_token"])
            access = str(refresh.access_token)
        except TokenError:
            raise InvalidCredentials("Refresh token is invalid or expired.")
        return Response({"access_token": access})


class SignOutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SignOutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            RefreshToken(serializer.validated_data["refresh_token"]).blacklist()
        except TokenError:
            pass  # Already invalid — signing out is idempotent.
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    """Launch bootstrap: auth + rewards + subscription in one round trip."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.rewards.serializers import RewardProfileSerializer
        from apps.rewards.services import get_rewards_state
        from apps.subscriptions.serializers import SubscriptionSerializer

        user = request.user
        return Response(
            {
                "user": UserSerializer(user).data,
                "rewards": RewardProfileSerializer(get_rewards_state(user)).data,
                "subscription": SubscriptionSerializer(
                    user.subscription, context={"request": request}
                ).data,
            }
        )
