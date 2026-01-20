from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='TrendAnalysisResult',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('analysis_type', models.CharField(db_index=True, max_length=50)),
                ('platform', models.CharField(blank=True, db_index=True, max_length=10, null=True)),
                ('days', models.IntegerField(blank=True, db_index=True, null=True)),
                ('status', models.CharField(db_index=True, default='success', max_length=20)),
                ('error_message', models.TextField(blank=True, null=True)),
                ('parameters', models.JSONField(blank=True, default=dict)),
                ('summary', models.JSONField(blank=True, default=dict)),
                ('result_data', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='trendanalysisresult',
            index=models.Index(fields=['analysis_type', 'platform', 'days'], name='analyzer_tr_analysis_6e76f2_idx'),
        ),
        migrations.AddIndex(
            model_name='trendanalysisresult',
            index=models.Index(fields=['analysis_type', 'created_at'], name='analyzer_tr_analysis_7c4a44_idx'),
        ),
    ]
