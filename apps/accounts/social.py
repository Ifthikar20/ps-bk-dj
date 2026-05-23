"""Server-side verification of Apple / Google ID tokens.

The app sends the provider's signed ID token; we verify the signature and
audience here and only then mint our own JWTs. The provider's stable subject
(`sub`) is what we key the account on.
"""
from dataclasses import dataclass

import jwt
import requests
from django.conf import settings
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from apps.common.exceptions import DomainError

APPLE_KEYS_URL = "https://appleid.apple.com/auth/keys"
APPLE_ISSUER = "https://appleid.apple.com"


class SocialAuthError(DomainError):
    status_code = 401
    default_code = "invalid_id_token"
    default_detail = "Could not verify the sign-in token."


@dataclass
class SocialIdentity:
    sub: str
    email: str
    name: str


def verify_google(id_token_str: str) -> SocialIdentity:
    audience = settings.GOOGLE_OAUTH_CLIENT_IDS
    if not audience:
        raise SocialAuthError("Google sign-in is not configured.")
    try:
        claims = google_id_token.verify_oauth2_token(
            id_token_str, google_requests.Request()
        )
    except ValueError as exc:
        raise SocialAuthError(str(exc))

    if claims.get("aud") not in audience:
        raise SocialAuthError("Token audience mismatch.")
    if claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise SocialAuthError("Token issuer mismatch.")

    return SocialIdentity(
        sub=claims["sub"],
        email=claims.get("email", ""),
        name=claims.get("name", ""),
    )


def verify_apple(id_token_str: str) -> SocialIdentity:
    audiences = settings.APPLE_BUNDLE_IDS
    if not audiences:
        raise SocialAuthError("Apple sign-in is not configured.")
    try:
        unverified_header = jwt.get_unverified_header(id_token_str)
        jwks = requests.get(APPLE_KEYS_URL, timeout=5).json()["keys"]
        key = next(k for k in jwks if k["kid"] == unverified_header["kid"])
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
        claims = jwt.decode(
            id_token_str,
            public_key,
            algorithms=["RS256"],
            audience=list(audiences),
            issuer=APPLE_ISSUER,
        )
    except (jwt.PyJWTError, StopIteration, KeyError, ValueError) as exc:
        raise SocialAuthError(f"Invalid Apple token: {exc}")

    return SocialIdentity(
        sub=claims["sub"],
        email=claims.get("email", ""),
        # Apple only sends the name on first consent (in the app, not the token).
        name=claims.get("name", ""),
    )


def verify_id_token(provider: str, id_token_str: str) -> SocialIdentity:
    if provider == "google":
        return verify_google(id_token_str)
    if provider == "apple":
        return verify_apple(id_token_str)
    raise SocialAuthError("Unsupported provider.")
