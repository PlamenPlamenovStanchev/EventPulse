from django.contrib import messages
from decimal import Decimal

from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from attendees.models import Attendee
from events.models import Event

from .forms import PaymentForm, TicketForm
from .models import Ticket


def dashboard(request):
    return render(request, 'ticketing/dashboard.html')


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
    money_field = DecimalField(max_digits=10, decimal_places=2)
    overall_totals = Ticket.objects.aggregate(
        expected_revenue=Coalesce(
            Sum("price"), Value(Decimal("0.00"), output_field=money_field)
        ),
        collected_revenue=Coalesce(
            Sum("price", filter=Q(status=Ticket.Status.PAID)),
            Value(Decimal("0.00"), output_field=money_field),
        ),
        paid_ticket_count=Count("pk", filter=Q(status=Ticket.Status.PAID)),
        unpaid_ticket_count=Count("pk", filter=Q(status=Ticket.Status.UNPAID)),
    )
    expected_revenue = overall_totals["expected_revenue"]
    collected_revenue = overall_totals["collected_revenue"]

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
            "expected_revenue": expected_revenue,
            "collected_revenue": collected_revenue,
            "outstanding_revenue": expected_revenue - collected_revenue,
            "paid_ticket_count": overall_totals["paid_ticket_count"],
            "unpaid_ticket_count": overall_totals["unpaid_ticket_count"],
            "collection_percentage": (
                collected_revenue / expected_revenue * Decimal("100")
                if expected_revenue > Decimal("0.00")
                else Decimal("0.00")
            ),
        },
    )


def insights(request):
    return render(request, 'ticketing/insights.html')
