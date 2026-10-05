import json
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from apps.api_testing.models import ApiProject, ApiCollection, ApiRequest, Environment, TestSuite, TestSuiteRequest
from apps.contracts.engine import digest, normalize
from apps.contracts.models import ContractVersion
from apps.users.models import User


class Command(BaseCommand):
    help = 'Seed an isolated, reproducible contract gate demo (DEBUG only).'

    def add_arguments(self, parser):
        parser.add_argument('--username', default='testhub_demo')
        parser.add_argument('--password', required=True)
        parser.add_argument('--base-url', default='http://127.0.0.1:8089')

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Demo seeding requires DEBUG=True')
        user, created = User.objects.get_or_create(username=options['username'])
        if created:
            user.set_password(options['password'])
            user.save()
        elif not user.check_password(options['password']):
            raise CommandError('Choose a new demo username; existing password is preserved')
        project, _ = ApiProject.objects.get_or_create(name='QualityGate 演示', owner=user)
        collection, _ = ApiCollection.objects.get_or_create(name='契约回归', project=project)
        env, _ = Environment.objects.update_or_create(name='质量门禁环境', project=project,
            defaults={'scope': 'LOCAL', 'variables': {'base_url': options['base_url']}, 'created_by': user})
        definitions = [
            ('登录前置', 'POST', '/login', {}, [], [
                {'name': 'access_token', 'source': 'json_path', 'expression': '$.token', 'required': True, 'secret': True}]),
            ('个人资料', 'GET', '/profile', {'Authorization': 'Bearer {{access_token}}'}, [
                {'type': 'json_path', 'expression': '$.user.id', 'expected': 7}], []),
            ('健康检查', 'GET', '/health', {}, [], []),
        ]
        requests = []
        for name, method, path, headers, assertions, extractors in definitions:
            request, _ = ApiRequest.objects.update_or_create(name=name, collection=collection,
                defaults={'method': method, 'url': '{{base_url}}' + path, 'headers': headers,
                    'assertions': [{'type': 'status_code', 'expected': 200}, *assertions],
                    'extractors': extractors, 'created_by': user})
            requests.append(request)
        for name, indices in [('关键登录链路', [0, 1]), ('独立健康检查', [2])]:
            suite, _ = TestSuite.objects.update_or_create(name=name, project=project,
                defaults={'environment': env, 'created_by': user})
            for order, index in enumerate(indices):
                TestSuiteRequest.objects.update_or_create(test_suite=suite, request=requests[index], defaults={'order': order})
        for name in ['baseline', 'compatible', 'breaking']:
            document = json.loads((settings.BASE_DIR / 'fixtures/contracts' / f'{name}.json').read_text(encoding='utf-8'))
            normalize(document)
            ContractVersion.objects.get_or_create(project=project, digest=digest(document),
                defaults={'name': name, 'document': document, 'created_by': user})
        self.stdout.write(f'Quality demo ready: project={project.id}; suites=2; versions=3')
