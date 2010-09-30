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

def get_key(compiler):
	#generate keys that will be unique to each query
	#NOTE: keys must be 250 characters or fewer
	sql, params = compiler.as_nested_sql()
	sql = sql.replace(' ','').replace('`','').replace('.','')
	sql = sql % params
	sql = sql.replace('%', '%25').replace(' ', '%20')
	return sql

#TODO: add cache invalidation using signals
def invalidate(model):
	#get table names for model and parents
	parents = model._meta.parents.keys()
	for table_name in table_names:
		cache.delete_many(_table_key_map[table_name])

#overwrite SQLCompiler.execute_sql
def try_cache(self, result_type=None):
	#logging.debug('try_cache()')
	#logging.debug(self)
	#logging.debug('Result type: %s' % result_type)
	
	#SELECT, INSERT, UPDATE, DELETE are all 6 chars long
	query_type = self.as_sql()[0][:6]
	logging.debug('Query type: %s' % query_type)
	
	if query_type == 'SELECT':
		key = get_key(self)
		logging.debug('Key: %s' % key)
		
		ret = cache.get(key)
		if ret is None:
			logging.debug('wasn\'t in cache')
			if result_type is None:
				ret = self._execute_sql()
			else:
				ret = self._execute_sql(result_type)
			logging.debug('ret: %s' % ret)
			if ret is not None:
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
	#INSERT, UPDATE, DELETE statements
	else:
		#perform operation
		if result_type is None:
			ret = self._execute_sql()
		else:
			ret = self._execute_sql(result_type)
		#TODO: invalidate cache only if rows were affected
		
		keys_to_delete = set([])
		for table in self.query.tables:
			try:
				keys_to_delete |= _table_key_map[table]
			except KeyError:
				pass
		
		cache.delete_many(keys_to_delete)
		
		return ret

SQLCompiler._execute_sql = SQLCompiler.execute_sql
SQLCompiler.execute_sql = try_cache


