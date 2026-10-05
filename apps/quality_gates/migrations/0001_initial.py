import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL), ('contracts', '0001_initial')]
    operations = [migrations.CreateModel(name='GateReport', fields=[
        ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
        ('report', models.JSONField()),
        ('created_at', models.DateTimeField(auto_now_add=True)),
        ('baseline', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='baseline_reports', to='contracts.contractversion')),
        ('candidate', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='candidate_reports', to='contracts.contractversion')),
        ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
        ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='api_testing.apiproject')),
    ], options={'ordering': ['-created_at']})]
