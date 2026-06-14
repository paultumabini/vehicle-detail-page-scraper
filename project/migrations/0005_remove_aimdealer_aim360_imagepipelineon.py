from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('project', '0004_aimdealer_new_fields'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='aimdealer',
            name='aim_360',
        ),
        migrations.RemoveField(
            model_name='aimdealer',
            name='image_pipeline_on',
        ),
    ]
