#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
from setuptools import setup
#import django_query_caching

package_name = 'django_query_caching'
test_package_name = '%s_test_project' % package_name

setup(name='django-query-caching',
	version='0.2.0dev',
	description="Caches the results of SQL queries transparently.",
	author='Seán Hayes',
	author_email='sean@seanhayes.name',
	classifiers=[
		"Development Status :: 3 - Alpha",
		"Framework :: Django",
		"Intended Audience :: Developers",
		"License :: OSI Approved :: BSD License",
		"Operating System :: OS Independent",
		"Programming Language :: Python",
		"Programming Language :: Python :: 2.6",
		"Topic :: Database",
		"Topic :: Internet :: WWW/HTTP :: Dynamic Content",
		"Topic :: Software Development :: Libraries",
		"Topic :: Software Development :: Libraries :: Python Modules"
	],
	keywords='django query cache',
	url='http://seanhayes.name/',
	download_url='https://github.com/SeanHayes/django-query-caching',
	license='BSD',
	package_dir={'test_app': os.path.join(test_package_name, 'apps', 'test_app')},
	packages=[
		'django_query_caching',
		'django_query_caching.test',
		'django_query_caching_test_project',
		'test_app',
	],
	include_package_data=True,
	install_requires=['Django',],
	test_suite = '%s.runtests.runtests' % test_package_name,
)

