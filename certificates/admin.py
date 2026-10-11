from django.contrib import admin

from .models import Certificate, Job

admin.site.register(Job)
admin.site.register(Certificate)
