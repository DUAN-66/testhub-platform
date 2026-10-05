from django.conf import settings
from rest_framework.exceptions import ValidationError
from apps.api_testing.models import TestSuiteRequest
from apps.api_testing.services import ApiExecutionService
from apps.contracts.engine import digest


def definition(request):
    return {key: getattr(request, key) for key in
            ['method', 'url', 'headers', 'params', 'body', 'auth', 'assertions']}


def fingerprint(request, environment):
    return digest({'request': definition(request), 'environment_id': environment.pk if environment else None,
                   'variables': environment.variables if environment else {},
                   'allowed_hosts': sorted(settings.PERFORMANCE_ALLOWED_HOSTS)})


def validate_access(request, environment, user, gate=None):
    project = request.collection.project if request.collection_id else None
    if not user.is_active or not project or not (project.owner_id == user.id or project.members.filter(pk=user.pk).exists()):
        raise ValidationError('Request is outside your project')
    if request.method not in {'GET', 'HEAD'} or request.request_type != 'HTTP':
        raise ValidationError('Only saved HTTP GET/HEAD requests are supported')
    try:
        ApiExecutionService.validate_environment_access(environment, user)
    except ValueError as exc:
        raise ValidationError('Environment is outside your access') from exc
    if environment and environment.scope == 'LOCAL' and environment.project_id != project.pk:
        raise ValidationError('Environment belongs to a different project')
    if gate:
        if gate.created_by_id != user.pk or gate.project_id != project.pk or 'performance' not in gate.plan['policy']:
            raise ValidationError('Gate must belong to this user/project and require performance evidence')
        links = TestSuiteRequest.objects.filter(test_suite_id__in=gate.plan['impact']['suite_ids'],
                                               request=request, enabled=True)
        if not links.filter(test_suite__environment=environment).exists():
            raise ValidationError('Request/environment must belong to an impacted gate suite')
    return project
