import re
import uuid
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.api_testing.models import ApiRequest, Environment
from apps.contracts.engine import digest
from apps.quality_gates.models import GateRun
from apps.quality_gates.views import projects
from .engine import validate_workload
from .models import PerformanceRun
from .services import fingerprint, validate_access
from .tasks import execute_performance


class CreateSerializer(serializers.Serializer):
    request_id = serializers.IntegerField(min_value=1)
    environment_id = serializers.IntegerField(min_value=1, allow_null=True, default=None)
    gate_id = serializers.UUIDField(allow_null=True, default=None)
    workload = serializers.JSONField(default=dict)


def run_data(run):
    return {'id': str(run.id), 'project': run.project_id, 'request_id': run.request_id,
            'environment_id': run.environment_id, 'gate_id': str(run.gate_id) if run.gate_id else None,
            'status': run.status, 'summary': run.summary, 'error_code': run.error_code,
            'workload': run.workload, 'created_at': run.created_at, 'finished_at': run.finished_at}


class PerformanceViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = CreateSerializer

    def get_queryset(self):
        return PerformanceRun.objects.filter(project__in=projects(self.request.user), created_by=self.request.user)

    def list(self, request):
        return Response([run_data(run) for run in self.get_queryset().order_by('-created_at')[:100]])

    def retrieve(self, request, pk=None):
        return Response(run_data(self.get_object()))

    def create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        key = request.headers.get('Idempotency-Key', '')
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', key):
            raise ValidationError('A valid Idempotency-Key is required')
        target = get_object_or_404(ApiRequest.objects.select_related('collection__project'),
                                 pk=data['request_id'], collection__project__in=projects(request.user))
        environment = get_object_or_404(Environment, pk=data['environment_id']) if data['environment_id'] else None
        gate = get_object_or_404(GateRun, pk=data['gate_id'], created_by=request.user) if data['gate_id'] else None
        project = validate_access(target, environment, request.user, gate)
        try:
            workload = validate_workload(data['workload'])
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        configuration = fingerprint(target, environment)
        request_digest = digest({'request': target.pk, 'environment': data['environment_id'],
                                 'gate': str(gate.pk) if gate else None, 'workload': workload,
                                 'configuration': configuration})
        try:
            with transaction.atomic():
                # Serialize per-owner dispatches; one outstanding run per user bounds aggregate load.
                type(request.user).objects.select_for_update().get(pk=request.user.pk)
                existing = self.get_queryset().filter(project=project, idempotency_key=key).first()
                if existing:
                    if existing.digest != request_digest:
                        return Response({'code': 'IDEMPOTENCY_CONFLICT'}, status=409)
                    return Response(run_data(existing), status=202)
                if self.get_queryset().filter(status__in=['QUEUED', 'RUNNING']).exists():
                    return Response({'code': 'PERFORMANCE_RUN_ACTIVE'}, status=409)
                run = PerformanceRun.objects.create(project=project, request=target, environment=environment,
                    gate=gate, created_by=request.user, idempotency_key=key, digest=request_digest,
                    configuration_digest=configuration, workload=workload, task_id=str(uuid.uuid4()))
        except IntegrityError:
            return Response({'code': 'GATE_ALREADY_BOUND'}, status=409)
        try:
            execute_performance.apply_async(args=[str(run.pk)], task_id=run.task_id)
        except Exception:
            PerformanceRun.objects.filter(pk=run.pk, status='QUEUED').update(status='FAILED', error_code='DISPATCH_FAILED')
        run.refresh_from_db()
        return Response(run_data(run), status=202)
