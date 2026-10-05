"""DEBUG-only business fixture; baseline deliberately demonstrates an N+1 query."""
import re
import time
import uuid
from django.conf import settings
from django.db import connection, transaction, IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.quality_gates.views import projects
from .models import Product, Inventory, Claim


def project_for(request, project_id):
    return get_object_or_404(projects(request.user), pk=project_id)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def products(request, project_id):
    if not settings.DEBUG:
        return Response(status=404)
    project_for(request, project_id)
    strategy = request.query_params.get('strategy', 'optimized')
    if strategy not in {'baseline', 'optimized'}:
        return Response({'error': 'Unknown strategy'}, status=400)
    stats = {'count': 0, 'seconds': 0}

    def timer(execute, sql, params, many, context):
        started = time.perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            stats['count'] += 1
            stats['seconds'] += time.perf_counter() - started

    with connection.execute_wrapper(timer):
        queryset = Product.objects.filter(project_id=project_id).order_by('id')[:24]
        if strategy == 'optimized':
            queryset = queryset.select_related('category', 'inventory')
        data = [{'id': item.pk, 'name': item.name, 'category': item.category.name,
                 'available': item.inventory.available} for item in queryset]
    response = Response({'count': len(data), 'products': data})
    response['X-Query-Count'] = str(stats['count'])
    response['Server-Timing'] = f"sql;dur={stats['seconds'] * 1000:.3f}"
    return response


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def claim(request, project_id, product_id):
    if not settings.DEBUG:
        return Response(status=404)
    project_for(request, project_id)
    product = get_object_or_404(Product, pk=product_id, project_id=project_id)
    key = request.headers.get('Idempotency-Key', '')
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', key):
        return Response({'code': 'INVALID_KEY'}, status=400)
    with transaction.atomic():
        inventory = Inventory.objects.select_for_update().get(product=product)
        existing = Claim.objects.filter(project_id=project_id, user=request.user, key=key).first()
        if existing:
            if existing.product_id != product_id:
                return Response({'code': 'IDEMPOTENCY_CONFLICT'}, status=409)
            return Response({'receipt': str(existing.receipt), 'replayed': True})
        if not inventory.available:
            return Response({'code': 'SOLD_OUT'}, status=409)
        try:
            with transaction.atomic():
                saved = Claim.objects.create(project_id=project_id, product=product, user=request.user,
                                             key=key, receipt=uuid.uuid4())
                inventory.available -= 1
                inventory.save(update_fields=['available'])
        except IntegrityError:
            # A concurrent claim for a different product reused this project/user key.
            return Response({'code': 'IDEMPOTENCY_CONFLICT'}, status=409)
    return Response({'receipt': str(saved.receipt), 'replayed': False}, status=201)
