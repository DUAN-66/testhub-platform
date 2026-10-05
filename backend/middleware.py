from django.utils.deprecation import MiddlewareMixin
from django.conf import settings
from django.http import JsonResponse


class CoreModuleBoundaryMiddleware(MiddlewareMixin):
    """Production starts with the audited API execution surface only."""
    API_PREFIXES = (
        '/api/auth/', '/api/users/', '/api/v1/contracts/', '/api/v1/quality/',
        '/api/api-testing/projects/', '/api/api-testing/collections/',
        '/api/api-testing/requests/', '/api/api-testing/environments/',
        '/api/api-testing/histories/', '/api/api-testing/test-suites/',
        '/api/api-testing/test-suite-requests/', '/api/api-testing/test-executions/',
        '/api/api-testing/users/', '/api/api-testing/dashboard/', '/api/api-testing/operation-logs/',
        '/api/schema/', '/api/docs/', '/api/redoc/',
    )

    def process_request(self, request):
        if settings.CORE_ONLY_MODE:
            path = request.path + ('/' if not request.path.endswith('/') else '')
            if path.endswith(('/send-register-code/', '/sms-login/', '/captcha/')):
                return JsonResponse({'error': 'Optional SMS module disabled by CORE_ONLY_MODE'}, status=403)
            if path.startswith('/api/') and not path.startswith(self.API_PREFIXES):
                return JsonResponse({'error': 'Optional module disabled by CORE_ONLY_MODE'}, status=403)
            if path.startswith(('/app-automation-templates/', '/app-automation-reports/')):
                return JsonResponse({'error': 'Optional module disabled by CORE_ONLY_MODE'}, status=403)
        return None

class DisableCSRFMiddleware(MiddlewareMixin):
    def process_request(self, request):
        # Compatibility import only; session requests must retain CSRF protection.
        return None
