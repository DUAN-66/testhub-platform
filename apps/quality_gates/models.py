import uuid

from django.conf import settings
from django.db import models


class GateReport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey('api_testing.ApiProject', on_delete=models.CASCADE)
    baseline = models.ForeignKey('contracts.ContractVersion', on_delete=models.CASCADE, related_name='baseline_reports')
    candidate = models.ForeignKey('contracts.ContractVersion', on_delete=models.CASCADE, related_name='candidate_reports')
    report = models.JSONField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class GateRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey('api_testing.ApiProject', on_delete=models.CASCADE)
    baseline = models.ForeignKey('contracts.ContractVersion', on_delete=models.CASCADE, related_name='baseline_runs')
    candidate = models.ForeignKey('contracts.ContractVersion', on_delete=models.CASCADE, related_name='candidate_runs')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    idempotency_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)
    plan = models.JSONField()
    execution_ids = models.JSONField(default=list)
    state = models.CharField(max_length=20, default='DISPATCHING')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['project', 'created_by', 'idempotency_key'], name='gate_run_idempotency')]
