from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('project', '0006_project_color_sort_order'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='AimDealer',
            new_name='Account',
        ),
        migrations.RenameField(
            model_name='account',
            old_name='account',
            new_name='account_status',
        ),
    ]
