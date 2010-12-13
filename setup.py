#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import setup

version = '0.1.0'

setup(name='django-query-caching',
	version=version,
	description="Caches the results of SQL queries transparently.",
	author='Seán Hayes',
	author_email='sean@seanhayes.name',
	keywords='django query cache',
	url='https://github.com/SeanHayes/django-query-caching',
	license='BSD',
	packages=['django_config_gen'],
	install_requires=['django',],
)


