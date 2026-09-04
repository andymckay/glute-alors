from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("alors", "0005_warmup"),
    ]

    operations = [
        migrations.RenameField(
            model_name="plannedworkout",
            old_name="warm_up",
            new_name="warm_up_text",
        ),
        migrations.AddField(
            model_name="plannedworkout",
            name="warm_up",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="workouts",
                to="alors.warmup",
                verbose_name="warm up",
            ),
        ),
        migrations.RemoveField(
            model_name="plannedworkout",
            name="warm_up_text",
        ),
    ]
