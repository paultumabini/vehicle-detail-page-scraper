from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('project', '0012_rename_account_dealer_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='targetsite',
            name='inactive_due_to_account',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'True when status was auto-set to Inactive because the linked account '
                    'is inactive/deleted; cleared when the account returns to ACTIVE.'
                ),
            ),
        ),
    ]
