from django.db import models

# Create your models here.

class TestModelBase(models.Model):
	name = models.CharField(max_length=25)
	added = models.DateTimeField(auto_now_add=True)
	last_edited = models.DateTimeField(auto_now=True)
	
	def __unicode__(self):
		return u'%s: %s (Created on %s, Edited on %s)' % (self.__class__, self.name, self.added, self.last_edited,)
	
	class Meta:
		abstract = True

class TestModelA(TestModelBase):
	pass

class TestModelB(TestModelBase):
	related = models.ForeignKey(TestModelA)

class TestModelC(TestModelBase):
	related = models.ManyToManyField(TestModelA)
