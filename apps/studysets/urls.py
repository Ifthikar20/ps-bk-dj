from rest_framework.routers import DefaultRouter

from .views import StudySetViewSet

router = DefaultRouter()
router.register("studysets", StudySetViewSet, basename="studyset")

urlpatterns = router.urls
