from django.urls import path

from . import views

app_name = 'ticketing'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('tickets/', views.ticket_list, name='ticket_list'),
    path('tracker/', views.tracker, name='tracker'),
    path('insights/', views.insights, name='insights'),
]
