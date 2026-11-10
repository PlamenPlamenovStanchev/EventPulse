from django.urls import path

from . import views

app_name = 'attendees'

urlpatterns = [
    path('', views.AttendeeListView.as_view(), name='attendee_list'),
    path('create/', views.AttendeeCreateView.as_view(), name='attendee_create'),
    path('<int:pk>/', views.AttendeeDetailView.as_view(), name='attendee_detail'),
    path('<int:pk>/edit/', views.AttendeeUpdateView.as_view(), name='attendee_update'),
    path('<int:pk>/delete/', views.AttendeeDeleteView.as_view(), name='attendee_delete'),
]
