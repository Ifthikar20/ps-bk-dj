from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import DomainError
from apps.studysets.models import StudySet

from .models import GuardianLink, LinkCode, SectionProgress
from .serializers import CompleteSerializer, HeartbeatSerializer, RedeemSerializer
from .services import mark_complete, record_heartbeat, student_analytics


def _owned_set(user, study_set_id):
    return get_object_or_404(StudySet, id=study_set_id, owner=user)


# --------------------------------------------------------------------------- #
# Progress (the student records their own time + completion)
# --------------------------------------------------------------------------- #
class HeartbeatView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        s = HeartbeatSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        study_set = _owned_set(request.user, d["study_set_id"])
        row = record_heartbeat(
            request.user, study_set, d["section_index"], d["section_title"], d["seconds"]
        )
        return Response({"secondsSpent": row.seconds_spent})


class CompleteSectionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        s = CompleteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        study_set = _owned_set(request.user, d["study_set_id"])
        row = mark_complete(
            request.user,
            study_set,
            d["section_index"],
            d["section_title"],
            d["correct"],
            d["total"],
        )
        return Response({"completed": row.completed})


class MyProgressView(APIView):
    """A student's own progress (same shape as the parent analytics board)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(student_analytics(request.user))


# --------------------------------------------------------------------------- #
# Guardian linking
# --------------------------------------------------------------------------- #
class LinkCodeView(APIView):
    """Student issues / fetches a short code to share with a parent."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        code = LinkCode.issue(request.user)
        return Response(
            {"code": code.code, "expiresAt": code.expires_at}, status=status.HTTP_201_CREATED
        )


class RedeemCodeView(APIView):
    """Parent redeems a student's code; the requester becomes the parent."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        s = RedeemSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        code = s.validated_data["code"].strip().upper()
        try:
            link_code = LinkCode.objects.select_related("student").get(code=code)
        except LinkCode.DoesNotExist:
            raise DomainError("That code is invalid.", code="bad_code")
        if not link_code.is_valid:
            raise DomainError("That code has expired.", code="expired_code")
        if link_code.student_id == request.user.id:
            raise DomainError("You can't link to your own account.", code="self_link")

        GuardianLink.objects.get_or_create(
            parent=request.user, student=link_code.student
        )
        link_code.delete()  # one-time use
        return Response(
            {
                "student": {
                    "id": str(link_code.student.id),
                    "name": link_code.student.name
                    or link_code.student.email.split("@")[0],
                }
            },
            status=status.HTTP_201_CREATED,
        )


class StatusView(APIView):
    """Who am I linked to? Drives the app's parent-mode UI."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        children = GuardianLink.objects.filter(parent=request.user).select_related(
            "student"
        )
        parents = GuardianLink.objects.filter(student=request.user).select_related(
            "parent"
        )
        return Response(
            {
                "isParent": children.exists(),
                "children": [
                    {
                        "linkId": l.id,
                        "id": str(l.student.id),
                        "name": l.student.name or l.student.email.split("@")[0],
                        "email": l.student.email,
                    }
                    for l in children
                ],
                "parents": [
                    {
                        "linkId": l.id,
                        "id": str(l.parent.id),
                        "name": l.parent.name or l.parent.email.split("@")[0],
                        "email": l.parent.email,
                    }
                    for l in parents
                ],
            }
        )


class ChildAnalyticsView(APIView):
    """Parent reads a linked student's analytics board."""

    permission_classes = [IsAuthenticated]

    def get(self, request, student_id):
        link = GuardianLink.objects.filter(
            parent=request.user, student_id=student_id
        ).select_related("student").first()
        if link is None:
            raise DomainError("You are not linked to this student.", code="not_linked")
        return Response(student_analytics(link.student))


class UnlinkView(APIView):
    """Either side may remove a link (by its id)."""

    permission_classes = [IsAuthenticated]

    def delete(self, request, link_id):
        link = GuardianLink.objects.filter(id=link_id).first()
        if link is None or request.user.id not in (link.parent_id, link.student_id):
            raise DomainError("Link not found.", code="not_found")
        link.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
