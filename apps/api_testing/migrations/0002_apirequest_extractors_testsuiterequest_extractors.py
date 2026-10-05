from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api_testing', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='apirequest',
            name='extractors',
            field=models.JSONField(blank=True, default=list, verbose_name='响应提取规则'),
        ),
        migrations.AddField(
            model_name='testsuiterequest',
            name='extractors',
            field=models.JSONField(blank=True, default=list, verbose_name='响应提取规则'),
        ),
    ]
