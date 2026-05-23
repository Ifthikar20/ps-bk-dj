from rest_framework.permissions import BasePermission


class IsOwner(BasePermission):
    """Object-level permission: a user may only touch rows they own.

    Works for models exposing either an ``owner`` or ``user`` FK to the user.
    """

    message = "You do not have access to this resource."

    def has_object_permission(self, request, view, obj):
        owner = getattr(obj, "owner", None) or getattr(obj, "user", None)
        return owner == request.user
