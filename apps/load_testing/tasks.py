from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from apps.api_testing.services.http_transport import RestrictedHttpClient
from .engine import measure
from .models import PerformanceRun
from .services import definition, fingerprint, validate_access


@shared_task(bind=True, time_limit=90, soft_time_limit=80)
def execute_performance(self, identifier):
    with transaction.atomic():
        run = PerformanceRun.objects.select_for_update().get(pk=identifier)
        if run.status != 'QUEUED' or run.task_id != self.request.id:
            return
        run.status = 'RUNNING'
        run.save(update_fields=['status'])
    try:
        validate_access(run.request, run.environment, run.created_by, run.gate)
        if fingerprint(run.request, run.environment) != run.configuration_digest:
            raise ValueError('Configuration changed')
        summary = measure(definition(run.request), run.environment.variables if run.environment else {},
                          run.workload, RestrictedHttpClient(allowed_hosts=settings.PERFORMANCE_ALLOWED_HOSTS))
        run.request.refresh_from_db()
        if run.environment:
            run.environment.refresh_from_db()
        run.created_by.refresh_from_db()
        validate_access(run.request, run.environment, run.created_by, run.gate)
        if fingerprint(run.request, run.environment) != run.configuration_digest:
            raise ValueError('Configuration changed during measurement')
        run.summary, run.status = summary, 'COMPLETED'
    except Exception:
        run.status, run.error_code = 'FAILED', 'MEASUREMENT_FAILED'
    run.finished_at = timezone.now()
    run.save(update_fields=['summary', 'status', 'error_code', 'finished_at'])
