import logging
import pdb

from django import db
from django.test import TestCase

from models import *

logger = logging.getLogger(__name__)

class SimpleTest(TestCase):
	def test_select_caching(self):
		"There should be one DB query to get the data, then any futerther attempts to get the same data should bypass the DB."
		with self.assertNumQueries(1):
			tms = TestModel.objects.all()
			len(tms)
		
		with self.assertNumQueries(0):
			tms = TestModel.objects.all()
			len(tms)
	
	
	
