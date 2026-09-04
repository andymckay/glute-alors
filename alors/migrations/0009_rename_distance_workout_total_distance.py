from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("alors", "0008_workout"),
    ]

    operations = [
        migrations.RenameField(
            model_name="workout",
            old_name="distance",
            new_name="total_distance",
        ),
    ]
