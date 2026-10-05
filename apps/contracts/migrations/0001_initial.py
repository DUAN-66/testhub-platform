import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL), ('api_testing', '0004_alter_testexecution_updated_at')]
    operations = [
        migrations.CreateModel(name='ContractVersion', fields=[
            ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ('name', models.CharField(max_length=120)),
            ('document', models.JSONField()),
            ('digest', models.CharField(max_length=64)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='api_testing.apiproject')),
        ], options={'ordering': ['-created_at']}),
        migrations.AddConstraint(model_name='contractversion', constraint=models.UniqueConstraint(fields=('project', 'digest'), name='contract_project_digest')),
    ]
