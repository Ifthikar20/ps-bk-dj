from rest_framework.routers import DefaultRouter

from .views import ExamPlanViewSet

router = DefaultRouter()
router.register("examplans", ExamPlanViewSet, basename="examplan")

urlpatterns = router.urls
