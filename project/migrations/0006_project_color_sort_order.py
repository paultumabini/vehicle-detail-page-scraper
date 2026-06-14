from django.db import migrations, models

# Seed sidebar color + order for known projects (see PROJECT_COLOR_CHOICES in models).
PROJECT_DEFAULTS = {
    'aim-dealers': ('brand', 0),
    'vdp-urls': ('sky', 10),
    'others': ('amber', 20),
}


def seed_project_nav_defaults(apps, schema_editor):
    """Apply defaults to existing rows; new projects keep model field defaults."""
    Project = apps.get_model('project', 'Project')
    for name, (color, sort_order) in PROJECT_DEFAULTS.items():
        Project.objects.filter(name=name).update(color=color, sort_order=sort_order)


class Migration(migrations.Migration):
    dependencies = [
        ('project', '0005_remove_aimdealer_aim360_imagepipelineon'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='color',
            field=models.CharField(
                choices=[
                    ('brand', 'Purple'),
                    ('sky', 'Blue'),
                    ('amber', 'Amber'),
                    ('emerald', 'Green'),
                    ('rose', 'Rose'),
                ],
                default='brand',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='project',
            name='sort_order',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.RunPython(seed_project_nav_defaults, migrations.RunPython.noop),
    ]
