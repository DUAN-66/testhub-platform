from rest_framework.routers import DefaultRouter

from .views import ContractViewSet, QualityViewSet, ReportViewSet

router = DefaultRouter()
router.register('contracts', ContractViewSet, basename='contract')
router.register('quality', QualityViewSet, basename='quality')
router.register('gate-reports', ReportViewSet, basename='gate-report')
urlpatterns = router.urls
