from django.urls import path

from . import views

app_name = 'attendees'

urlpatterns = [
    path('', views.attendee_list, name='attendee_list'),
]
