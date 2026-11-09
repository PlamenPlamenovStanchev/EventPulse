from django.urls import path

from . import views

app_name = 'events'

urlpatterns = [
    path('', views.EventListView.as_view(), name='event_list'),
    path('create/', views.EventCreateView.as_view(), name='event_create'),
    path('<int:pk>/', views.EventDetailView.as_view(), name='event_detail'),
    path('<int:pk>/edit/', views.EventUpdateView.as_view(), name='event_update'),
    path('<int:pk>/delete/', views.EventDeleteView.as_view(), name='event_delete'),
    path('venues/', views.VenueListView.as_view(), name='venue_list'),
    path('venues/create/', views.VenueCreateView.as_view(), name='venue_create'),
    path('venues/<int:pk>/', views.VenueDetailView.as_view(), name='venue_detail'),
    path('venues/<int:pk>/edit/', views.VenueUpdateView.as_view(), name='venue_update'),
    path('venues/<int:pk>/delete/', views.VenueDeleteView.as_view(), name='venue_delete'),
]
