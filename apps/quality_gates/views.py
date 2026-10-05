from django.db import IntegrityError, transaction
import re
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.api_testing.models import ApiProject, TestExecution, TestSuite
from apps.api_testing.services.dispatch import dispatch_test_suite
from apps.contracts.engine import ContractError, digest, normalize
from apps.contracts.models import ContractVersion
from .engine import evaluate, validate_policy
from .models import GateReport, GateRun
from .services import analyze, suite_fingerprints


def projects(user):
    return ApiProject.objects.filter(Q(owner=user) | Q(members=user)).distinct()


class VersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContractVersion
        fields = ['id', 'project', 'name', 'digest', 'created_at']


class ImportSerializer(serializers.Serializer):
    project = serializers.IntegerField(min_value=1)
    name = serializers.CharField(max_length=120)
    document = serializers.JSONField()


class ComparisonSerializer(serializers.Serializer):
    baseline_id = serializers.UUIDField()
    candidate_id = serializers.UUIDField()
    execution_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), default=list, max_length=100)
    policy = serializers.JSONField(default=dict)


class RunEvaluationSerializer(serializers.Serializer):
    run_id = serializers.UUIDField()


class ReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = GateReport
        fields = '__all__'


class ContractViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = VersionSerializer

    def get_queryset(self):
        queryset = ContractVersion.objects.filter(project__in=projects(self.request.user))
        project = self.request.query_params.get('project')
        if project:
            try:
                project = int(project)
            except ValueError as exc:
                raise ValidationError('project must be an integer') from exc
            queryset = queryset.filter(project_id=project)
        return queryset

    def list(self, request):
        return Response(VersionSerializer(self.get_queryset()[:200], many=True).data)

    def retrieve(self, request, pk=None):
        version = self.get_object()
        return Response({**VersionSerializer(version).data, 'document': version.document})

    def create(self, request):
        serializer = ImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        project = get_object_or_404(projects(request.user), pk=data['project'])
        try:
            document, _ = normalize(data['document'])
        except ContractError as exc:
            raise ValidationError({'document': str(exc)}) from exc
        try:
            with transaction.atomic():
                version, created = ContractVersion.objects.get_or_create(project=project, digest=digest(document),
                    defaults={'name': data['name'], 'document': document, 'created_by': request.user})
        except IntegrityError:
            version, created = ContractVersion.objects.get(project=project, digest=digest(document)), False
        return Response(VersionSerializer(version).data, status=201 if created else 200)


class QualityViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = ComparisonSerializer

    def resolve(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        versions = ContractVersion.objects.filter(project__in=projects(request.user))
        baseline = get_object_or_404(versions, pk=data['baseline_id'])
        candidate = get_object_or_404(versions, pk=data['candidate_id'], project_id=baseline.project_id)
        try:
            policy = validate_policy(data['policy'])
        except ValueError as exc:
            raise ValidationError({'policy': str(exc)}) from exc
        diff, impact = analyze(baseline, candidate)
        return data, baseline, candidate, diff, impact, policy

    @action(detail=False, methods=['post'])
    def plan(self, request):
        _, baseline, candidate, diff, impact, _ = self.resolve(request)
        return Response({'baseline_id': baseline.id, 'candidate_id': candidate.id, 'diff': diff, 'impact': impact})

    @action(detail=False, methods=['post'])
    def execute(self, request):
        _, baseline, candidate, diff, impact, policy = self.resolve(request)
        key = request.headers.get('Idempotency-Key', '')
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', key):
            raise ValidationError('A valid Idempotency-Key header is required')
        if len(impact['suite_ids']) > 100:
            raise ValidationError('At most 100 suites may be dispatched per gate run')
        fingerprint = digest({'baseline': str(baseline.id), 'candidate': str(candidate.id), 'policy': policy})
        plan = {'diff': diff, 'impact': impact, 'policy': policy,
                'suite_fingerprints': suite_fingerprints(baseline.project_id, impact['suite_ids'])}
        with transaction.atomic():
            run, created = GateRun.objects.get_or_create(project_id=baseline.project_id, created_by=request.user,
                idempotency_key=key, defaults={'baseline': baseline, 'candidate': candidate, 'plan': plan, 'request_digest': fingerprint})
        if not created:
            if run.request_digest != fingerprint:
                return Response({'code': 'IDEMPOTENCY_CONFLICT'}, status=409)
            return Response(self.run_data(run), status=202)
        suites = TestSuite.objects.filter(project_id=baseline.project_id, pk__in=impact['suite_ids']).order_by('id')
        try:
            for suite in suites:
                run.execution_ids.append(dispatch_test_suite(suite, request.user).id)
                run.save(update_fields=['execution_ids'])
            run.state = 'READY'
        except Exception:
            run.state = 'ERROR'
        run.save(update_fields=['state'])
        return Response(self.run_data(run), status=202)

    @staticmethod
    def run_data(run):
        return {'id': run.id, 'state': run.state, 'execution_ids': run.execution_ids, **run.plan}

    @action(detail=True, methods=['get'], url_path='run')
    def run(self, request, pk=None):
        identifier = RunEvaluationSerializer(data={'run_id': pk})
        identifier.is_valid(raise_exception=True)
        run = get_object_or_404(GateRun.objects.filter(project__in=projects(request.user)), pk=identifier.validated_data['run_id'])
        return Response(self.run_data(run))

    @action(detail=False, methods=['post'])
    def evaluate(self, request):
        serializer = RunEvaluationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run = get_object_or_404(GateRun.objects.filter(project__in=projects(request.user)).select_related('baseline', 'candidate'),
                               pk=serializer.validated_data['run_id'])
        baseline, candidate = run.baseline, run.candidate
        diff, impact, policy = run.plan['diff'], run.plan['impact'], run.plan['policy']
        ids = run.execution_ids
        queryset = TestExecution.objects.filter(pk__in=ids, test_suite__project_id=baseline.project_id)
        if queryset.count() != len(ids):
            raise ValidationError({'execution_ids': 'Missing execution or different project'})
        executions = []
        for execution in queryset:
            executions.append({'suite_id': execution.test_suite_id, 'status': execution.status,
                               'results': execution.results, 'total_requests': execution.total_requests})
        report = evaluate(diff, impact, executions, policy)
        configuration_matches = run.plan['suite_fingerprints'] == suite_fingerprints(run.project_id, impact['suite_ids'])
        report['rules'].append({'name': 'CASE_CONFIGURATION_UNCHANGED', 'passed': configuration_matches,
                                'actual': configuration_matches, 'expected': True})
        report['rules'].append({'name': 'DISPATCH_COMPLETE', 'passed': run.state == 'READY',
                                'actual': run.state, 'expected': 'READY'})
        if not all(rule['passed'] for rule in report['rules']):
            report['decision'] = 'BLOCK'
        report.update({'diff': diff, 'impact': impact, 'execution_ids': ids,
                       'run_id': str(run.id), 'baseline_digest': baseline.digest, 'candidate_digest': candidate.digest})
        saved = GateReport.objects.create(project_id=baseline.project_id, baseline=baseline, candidate=candidate,
                                         report=report, created_by=request.user)
        return Response({'id': saved.id, **report}, status=201)


class ReportViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = ReportSerializer

    def get_queryset(self):
        return GateReport.objects.filter(project__in=projects(self.request.user))

    def list(self, request):
        return Response([{'id': r.id, 'project': r.project_id, 'created_at': r.created_at, **r.report}
                         for r in self.get_queryset()[:100]])

    def retrieve(self, request, pk=None):
        report = self.get_object()
        return Response({'id': report.id, 'project': report.project_id, 'created_at': report.created_at, **report.report})
