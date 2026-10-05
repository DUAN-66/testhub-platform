import uuid
from django.conf import settings
from django.db import models


class PerformanceRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey('api_testing.ApiProject', on_delete=models.CASCADE)
    request = models.ForeignKey('api_testing.ApiRequest', on_delete=models.CASCADE)
    environment = models.ForeignKey('api_testing.Environment', null=True, on_delete=models.SET_NULL)
    gate = models.OneToOneField('quality_gates.GateRun', null=True, blank=True,
                              on_delete=models.CASCADE, related_name='performance_run')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    idempotency_key = models.CharField(max_length=128)
    digest = models.CharField(max_length=64)
    configuration_digest = models.CharField(max_length=64)
    workload = models.JSONField()
    task_id = models.CharField(max_length=36)
    status = models.CharField(max_length=20, default='QUEUED')
    summary = models.JSONField(default=dict)
    error_code = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['project', 'created_by', 'idempotency_key'],
                                               name='performance_run_idempotency')]
