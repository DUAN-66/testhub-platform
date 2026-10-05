import uuid

from django.conf import settings
from django.db import models


class ContractVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey('api_testing.ApiProject', on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    document = models.JSONField()
    digest = models.CharField(max_length=64)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['project', 'digest'], name='contract_project_digest')]
