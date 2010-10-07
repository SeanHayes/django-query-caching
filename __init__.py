from django.db.models.sql.compiler import SQLCompiler
from django.db.models.sql.constants import MULTI
from django.db import DEFAULT_DB_ALIAS
from django.core.cache import cache
from django.db.models.signals import post_save, post_delete
from django.conf import settings
import logging

#TODO: add exclude list so you can specify if queries involving certain tables shouldn't be cached
#TODO: add another exclude list that's only for the main table being queried (e.g. for if you don't want User objects cached, but are fine with caching objects that are queried using User)
#TODO: add size limit (only results shorter than this will be cached)

#FIXME: need to ensure list of table keys don't expire before the keys themselves, or handle this occurance. Can either touch table keys frequently, or invalidate whole cache if they're missing (which would require frequent checking).

#use a high default value since memcached uses LRU, so least needed items will get thrown out automatically when cache fills up.
TIMEOUT = settings.QUERY_CACHE_TIMEOUT if hasattr(settings, 'QUERY_CACHE_TIMEOUT') else 86400
logging.debug('TIMEOUT: %s' % TIMEOUT)

#use shorter keys for performance. They just have to be unique, probably no one will ever see them.
CACHE_PREFIX = settings.QUERY_CACHE_PREFIX if hasattr(settings, 'QUERY_CACHE_PREFIX') else 'dqc:'
logging.debug('CACHE_PREFIX: %s' % CACHE_PREFIX)

def get_query_key(compiler):
	"Generates keys that will be unique to each query."
	#NOTE: keys must be 250 characters or fewer
	#FIXME: should include database name
	sql, params = compiler.as_nested_sql()
	#whitespace in the query is removed, but whitespace in parameters is percent encoded
	sql = sql.replace(' ','').replace('`','').replace('.','')[6:]
	logging.debug(sql)
	logging.debug(params)
	sql = sql % params
	#FIXME: if someone queries using a large amount of data (almost anything other than a number key) this key will definitely be too long
	#TODO: maybe use a hash function?
	#sha-256 should work (no collisions, only 32 bytes long). The binary value should be base64 encoded instead of hex encoded to reduce key size.
	sql = sql.replace('%', '%25').replace(' ', '%20')
	return sql

def get_table_keys(query):
	"Returns a set of cache keys based on table names. These keys are used to store sets of keys for cached queries that depend on said tables."
	table_keys = set([])
	
	for table in query.tables:
		#logging.debug(table)
		table_keys.add('%s%s' % (CACHE_PREFIX, table))
	return table_keys

def invalidate(query):
	"Invalidates the cache keys relevant to the supplied query."
	table_keys = get_table_keys(query)
	
	table_key_map = cache.get_many(table_keys)
	
	keys_to_delete = set(table_keys)
	for table in table_key_map:
		keys_to_delete |= table_key_map[table]
	
	logging.debug('Invalidating the following keys: %s' % str(keys_to_delete))
	
	success = cache.delete_many(keys_to_delete)

#overwrite SQLCompiler.execute_sql
def try_cache(self, result_type=MULTI):
	"This function overwrites the default behavior of SQLCompiler.execute_sql(), attempting to retreive data from the cache first before trying the database."
	#logging.debug('try_cache()')
	#logging.debug(self)
	#logging.debug('Result type: %s' % result_type)
	
	#luckily SELECT, INSERT, UPDATE, DELETE are all 6 chars long
	query_type = self.as_sql()[0][:6]
	logging.debug('Query type: %s' % query_type)
	
	#SELECT statements
	if query_type == 'SELECT':
		key = get_query_key(self)
		logging.debug('Key: %s' % key)
		
		ret = cache.get(key)
		if ret is None:
			logging.debug('wasn\'t in cache')
			ret = self._execute_sql(result_type)
			logging.debug('ret: %s' % ret)
			if ret is not None:
				ret = list(ret)
				#logging.debug('Result: %s' % ret)
				#logging.debug('Result class: %s' % ret.__class__)
				
				#update key lists
				table_keys = get_table_keys(self.query)
				
				table_key_map = cache.get_many(table_keys)
				for table in table_keys:
					if table in table_key_map:
						table_key_map[table].add(key)
					else:
						table_key_map[table] = set([key])
				
				#update cache with new query result and table_key_map in a single atomic operation (where supported)
				table_key_map[key] = ret
				cache.set_many(table_key_map, timeout=TIMEOUT)
		else:
			logging.debug('was in cache')
		
		return ret
	#INSERT, UPDATE, DELETE statements
	else:
		#perform operation
		ret = self._execute_sql(result_type)
		#TODO: invalidate cache only if rows were affected
		
		invalidate(self.query)
		
		return ret

SQLCompiler._execute_sql = SQLCompiler.execute_sql
SQLCompiler.execute_sql = try_cache

#TODO: add patch and unpatch methods

