from django.db.models.sql.compiler import SQLCompiler
from django.db.models.sql.constants import MULTI
from django.db import DEFAULT_DB_ALIAS
from django.core.cache import cache
from django.db.models.signals import post_save, post_delete
from django.conf import settings
import defaults
import logging
import pdb
import sys
from datetime import datetime
import hashlib
import base64
import re

logger = logging.getLogger(__name__)

patched = False

SELECT_QUERY = 0
INSERT_QUERY = 1
UPDATE_QUERY = 2
DELETE_QUERY = 3

QUERY_TYPES = {
	'SELECT': SELECT_QUERY,
	'INSERT': INSERT_QUERY,
	'UPDATE': UPDATE_QUERY,
	'DELETE': DELETE_QUERY,
}

#TODO: how to handle transactions?

#TODO: need to support strings in settings and convert them to Model classes
#exclude list (actually a set) so you can specify if queries involving certain tables shouldn't be cached
EXCLUDE_TABLES = settings.QUERY_CACHE_EXCLUDE_TABLES if hasattr(settings, 'QUERY_CACHE_EXCLUDE_TABLES') else defaults.EXCLUDE_TABLES
EXCLUDE_TABLES = frozenset(EXCLUDE_TABLES)
logger.debug('EXCLUDE_TABLES: %s' % EXCLUDE_TABLES)

#another exclude list that's only for the main table being queried (e.g. for if you don't want User objects cached, but are fine with caching objects that are queried using User)
EXCLUDE_MODELS = settings.QUERY_CACHE_EXCLUDE_MODELS if hasattr(settings, 'QUERY_CACHE_EXCLUDE_MODELS') else defaults.EXCLUDE_MODELS
EXCLUDE_MODELS = frozenset(EXCLUDE_MODELS)
logger.debug('EXCLUDE_MODELS: %s' % EXCLUDE_MODELS)

#size limit in bytes (only results shorter than this will be cached). Defaults to 1 MB for now.
#TODO: need to find a way to implement this (sys.getsizeof isn't working well)
SIZE_LIMIT = settings.QUERY_CACHE_SIZE_LIMIT if hasattr(settings, 'QUERY_CACHE_SIZE_LIMIT') else defaults.SIZE_LIMIT
logger.debug('SIZE_LIMIT: %s' % SIZE_LIMIT)

#use a high default value since memcached uses LRU, so least needed items will get thrown out automatically when cache fills up.
TIMEOUT = settings.QUERY_CACHE_TIMEOUT if hasattr(settings, 'QUERY_CACHE_TIMEOUT') else defaults.TIMEOUT
logger.debug('TIMEOUT: %s' % TIMEOUT)

#use shorter keys for performance. They just have to be unique, probably no one will ever see them.
CACHE_PREFIX = settings.QUERY_CACHE_PREFIX if hasattr(settings, 'QUERY_CACHE_PREFIX') else defaults.CACHE_PREFIX
logger.debug('CACHE_PREFIX: %s' % CACHE_PREFIX)

def get_query_key(compiler):
	"Generates keys that will be unique to each query."
	#NOTE: keys must be 250 characters or fewer
	sql, params = compiler.as_nested_sql()
	#profiling shows that using string.replace and regex to shorten sql (removing [ `.]) adds more
	#time than is saved during sha256-ing. [6:] has some slight benefit though.
	key = '%s:%s' % (compiler.using, sql[6:])
	#logger.debug(key)
	#logger.debug(params)
	key = key % params
	#sha-256 should work (no collisions, only 32 bytes long). The binary value should be base64 encoded instead of hex encoded to reduce key size.
	#TODO: check if these are implemented with C extensions
	return base64.b64encode(hashlib.sha256(key).digest())

def get_table_keys(query):
	"Returns a set of cache keys based on table names. These keys are used to store timestamps of when the last time said tables were last updated."
	logger.debug('get_table_keys()')
	table_keys = set([])
	tables = query.tables
	#OPTIMIZE: if not tables:
	if len(tables) == 0:
		tables = [query.model._meta.db_table]
	#will converting to frozensets be faster?
	#test if map is faster. if not, list comprehensions are
	for table in tables:
		logger.debug('table: %s' % table)
		table_keys.add('%s%s' % (CACHE_PREFIX, table))
	return table_keys

def get_current_timestamp():
	#TODO: make timezone aware
	#this has microsecond precision, which is good
	return datetime.now()

