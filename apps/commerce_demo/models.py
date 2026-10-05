from django.conf import settings
from django.db import models


class Category(models.Model):
    project = models.ForeignKey('api_testing.ApiProject', on_delete=models.CASCADE)
    name = models.CharField(max_length=100)


class Product(models.Model):
    project = models.ForeignKey('api_testing.ApiProject', on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)


class Inventory(models.Model):
    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name='inventory')
    available = models.PositiveIntegerField()


class Claim(models.Model):
    project = models.ForeignKey('api_testing.ApiProject', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    key = models.CharField(max_length=128)
    receipt = models.UUIDField(unique=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['project', 'user', 'key'], name='demo_claim_idempotency')]
