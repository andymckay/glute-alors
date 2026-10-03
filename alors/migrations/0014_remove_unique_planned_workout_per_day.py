from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("alors", "0013_userprofile_send_daily_email"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="plannedworkout",
            name="unique_planned_workout_per_day",
        ),
    ]
