from django.db.models.sql.compiler import SQLCompiler
from django.db.models.sql.constants import MULTI
from django.db import DEFAULT_DB_ALIAS
from django.core.cache import cache
import cPickle as pickle
from django.db.models.signals import post_save, post_delete
import logging

TIMEOUT = 60

#TODO: make sure only SELECT statements are cached, and others are left alone

#FIXME: this will have to be stored in the cache in order to ensure all running instances of a Django project know when keys need to be invalidated
#FIXME: How large can this get without hurting performance?
#a dict with model names for keys and sets of cache keys using those models for values
#note, this isn't meant to be a current list of active keys, some will inevitably expire wihtout being removed from this list
_table_key_map = {}

def get_key(query):
	#generate keys that will be unique to each query
	#NOTE: keys must be 250 characters or fewer
	sql, params = query.get_compiler(using=DEFAULT_DB_ALIAS).as_nested_sql()
	sql = sql.replace(' ','').replace('`','').replace('.','')
	sql = sql % params
	sql = sql.replace('%', '%25').replace(' ', '%20')
	return sql

def try_cache(self, result_type=None):
	#logging.debug('try_cache()')
	#logging.debug(self)
	#logging.debug('Result type: %s' % result_type)
	
	key = get_key(self.query)
	logging.debug('Key: %s' % key)
	
	ret = cache.get(key)
	if ret is None:
		logging.debug('wasn\'t in cache')
		if result_type is None:
			ret = self._execute_sql()
		else:
			ret = self._execute_sql(result_type)
		
		ret = list(ret)
		#logging.debug('Result: %s' % ret)
		#logging.debug('Result class: %s' % ret.__class__)
		cache.set(key, pickle.dumps(ret), timeout=TIMEOUT)
		
	#if not None, then unpickle the string
	else:
		logging.debug('was in cache')
		ret = pickle.loads(ret)
	
	for table in self.query.tables:
		try:
			_table_key_map[table].add(key)
		except KeyError:
			_table_key_map[table] = set([key])
	
	return ret

SQLCompiler._execute_sql = SQLCompiler.execute_sql
SQLCompiler.execute_sql = try_cache

#TODO: add cache invalidation using signals
def invalidate(model):
	#get table name for model
	#cache.delete_many(_table_key_map[table_name])
