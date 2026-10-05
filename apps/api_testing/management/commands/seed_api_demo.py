from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.api_testing.models import ApiProject, ApiCollection, ApiRequest, Environment, TestSuite, TestSuiteRequest
from apps.users.models import User


class Command(BaseCommand):
    help = 'Create isolated API demonstration data; existing account passwords are preserved.'

    def add_arguments(self, parser):
        parser.add_argument('--username', default='testhub_demo')
        parser.add_argument('--password', required=True)
        parser.add_argument('--base-url', default='http://127.0.0.1:8089')

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Demo seeding is available only with DEBUG=True')
        user, created = User.objects.get_or_create(username=options['username'])
        if created:
            user.set_password(options['password'])
            user.save()
        elif not user.check_password(options['password']):
            raise CommandError('Existing account password differs; choose a new demo username')
        project, _ = ApiProject.objects.get_or_create(name='TestHub 二开演示', owner=user)
        collection, _ = ApiCollection.objects.get_or_create(name='关联接口', project=project)
        environment, _ = Environment.objects.update_or_create(
            name='本地演示环境', project=project,
            defaults={'scope': 'LOCAL', 'variables': {'base_url': options['base_url']}, 'created_by': user},
        )
        definitions = [
            ('登录并提取 Token', 'POST', '/login', {},
             [{'type': 'status_code', 'expected': 200}],
             [{'name': 'access_token', 'source': 'json_path', 'expression': '$.token', 'required': True, 'secret': True}]),
            ('查询个人资料', 'GET', '/profile', {'Authorization': 'Bearer {{access_token}}'},
             [{'type': 'json_path', 'expression': '$.user.id', 'expected': 7}], []),
            ('预期不匹配', 'GET', '/profile', {'Authorization': 'Bearer {{access_token}}'},
             [{'type': 'json_path', 'expression': '$.user.id', 'expected': 999}], []),
            ('慢请求用于取消', 'GET', '/slow', {}, [{'type': 'status_code', 'expected': 200}], []),
        ]
        requests = []
        for name, method, path, headers, assertions, extractors in definitions:
            request, _ = ApiRequest.objects.update_or_create(
                name=name, collection=collection,
                defaults={'method': method, 'url': '{{base_url}}' + path, 'headers': headers,
                          'assertions': assertions, 'extractors': extractors, 'created_by': user},
            )
            requests.append(request)
        for name, indices in [('01 登录关联成功', [0, 1]), ('02 断言失败', [0, 2]), ('03 运行中取消', [3, 1])]:
            suite, _ = TestSuite.objects.update_or_create(
                name=name, project=project,
                defaults={'environment': environment, 'created_by': user},
            )
            for order, index in enumerate(indices):
                TestSuiteRequest.objects.update_or_create(test_suite=suite, request=requests[index], defaults={'order': order})
        self.stdout.write(self.style.SUCCESS(f'Demo ready: user={user.username}, project={project.id}'))
