from __future__ import absolute_import
from datetime import datetime

from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save

from domain.models import Domain
from phone.processor import create_backup, create_phone_user, BACKUP_XMLNS, \
    REGISTRATION_XMLNS
from receiver.models import Attachment
from scheduler.fields import PickledObjectField
from xformmanager.models import Metadata
import xformmanager.xmlrouter as xmlrouter



# the scheduler is a really bad place for this class to live


class Phone(models.Model):
    """A phone (device)."""
    device_id = models.CharField(max_length=32)
    domain = models.ForeignKey(Domain, related_name="phones")
    
    def __unicode__(self):
        return self.device_id
    
class PhoneUserInfo(models.Model):
    """
    Someone who uses a phone.  This object is somewhat like a profile in that 
    it basically annotates a User account with some extra info about the phone
    the user is using.  However a user might have multiple phones.
    """
    user = models.ForeignKey(User, null=True)
    phone = models.ForeignKey(Phone, related_name="users")
    
    # the username and password are from the phone, not the user account
    username = models.CharField(max_length=32)
    password = models.CharField(max_length=32, null=True) 
    uuid = models.CharField(max_length=32)
    registered = models.DateField(default=datetime.today)
    additional_data = PickledObjectField(null=True, blank=True)
    
    class Meta:
        unique_together = ("phone", "username")

    def __unicode__(self):
        return unicode(self.user)
    
    
class PhoneBackup(models.Model):
    """An instance of a phone backup.  Points to a specific device
       as well as a set of users.  Additionally, has information about
       the original attachment that created the backup"""
    
    # TODO: Should this  be moved to its own app since it's not core
    # phone user functionality?
    attachment = models.ForeignKey(Attachment)    
    phone = models.ForeignKey(Phone)

    def __unicode__(self):
        return "Id: %s, Device: %s, Users: %s" % (self.id, self.phone,
                                                  self.device.users.count())


def create_phone(sender, instance, created, **kwargs):
    """
    Create a phone from a metadata submission if its a device we've
    not seen.
    """
    
    if not created:             return
    if not instance.device_id:  return
    
    Phone.objects.get_or_create(device_id = instance.device_id,
                                domain = instance.attachment.submission.domain)
    

post_save.connect(create_phone, sender=Metadata)
    
# register our backup and registration methods, like a signal, 
# in the models file to make sure this always gets bootstrapped.
xmlrouter.register(BACKUP_XMLNS, create_backup)
xmlrouter.register(REGISTRATION_XMLNS, create_phone_user)