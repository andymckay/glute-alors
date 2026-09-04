from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("alors", "0014_issue_created_at_issue_created_by_issue_updated_at"),
    ]

    operations = [
        migrations.RenameField(
            model_name="workout",
            old_name="type",
            new_name="workout_type",
        ),
    ]
