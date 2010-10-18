from django.db.models.sql.compiler import SQLCompiler
from django.db.models.sql.constants import MULTI
from django.db import DEFAULT_DB_ALIAS
from django.core.cache import cache
from django.db.models.signals import post_save, post_delete
from django.conf import settings
import logging
import pdb
import sys
from datetime import datetime

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

#TODO: need to support strings in settings and convert them to Model classes
#exclude list (actually a set) so you can specify if queries involving certain tables shouldn't be cached
EXCLUDE_TABLES = settings.QUERY_CACHE_EXCLUDE_TABLES if hasattr(settings, 'QUERY_CACHE_EXCLUDE_TABLES') else set()
logger.debug('EXCLUDE_TABLES: %s' % EXCLUDE_TABLES)

#another exclude list that's only for the main table being queried (e.g. for if you don't want User objects cached, but are fine with caching objects that are queried using User)
EXCLUDE_MODELS = settings.QUERY_CACHE_EXCLUDE_MODELS if hasattr(settings, 'QUERY_CACHE_EXCLUDE_MODELS') else set()
logger.debug('EXCLUDE_MODELS: %s' % EXCLUDE_MODELS)

#size limit in bytes (only results shorter than this will be cached). Defaults to 1 MB for now.
#TODO: need to find a way to implement this (sys.getsizeof isn't working well)
SIZE_LIMIT = settings.QUERY_CACHE_SIZE_LIMIT if hasattr(settings, 'QUERY_CACHE_SIZE_LIMIT') else 1048576
logger.debug('SIZE_LIMIT: %s' % SIZE_LIMIT)

#use a high default value since memcached uses LRU, so least needed items will get thrown out automatically when cache fills up.
TIMEOUT = settings.QUERY_CACHE_TIMEOUT if hasattr(settings, 'QUERY_CACHE_TIMEOUT') else 86400
logger.debug('TIMEOUT: %s' % TIMEOUT)

#use shorter keys for performance. They just have to be unique, probably no one will ever see them.
CACHE_PREFIX = settings.QUERY_CACHE_PREFIX if hasattr(settings, 'QUERY_CACHE_PREFIX') else 'dqc:'
logger.debug('CACHE_PREFIX: %s' % CACHE_PREFIX)

def get_query_key(compiler):
	"Generates keys that will be unique to each query."
	#NOTE: keys must be 250 characters or fewer
	#FIXME: should include database name
	sql, params = compiler.as_nested_sql()
	#whitespace in the query is removed, but whitespace in parameters is percent encoded
	sql = sql.replace(' ','').replace('`','').replace('.','')[6:]
	#logger.debug(sql)
	#logger.debug(params)
	sql = sql % params
	#FIXME: if someone queries using a large amount of data (almost anything other than a number key) this key will definitely be too long
	#TODO: maybe use a hash function?
	#sha-256 should work (no collisions, only 32 bytes long). The binary value should be base64 encoded instead of hex encoded to reduce key size.
	sql = sql.replace('%', '%25').replace(' ', '%20')
	return sql

def get_table_keys(query):
	"Returns a set of cache keys based on table names. These keys are used to store timestamps of when the last time said tables were last updated."
	table_keys = set([])
	
	for table in query.tables:
		#logger.debug(table)
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
	
	#luckily SELECT, INSERT, UPDATE, DELETE are all 6 chars long
	query_type = QUERY_TYPES[self.as_sql()[0][:6]]
	
	logger.debug('Query type: %s' % query_type)
	
	enabled = True
	
	if len(EXCLUDE_MODELS) > 0 and query.model in EXCLUDE_MODELS:
		enabled = False
	
	#if some tables are excluded and some of those are in this query, don't cache
	if enabled and len(EXCLUDE_TABLES) > 0 and len(EXCLUDE_TABLES & set(query.tables)) > 0:
		enabled = False
	
	#SELECT statements
	if query_type == SELECT_QUERY and enabled:
		query_key = get_query_key(self)
		#logger.debug('Key: %s' % query_key)
		
		ret = None
		#get table timeouts and compare to query timeout
		keys_to_get = get_table_keys(self.query)
		keys_to_get.add(query_key)
		#logger.debug('keys_to_get: %s' % str(keys_to_get))
		cached_vals = cache.get_many(keys_to_get)
		
		#check if all keys were returned
		if len(keys_to_get) == len(cached_vals):
			#remove query result from cached_vals, leaving only the table timeouts
			ret = cached_vals.pop(query_key, None)
			#only do this if query result was present
			if ret is not None:
				for k in cached_vals:
					#if the table was updated since the query result was stored, then it's invalid
					if cached_vals[k] > ret[0]:
						ret = None
						break
		#if the query key is present then a timeout is missing
		elif query_key in cached_vals:
			#if any table timeouts are missing, replace them
			keys_to_add = {}
			now = get_current_timestamp()
			for k in keys_to_get:
				if k not in cached_vals:
					keys_to_add[k] = now
			if len(keys_to_add) > 0:
				cache.set_many(keys_to_add, timeout=TIMEOUT)
		
		if ret is None:
			#logger.debug('wasn\'t in cache')
			ret = self._execute_sql(result_type)
			#logger.debug('ret: %s' % ret)
			
			#pdb.set_trace()
			if ret is not None:# and sys.getsizeof(ret) < SIZE_LIMIT:
				now = get_current_timestamp()
				ret = list(ret)
				#logger.debug('Result: %s' % ret)
				#logger.debug('Result class: %s' % ret.__class__)
				
				#update cache with new query result
				cache.set(query_key, (now, ret), timeout=TIMEOUT)
			#else the value is still good but just shouldn't be stored, so we delete the key.
			#this won't always result in a deleted key, since sometimes the key won't be there to begin with,
			#but other times an outdated key could be stored in the cache with no storable value to replace it with, and deleting it here can save some bandwidth and processing when attempting to get the invalid key later on.
			else:
				cache.delete(query_key)
		else:
			#logger.debug('was in cache')
			#if the query result was obtained from the cache, then it's actually a tuple of the form (timeout, query_result)
			ret = ret[1]
		
		return ret
	#INSERT, UPDATE, DELETE statements (and SELECT with caching disabled)
	else:
		#perform operation
		ret = self._execute_sql(result_type)
		#update table timeouts in cache only if rows were affected (don't do this for SELECT statements)
		if query_type != SELECT_QUERY and ret.cursor.rowcount > 0:
			now = get_current_timestamp()
			#update key lists
			#TODO: only do this for tables not in EXCLUDE_TABLES and EXCLUDE_MODELS
			table_key_map = dict((key, now) for key in get_table_keys(self.query))
			cache.set_many(table_key_map, timeout=TIMEOUT)
		
		return ret

if not patched:
	logger.debug('Patching')
	patched = True
	SQLCompiler._execute_sql = SQLCompiler.execute_sql
	SQLCompiler.execute_sql = try_cache

#TODO: add patch and unpatch methods

