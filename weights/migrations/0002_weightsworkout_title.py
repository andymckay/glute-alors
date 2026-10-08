from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("weights", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="weightsworkout",
            name="title",
            field=models.CharField(
                default="",
                help_text="A short name for the workout.",
                max_length=200,
                verbose_name="title",
            ),
            preserve_default=False,
        ),
    ]
