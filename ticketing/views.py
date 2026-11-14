from django.contrib import messages
from decimal import Decimal

from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from attendees.models import Attendee
from events.models import Event

from .analytics import get_event_performance, get_revenue_metrics
from .forms import PaymentForm, TicketForm
from .models import Ticket


def dashboard(request):
    revenue_metrics = get_revenue_metrics()
    return render(
        request,
        "ticketing/dashboard.html",
        {
            "total_event_count": Event.objects.count(),
            "total_attendee_count": Attendee.objects.count(),
            "expected_revenue": revenue_metrics.expected_revenue,
            "collected_revenue": revenue_metrics.collected_revenue,
            "outstanding_revenue": revenue_metrics.outstanding_revenue,
            "collection_percentage": revenue_metrics.collection_percentage,
            "issued_ticket_count": revenue_metrics.issued_ticket_count,
            "event_performance": get_event_performance(),
        },
    )


class TicketListView(ListView):
    model = Ticket
    context_object_name = "tickets"
    template_name = "ticketing/ticket_list.html"

    sort_options = {
        "newest": ("-created_at",),
        "oldest": ("created_at",),
        "price": ("price", "-created_at"),
        "-price": ("-price", "-created_at"),
        "event_date": ("event__starts_at", "event__name", "-created_at"),
    }

    def get_queryset(self):
        queryset = Ticket.objects.select_related("event__venue", "attendee")
        search_term = self.request.GET.get("q", "").strip()
        selected_event = self.get_selected_event()
        selected_status = self.get_selected_status()

        if search_term:
            queryset = queryset.filter(
                Q(event__name__icontains=search_term)
                | Q(attendee__name__icontains=search_term)
                | Q(attendee__email__icontains=search_term)
            )
        if selected_event:
            queryset = queryset.filter(event=selected_event)
        if selected_status:
            queryset = queryset.filter(status=selected_status)

        return queryset.order_by(*self.sort_options[self.get_sort_option()])

    def get_selected_event(self):
        event_id = self.request.GET.get("event", "").strip()
        if not event_id.isdigit():
            return None
        return Event.objects.filter(pk=event_id).first()

    def get_selected_status(self):
        status = self.request.GET.get("status", "")
        valid_statuses = {value for value, _ in Ticket.Status.choices}
        return status if status in valid_statuses else ""

    def get_sort_option(self):
        sort_option = self.request.GET.get("sort", "newest")
        return sort_option if sort_option in self.sort_options else "newest"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["events"] = Event.objects.select_related("venue").order_by(
            "starts_at", "name"
        )
        context["search_term"] = self.request.GET.get("q", "").strip()
        context["selected_event"] = self.get_selected_event()
        context["selected_status"] = self.get_selected_status()
        context["sort"] = self.get_sort_option()
        context["matching_ticket_count"] = context["tickets"].count()
        return context


class TicketDetailView(DetailView):
    model = Ticket
    context_object_name = "ticket"
    template_name = "ticketing/ticket_detail.html"

    def get_queryset(self):
        return Ticket.objects.select_related("event__venue", "attendee")


class TicketCreateView(CreateView):
    model = Ticket
    form_class = TicketForm
    template_name = "ticketing/ticket_form.html"

    def prerequisites_exist(self):
        return Event.objects.exists() and Attendee.objects.exists()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["has_events"] = Event.objects.exists()
        context["has_attendees"] = Attendee.objects.exists()
        context["can_create_ticket"] = (
            context["has_events"] and context["has_attendees"]
        )
        return context

    def get_initial(self):
        initial = super().get_initial()
        event_id = self.request.GET.get("event", "").strip()
        if event_id.isdigit() and Event.objects.filter(pk=event_id).exists():
            initial["event"] = event_id
        return initial

    def post(self, request, *args, **kwargs):
        if not self.prerequisites_exist():
            messages.error(
                request,
                "Create at least one event and one attendee before issuing a ticket.",
            )
            return self.get(request, *args, **kwargs)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        messages.success(self.request, "Ticket created successfully.")
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, "Please correct the ticket form errors below.")
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse("ticketing:ticket_detail", kwargs={"pk": self.object.pk})


class TicketUpdateView(UpdateView):
    model = Ticket
    form_class = TicketForm
    template_name = "ticketing/ticket_form.html"

    def form_valid(self, form):
        messages.success(self.request, "Ticket updated successfully.")
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, "Please correct the ticket form errors below.")
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse("ticketing:ticket_detail", kwargs={"pk": self.object.pk})


class TicketDeleteView(DeleteView):
    model = Ticket
    context_object_name = "ticket"
    template_name = "ticketing/ticket_confirm_delete.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Ticket deleted successfully.")
        return response

    def get_success_url(self):
        return reverse("ticketing:ticket_list")


def mark_ticket_paid(request, pk):
    ticket = get_object_or_404(
        Ticket.objects.select_related("event__venue", "attendee"), pk=pk
    )

    if request.method == "POST":
        if ticket.status == Ticket.Status.PAID:
            messages.info(request, "This ticket is already marked as paid.")
            return redirect("ticketing:ticket_detail", pk=ticket.pk)

        ticket.status = Ticket.Status.PAID
        form = PaymentForm(request.POST, instance=ticket)
        if form.is_valid():
            form.save()
            messages.success(request, "Ticket marked as paid.")
            return redirect("ticketing:ticket_detail", pk=ticket.pk)
        ticket.status = Ticket.Status.UNPAID
    else:
        form = PaymentForm(instance=ticket)

    return render(
        request,
        "ticketing/ticket_payment_form.html",
        {"ticket": ticket, "form": form, "target_status": Ticket.Status.PAID},
    )


