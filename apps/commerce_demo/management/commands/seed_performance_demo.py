import copy
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from apps.users.models import User
from apps.api_testing.models import ApiProject, ApiCollection, ApiRequest, Environment, TestSuite, TestSuiteRequest
from apps.contracts.models import ContractVersion
from apps.contracts.engine import digest
from apps.commerce_demo.models import Category, Product, Inventory


class Command(BaseCommand):
    help = 'Seed a DEBUG-only N+1/stock fixture without resetting existing inventory or passwords.'

    def add_arguments(self, parser):
        parser.add_argument('--password', required=True)
        parser.add_argument('--base-url', default='http://127.0.0.1:8000')

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Demo requires DEBUG=True')
        user, created = User.objects.get_or_create(username='testhub_demo')
        if created:
            user.set_password(options['password'])
            user.save()
        elif not user.check_password(options['password']):
            raise CommandError('Existing password is preserved')
        project, _ = ApiProject.objects.get_or_create(name='PerformanceGate 演示', owner=user)
        category, _ = Category.objects.get_or_create(project=project, name='演示商品')
        for index in range(24):
            product, _ = Product.objects.get_or_create(project=project, category=category, name=f'商品{index + 1:02d}')
            Inventory.objects.get_or_create(product=product, defaults={'available': 5})
        collection, _ = ApiCollection.objects.get_or_create(project=project, name='服务端性能验证')
        environment, _ = Environment.objects.get_or_create(project=project, name='性能演示环境',
            defaults={'scope': 'LOCAL', 'created_by': user,
                      'variables': {'base_url': options['base_url'], 'access_token': {'value': '', 'secret': True}}})
        environment.variables = {**environment.variables, 'base_url': options['base_url']}
        environment.save(update_fields=['variables'])
        path = f'/api/demo-commerce/projects/{project.pk}/products/'
        for strategy in ['baseline', 'optimized']:
            target, _ = ApiRequest.objects.update_or_create(collection=collection, name=strategy,
                defaults={'created_by': user, 'url': '{{base_url}}' + path,
                          'params': {'strategy': strategy}, 'headers': {'Authorization': 'Bearer {{access_token}}'},
                          'assertions': [{'type': 'status_code', 'expected': 200},
                                         {'type': 'json_path', 'expression': '$.count', 'expected': 24}]})
            if strategy == 'optimized':
                suite, _ = TestSuite.objects.get_or_create(project=project, name='商品查询回归',
                                                          defaults={'created_by': user, 'environment': environment})
                TestSuiteRequest.objects.get_or_create(test_suite=suite, request=target)
        document = {'openapi': '3.0.3', 'info': {'title': 'Commerce fixture', 'version': '1'},
                    'paths': {path: {'get': {'responses': {'200': {'description': 'Products',
                        'content': {'application/json': {'schema': {'type': 'object', 'properties': {
                            'count': {'type': 'integer'}, 'products': {'type': 'array', 'items': {'type': 'object'}}}}}}}}}}}}
        for name in ['baseline', 'compatible']:
            version = copy.deepcopy(document)
            if name == 'compatible':
                version['paths'][path]['get']['responses']['200']['content']['application/json']['schema']['properties']['trace_id'] = {'type': 'string'}
            ContractVersion.objects.get_or_create(project=project, digest=digest(version),
                defaults={'name': name, 'document': version, 'created_by': user})
        self.stdout.write(f'Performance demo ready: project={project.pk}; products=24; inventory preserved')
