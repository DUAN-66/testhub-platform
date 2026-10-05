import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from rest_framework.test import APIClient
from apps.api_testing.models import ApiProject
from apps.commerce_demo.models import Product, Inventory, Claim
from apps.users.models import User


@pytest.fixture
def demo(db, settings):
    settings.DEBUG = True
    call_command('seed_performance_demo', password='Demo-only!2026')
    user = User.objects.get(username='testhub_demo')
    client = APIClient()
    client.force_authenticate(user)
    project = ApiProject.objects.get(name='PerformanceGate 演示')
    return client, project, Product.objects.filter(project=project).first()


@pytest.mark.django_db
def test_same_payload_49_to_1_queries_and_private_access(demo, settings):
    client, project, _ = demo
    path = f'/api/demo-commerce/projects/{project.pk}/products/'
    baseline = client.get(path, {'strategy': 'baseline'})
    optimized = client.get(path)
    assert baseline.data == optimized.data and optimized.data['count'] == 24
    assert int(baseline['X-Query-Count']) == 49 and int(optimized['X-Query-Count']) == 1
    assert client.get(path, {'strategy': 'other'}).status_code == 400
    settings.DEBUG = False
    assert client.get(path).status_code == 404
    settings.DEBUG = True
    client.force_authenticate(User.objects.create_user(username='commerce-outsider'))
    assert client.get(path).status_code == 404


@pytest.mark.django_db
def test_inventory_idempotency_conflict_and_no_negative_stock(demo):
    client, project, product = demo
    path = f'/api/demo-commerce/projects/{project.pk}/products/{product.pk}/claim/'
    assert client.post(path).status_code == 400
    first = client.post(path, HTTP_IDEMPOTENCY_KEY='same')
    replay = client.post(path, HTTP_IDEMPOTENCY_KEY='same')
    assert first.status_code == 201 and replay.status_code == 200
    assert first.data['receipt'] == replay.data['receipt']
    another = Product.objects.filter(project=project).exclude(pk=product.pk).first()
    assert client.post(path.replace(f'/{product.pk}/claim', f'/{another.pk}/claim'), HTTP_IDEMPOTENCY_KEY='same').status_code == 409
    for index in range(10):
        client.post(path, HTTP_IDEMPOTENCY_KEY=f'unique-{index}')
    assert Inventory.objects.get(product=product).available == 0
    assert Claim.objects.filter(product=product).count() == 5
    assert client.post(path, HTTP_IDEMPOTENCY_KEY='sold-out').data['code'] == 'SOLD_OUT'


@pytest.mark.django_db
def test_seeder_preserves_accounts_inventory_and_production_boundary(demo, settings):
    _, _, product = demo
    Inventory.objects.filter(product=product).update(available=1)
    call_command('seed_performance_demo', password='Demo-only!2026')
    assert Product.objects.count() == 24 and Inventory.objects.get(product=product).available == 1
    with pytest.raises(CommandError):
        call_command('seed_performance_demo', password='different')
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command('seed_performance_demo', password='Demo-only!2026')
