"""Rename the WarmUp model to SavedWorkout."""

from django.db import migrations


class Migration(migrations.Migration):
    """The warm-up concept became a general reusable workout, so the model and
    its table are renamed. ``RenameModel`` renames ``alors_warmup`` in place, so
    existing rows are preserved (no data is dropped)."""

    dependencies = [
        ("alors", "0009_remove_plannedworkout_warm_up"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="WarmUp",
            new_name="SavedWorkout",
        ),
    ]
