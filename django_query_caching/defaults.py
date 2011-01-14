#the query of the 'django_session' table changes on every request, so caching is mostly useless
EXCLUDE_TABLES = set(['django_session'])
EXCLUDE_MODELS = set()
SIZE_LIMIT = 1048576
TIMEOUT = 86400
CACHE_PREFIX = 'dqc:'
