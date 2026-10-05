from django.urls import path
from .views import products, claim

urlpatterns = [path('projects/<int:project_id>/products/', products),
               path('projects/<int:project_id>/products/<int:product_id>/claim/', claim)]
