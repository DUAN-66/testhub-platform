from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('api_testing', '0002_apirequest_extractors_testsuiterequest_extractors'),
    ]

    operations = [
        migrations.AlterField(
            model_name='testexecution',
            name='status',
            field=models.CharField(
                choices=[
                    ('PENDING', '待执行'),
                    ('QUEUED', '已入队'),
                    ('RUNNING', '执行中'),
                    ('COMPLETED', '已完成'),
                    ('FAILED', '执行失败'),
                    ('CANCELLED', '已取消'),
                ],
                default='PENDING',
                max_length=20,
                verbose_name='执行状态',
            ),
        ),
        migrations.AddField(
            model_name='testexecution',
            name='celery_task_id',
            field=models.CharField(blank=True, db_index=True, max_length=255, verbose_name='Celery任务ID'),
        ),
        migrations.AddField(
            model_name='testexecution',
            name='progress',
            field=models.PositiveSmallIntegerField(default=0, verbose_name='执行进度'),
        ),
        migrations.AddField(
            model_name='testexecution',
            name='current_request',
            field=models.PositiveIntegerField(default=0, verbose_name='当前请求序号'),
        ),
        migrations.AddField(
            model_name='testexecution',
            name='error_message',
            field=models.TextField(blank=True, verbose_name='执行错误'),
        ),
        migrations.AddField(
            model_name='testexecution',
            name='state_version',
            field=models.PositiveIntegerField(default=0, verbose_name='状态版本'),
        ),
        migrations.AddField(
            model_name='testexecution',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.CreateModel(
            name='TestExecutionLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sequence', models.PositiveIntegerField(verbose_name='事件序号')),
                ('level', models.CharField(choices=[('DEBUG', '调试'), ('INFO', '信息'), ('WARNING', '警告'), ('ERROR', '错误')], default='INFO', max_length=10, verbose_name='日志级别')),
                ('event', models.CharField(max_length=50, verbose_name='事件类型')),
                ('message', models.CharField(max_length=500, verbose_name='日志消息')),
                ('data', models.JSONField(blank=True, default=dict, verbose_name='结构化数据')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('execution', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='logs', to='api_testing.testexecution', verbose_name='测试执行')),
            ],
            options={
                'verbose_name': '接口测试执行日志',
                'verbose_name_plural': '接口测试执行日志',
                'db_table': 'api_test_execution_logs',
                'ordering': ['sequence'],
            },
        ),
        migrations.AddConstraint(
            model_name='testexecutionlog',
            constraint=models.UniqueConstraint(fields=('execution', 'sequence'), name='uniq_api_execution_log_sequence'),
        ),
    ]
