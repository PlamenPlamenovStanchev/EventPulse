from django.urls import path

from . import views

app_name = 'ticketing'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('tickets/', views.TicketListView.as_view(), name='ticket_list'),
    path('tickets/create/', views.TicketCreateView.as_view(), name='ticket_create'),
    path('tickets/<int:pk>/', views.TicketDetailView.as_view(), name='ticket_detail'),
    path('tickets/<int:pk>/edit/', views.TicketUpdateView.as_view(), name='ticket_update'),
    path('tickets/<int:pk>/delete/', views.TicketDeleteView.as_view(), name='ticket_delete'),
    path('tracker/', views.tracker, name='tracker'),
    path('insights/', views.insights, name='insights'),
]
