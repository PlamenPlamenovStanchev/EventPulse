from django.urls import path

from . import views

app_name = 'events'

urlpatterns = [
    path('', views.event_list, name='event_list'),
    path('venues/', views.venue_list, name='venue_list'),
]
