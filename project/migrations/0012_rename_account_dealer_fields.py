from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('project', '0011_accountsyncstate'),
    ]

    operations = [
        migrations.RenameField(
            model_name='account',
            old_name='dealer_id',
            new_name='account_id',
        ),
        migrations.RenameField(
            model_name='account',
            old_name='dealer_name',
            new_name='account_name',
        ),
    ]
