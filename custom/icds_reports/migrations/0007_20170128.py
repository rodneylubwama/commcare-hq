# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from corehq.sql_db.operations import RawSQLMigration

migrator = RawSQLMigration(('custom', 'icds_reports', 'migrations', 'sql_templates'))


class Migration(migrations.Migration):

    dependencies = [
        ('icds_reports', '0006_fix_functions'),
    ]

    operations = [
        migrator.get_migration('create_functions.sql'),
        migrator.get_migration('setup_category_tables.sql'),
    ]
