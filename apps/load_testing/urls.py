from rest_framework.routers import DefaultRouter
from .views import PerformanceViewSet

router = DefaultRouter()
router.register('performance', PerformanceViewSet, basename='performance')
urlpatterns = router.urls