def mark_ticket_unpaid(request, pk):
    ticket = get_object_or_404(
        Ticket.objects.select_related("event__venue", "attendee"), pk=pk
    )

    if request.method == "POST":
        if ticket.status == Ticket.Status.UNPAID:
            messages.info(request, "This ticket is already marked as unpaid.")
            return redirect("ticketing:ticket_detail", pk=ticket.pk)

        ticket.status = Ticket.Status.UNPAID
        ticket.payment_date = None
        ticket.payment_method = None
        ticket.save()
        messages.success(request, "Ticket marked as unpaid.")
        return redirect("ticketing:ticket_detail", pk=ticket.pk)

    return render(
        request,
        "ticketing/ticket_payment_form.html",
        {"ticket": ticket, "target_status": Ticket.Status.UNPAID},
    )


def tracker(request):
    revenue_metrics = get_revenue_metrics()

    search_term = request.GET.get("q", "").strip()
    event_id = request.GET.get("event", "").strip()
    selected_event = Event.objects.filter(pk=event_id).first() if event_id.isdigit() else None
    selected_status = request.GET.get("status", "")
    valid_statuses = {value for value, _ in Ticket.Status.choices}
    if selected_status not in valid_statuses:
        selected_status = ""

    tickets = Ticket.objects.select_related("event__venue", "attendee")
    if search_term:
        tickets = tickets.filter(
            Q(event__name__icontains=search_term)
            | Q(attendee__name__icontains=search_term)
            | Q(attendee__email__icontains=search_term)
        )
    if selected_event:
        tickets = tickets.filter(event=selected_event)
    if selected_status:
        tickets = tickets.filter(status=selected_status)
    tickets = tickets.order_by("event__starts_at", "event__name", "attendee__name")

    return render(
        request,
        'ticketing/tracker.html',
        {
            "tickets": tickets,
            "events": Event.objects.select_related("venue").order_by("starts_at", "name"),
            "search_term": search_term,
            "selected_event": selected_event,
            "selected_status": selected_status,
            "matching_ticket_count": tickets.count(),
            "expected_revenue": revenue_metrics.expected_revenue,
            "collected_revenue": revenue_metrics.collected_revenue,
            "outstanding_revenue": revenue_metrics.outstanding_revenue,
            "paid_ticket_count": revenue_metrics.paid_ticket_count,
            "unpaid_ticket_count": revenue_metrics.unpaid_ticket_count,
            "collection_percentage": revenue_metrics.collection_percentage,
        },
    )


def insights(request):
    selected_event_id = request.GET.get("event", "").strip()
    selected_event = (
        Event.objects.filter(pk=selected_event_id).first()
        if selected_event_id.isdigit()
        else None
    )
    events = Event.objects.select_related("venue").order_by("starts_at", "name")
    scoped_events = events.filter(pk=selected_event.pk) if selected_event else events
    scoped_tickets = Ticket.objects.filter(event=selected_event) if selected_event else None
    revenue_metrics = get_revenue_metrics(scoped_tickets)
    event_performance = get_event_performance(scoped_events)

    max_expected_revenue = max(
        (performance.expected_revenue for performance in event_performance),
        default=Decimal("0.00"),
    )
    chart_rows = [
        {
            "performance": performance,
            "expected_width": (
                performance.expected_revenue / max_expected_revenue * Decimal("100")
                if max_expected_revenue
                else Decimal("0")
            ),
            "collected_width": (
                performance.collected_revenue / max_expected_revenue * Decimal("100")
                if max_expected_revenue
                else Decimal("0")
            ),
        }
        for performance in event_performance
    ]
    ticket_total = revenue_metrics.issued_ticket_count
    paid_ticket_percentage = (
        Decimal(revenue_metrics.paid_ticket_count) / Decimal(ticket_total) * Decimal("100")
        if ticket_total
        else Decimal("0")
    )
    unpaid_ticket_percentage = (
        Decimal(revenue_metrics.unpaid_ticket_count) / Decimal(ticket_total) * Decimal("100")
        if ticket_total
        else Decimal("0")
    )

    return render(
        request,
        "ticketing/insights.html",
        {
            "events": events,
            "selected_event": selected_event,
            "event_performance": event_performance,
            "chart_rows": chart_rows,
            "expected_revenue": revenue_metrics.expected_revenue,
            "collected_revenue": revenue_metrics.collected_revenue,
            "outstanding_revenue": revenue_metrics.outstanding_revenue,
            "collection_percentage": revenue_metrics.collection_percentage,
            "issued_ticket_count": revenue_metrics.issued_ticket_count,
            "paid_ticket_count": revenue_metrics.paid_ticket_count,
            "unpaid_ticket_count": revenue_metrics.unpaid_ticket_count,
            "paid_ticket_percentage": paid_ticket_percentage,
            "unpaid_ticket_percentage": unpaid_ticket_percentage,
        },
    )
