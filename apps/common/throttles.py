from rest_framework.throttling import ScopedRateThrottle, UserRateThrottle


class GenerationThrottle(UserRateThrottle):
    scope = "generation"


class AuthThrottle(ScopedRateThrottle):
    """Throttle login/auth endpoints by IP to slow brute-force attempts."""

    scope = "auth"
