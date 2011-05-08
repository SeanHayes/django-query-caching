from django.db import models

# Create your models here.

class TestModel(models.Model):
	added = models.DateTimeField(auto_now_add=True)
	last_edited = models.DateTimeField(auto_now=True)
