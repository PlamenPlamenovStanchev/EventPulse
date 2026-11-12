from django.contrib import messages
from decimal import Decimal

from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.deletion import ProtectedError
from django.db.models.functions import Coalesce
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from .forms import EventForm, VenueForm
from .models import Event, Venue


class EventListView(ListView):
    model = Event
    context_object_name = "events"
    template_name = "events/event_list.html"

    def get_queryset(self):
        queryset = Event.objects.select_related("venue").annotate(
            ticket_count=Count("tickets")
        )
        search_term = self.request.GET.get("q", "").strip()
        venue_id = self.request.GET.get("venue", "").strip()
        sort = self.request.GET.get("sort", "date")

        if search_term:
            queryset = queryset.filter(name__icontains=search_term)
        if venue_id:
            queryset = queryset.filter(venue_id=venue_id)

        ordering = {"date": ("starts_at", "name"), "-date": ("-starts_at", "name")}
        return queryset.order_by(*ordering.get(sort, ordering["date"]))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["venues"] = Venue.objects.order_by("name")
        context["selected_venue"] = self.request.GET.get("venue", "")
        context["search_term"] = self.request.GET.get("q", "").strip()
        context["sort"] = self.request.GET.get("sort", "date")
        return context


class EventDetailView(DetailView):
    model = Event
    context_object_name = "event"
    template_name = "events/event_detail.html"

    def get_queryset(self):
        money_field = DecimalField(max_digits=10, decimal_places=2)
        return Event.objects.select_related("venue").prefetch_related(
            "tickets__attendee"
        ).annotate(
            ticket_count=Count("tickets"),
            expected_revenue=Coalesce(
                Sum("tickets__price"), Value(Decimal("0.00")), output_field=money_field
            ),
            collected_revenue=Coalesce(
                Sum("tickets__price", filter=Q(tickets__status="PAID")),
                Value(Decimal("0.00")),
                output_field=money_field,
            ),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["occupancy_percentage"] = (
            self.object.ticket_count / self.object.venue.capacity * 100
            if self.object.venue.capacity
            else 0
        )
        return context


class EventCreateView(CreateView):
    model = Event
    form_class = EventForm
    template_name = "events/event_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["has_venues"] = Venue.objects.exists()
        return context

    def form_valid(self, form):
        messages.success(self.request, "Event created successfully.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("events:event_detail", kwargs={"pk": self.object.pk})


class EventUpdateView(UpdateView):
    model = Event
    form_class = EventForm
    template_name = "events/event_form.html"

    def form_valid(self, form):
        messages.success(self.request, "Event updated successfully.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("events:event_detail", kwargs={"pk": self.object.pk})


class EventDeleteView(DeleteView):
    model = Event
    context_object_name = "event"
    template_name = "events/event_confirm_delete.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["ticket_count"] = self.object.tickets.count()
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Event deleted successfully.")
        return response

    def get_success_url(self):
        return reverse("events:event_list")


class VenueListView(ListView):
    model = Venue
    context_object_name = "venues"
    template_name = "events/venue_list.html"

    def get_queryset(self):
        queryset = Venue.objects.annotate(event_count=Count("events"))
        search_term = self.request.GET.get("q", "").strip()
        if search_term:
            queryset = queryset.filter(
                Q(name__icontains=search_term) | Q(address__icontains=search_term)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_term"] = self.request.GET.get("q", "").strip()
        return context


class VenueDetailView(DetailView):
    model = Venue
    context_object_name = "venue"
    template_name = "events/venue_detail.html"

    def get_queryset(self):
        return Venue.objects.prefetch_related("events")


class VenueCreateView(CreateView):
    model = Venue
    form_class = VenueForm
    template_name = "events/venue_form.html"

    def form_valid(self, form):
        messages.success(self.request, "Venue created successfully.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("events:venue_detail", kwargs={"pk": self.object.pk})


class VenueUpdateView(UpdateView):
    model = Venue
    form_class = VenueForm
    template_name = "events/venue_form.html"

    def form_valid(self, form):
        messages.success(self.request, "Venue updated successfully.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("events:venue_detail", kwargs={"pk": self.object.pk})


class VenueDeleteView(DeleteView):
    model = Venue
    context_object_name = "venue"
    template_name = "events/venue_confirm_delete.html"

    def form_valid(self, form):
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(self.request, "This venue cannot be deleted because one or more events reference it.")
            return redirect("events:venue_detail", pk=self.object.pk)

        messages.success(self.request, "Venue deleted successfully.")
        return response

    def get_success_url(self):
        return reverse("events:venue_list")
