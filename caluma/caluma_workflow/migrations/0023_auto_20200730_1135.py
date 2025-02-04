# Generated by Django 2.2.14 on 2020-07-30 11:35

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("caluma_workflow", "0022_workitem_name_description")]

    operations = [
        migrations.AddField(
            model_name="historicalworkitem",
            name="previous_work_item",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="caluma_workflow.WorkItem",
            ),
        ),
        migrations.AddField(
            model_name="workitem",
            name="previous_work_item",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="succeeding_work_items",
                to="caluma_workflow.WorkItem",
            ),
        ),
    ]
