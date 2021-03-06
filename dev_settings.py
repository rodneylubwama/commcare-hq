"""
This is a home for shared dev settings.  Feel free to add anything that all
devs should have set.

Add `from dev_settings import *` to the top of your localsettings file to use.
You can then override or append to any of these settings there.
"""
from __future__ import absolute_import
import os

LOCAL_APPS = (
    'django_extensions',
    'kombu.transport.django',
)

# TEST_RUNNER is overridden in testsettings, which is the default settings
# module for the test command (see manage.py); this has no effect by default.
# Use ./manage.py test --settings=settings to use this setting.
TEST_RUNNER = 'testrunner.DevTestRunner'

SKIP_TESTS_REQUIRING_EXTRA_SETUP = True

# touchforms must be running when this is false or not set
# see also corehq.apps.sms.tests.util.TouchformsTestCase
SKIP_TOUCHFORMS_TESTS = True

# https://docs.djangoproject.com/en/1.8/ref/settings/#std:setting-TEST_NON_SERIALIZED_APPS
# https://docs.djangoproject.com/en/1.8/ref/settings/#serialize
TEST_NON_SERIALIZED_APPS = ['corehq.form_processor']

####### Django Extensions #######
# These things will be imported when you run ./manage.py shell_plus
SHELL_PLUS_POST_IMPORTS = (
    # Models
    ('corehq.apps.app_manager.models', 'Application'),
    ('corehq.apps.domain.models', 'Domain'),
    ('corehq.apps.groups.models', 'Group'),
    ('corehq.apps.locations.models', 'Location'),
    ('corehq.apps.users.models', ('CouchUser', 'WebUser', 'CommCareUser')),
    ('casexml.apps.case.models', 'CommCareCase'),
    ('corehq.form_processor.interfaces.dbaccessors', 'CaseAccessors'),
    ('couchforms.models', 'XFormInstance'),

    # Data querying utils
    ('dimagi.utils.couch.database', 'get_db'),
    ('corehq.apps.es', '*'),
)

ALLOWED_HOSTS = ['*']
FIX_LOGGER_ERROR_OBFUSCATION = True

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': 'commcarehq',
        'USER': 'commcarehq',
        'PASSWORD': 'commcarehq',
        'HOST': 'localhost',
        'PORT': '5432'
    }
}

CACHES = {'default': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'}}

# Use faster compressor that doesn't do source maps
COMPRESS_JS_COMPRESSOR = 'compressor.js.JsCompressor'

PILLOWTOP_MACHINE_ID = 'testhq'  # for tests

#  make celery synchronous
CELERY_ALWAYS_EAGER = True
# Fail hard in tasks so you get a traceback
CELERY_EAGER_PROPAGATES_EXCEPTIONS = True

# default inactivity timeout to 1 year
INACTIVITY_TIMEOUT = 60 * 24 * 365

CACHE_REPORTS = False

# Fail hard on csrf failures during dev
CSRF_SOFT_MODE = False

# Make a dir to use for storing attachments as blobs on the filesystem
shared_dirname = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                              'sharedfiles')
if not os.path.exists(shared_dirname):
    os.mkdir(shared_dirname)
SHARED_DRIVE_ROOT = shared_dirname

PHONE_TIMEZONES_SHOULD_BE_PROCESSED = True

# These ES hosts are to be used strictly for DEBUG mode read operations
ELASTICSEARCH_DEBUG_HOSTS = {
    'prod': 'hqes0.internal-va.commcarehq.org',
    'staging': 'hqes0-staging.internal-va.commcarehq.org',
    'india': '10.162.36.221',
}