#FIXME: before doing INSERT, UPDATE, or DELETE, Django first does a SELECT to see if the rows exists, which means the cache will needlessly be updated right before the updated parts are invalidated. Any way around this? Maybe these SELECT queries have some sort of flag we can use to ignore them.
def try_cache(self, result_type=MULTI):
	"This function overwrites the default behavior of SQLCompiler.execute_sql(), attempting to retreive data from the cache first before trying the database."
	#logger.debug('try_cache()')
	#logger.debug(self)
	#logger.debug('Result type: %s' % result_type)
	logger.debug(self.as_sql())
	#pdb.set_trace()
	
	#luckily SELECT, INSERT, UPDATE, DELETE are all 6 chars long
	query_type = QUERY_TYPES[self.as_sql()[0][:6]]
	
	logger.debug('Query type: %s' % query_type)
	
	enabled = True
	
	if len(EXCLUDE_MODELS) > 0 and query.model in EXCLUDE_MODELS:
		enabled = False
	
	#if some tables are excluded and some of those are in this query, don't cache
	if enabled and len(EXCLUDE_TABLES) > 0 and len(EXCLUDE_TABLES & set(self.query.tables)) > 0:
		enabled = False
	
	#SELECT statements
	if query_type == SELECT_QUERY and enabled:
		query_key = get_query_key(self)
		logger.debug('Key: %s' % query_key)
		
		#get table timestamps and compare to query timestamp
		keys_to_get = get_table_keys(self.query)
		keys_to_get.add(query_key)
		#logger.debug('keys_to_get: %s' % str(keys_to_get))
		cached_vals = cache.get_many(keys_to_get)
		#remove query result from cached_vals, leaving only the table timestamps
		ret = cached_vals.pop(query_key, None)
		if ret is not None:
			logger.debug('wasn\'t in cache')
		else:
			logger.debug('was in cache')
		
		#check if all keys were returned
		if len(keys_to_get)-1 == len(cached_vals):
			#only do this if query result was present
			if ret is not None:
				logger.debug('query timeout: %s' % ret[0])
				for k in cached_vals:
					#if the table was updated since the query result was stored, then it's invalid
					logger.debug('timeout: %s = %s' % (k, cached_vals[k]))
					if cached_vals[k] > ret[0]:
						ret = None
						logger.debug('key is outdated')
						break
		else:
			#if any table timestamps are missing, replace them
			logger.debug('timestamps missing')
			keys_to_add = {}
			now = get_current_timestamp()
			for k in keys_to_get:
				if k not in cached_vals:
					keys_to_add[k] = now
			cache.set_many(keys_to_add, timeout=TIMEOUT)
			#we can't guarantee the result is current
			ret = None
		
		if ret is None:
			logger.debug('no valid ret value in cache')
			ret = self._execute_sql(result_type)
			#logger.debug('ret: %s' % ret)
			
			#pdb.set_trace()
			#if ret isn't None store the value
			if ret is not None:# and sys.getsizeof(ret) < SIZE_LIMIT:
				now = get_current_timestamp()
				ret = list(ret)
				logger.debug('Result: %s' % ret)
				#logger.debug('Result class: %s' % ret.__class__)
				
				#update cache with new query result
				cache.set(query_key, (now, ret), timeout=TIMEOUT)
			#else the value is still valid but just shouldn't be stored, so we delete
			#the key (None shouldn't be stored, but can be returned by execute_sql).
			#this won't always result in a deleted key, since sometimes the key
			#won't be there to begin with, but other times an outdated key could
			#be stored in the cache with no storable value to replace it with, and
			#deleting it here can save some bandwidth and processing when attempting
			#to get the invalid key later on.
			else:
				cache.delete(query_key)
		else:
			logger.debug('valid ret value was in cache')
			#if the query result was obtained from the cache, then it's actually a tuple of the form (timestamp, query_result)
			ret = ret[1]
		
		return ret
	#INSERT, UPDATE, DELETE statements (and SELECT with caching disabled)
	else:
		#perform operation
		ret = self._execute_sql(result_type)
		#update table timestamps in cache only if rows were affected (don't do this for SELECT statements)
		if query_type != SELECT_QUERY and ret.cursor.rowcount > 0:
			now = get_current_timestamp()
			#update key lists
			#TODO: only do this for tables not in EXCLUDE_TABLES and EXCLUDE_MODELS
			table_key_map = dict((key, now) for key in get_table_keys(self.query))
			logger.debug(table_key_map)
			cache.set_many(table_key_map, timeout=TIMEOUT)
			#pdb.set_trace()
		
		return ret

if not patched:
	logger.debug('Patching')
	patched = True
	SQLCompiler._execute_sql = SQLCompiler.execute_sql
	SQLCompiler.execute_sql = try_cache
	#TODO: set timeout keys for all models on initialization. This will make sure cache is invalidated when reloading web server (so sys admins won't have to invalidate all of memcached when upgrading live code)

#TODO: add patch and unpatch methods

