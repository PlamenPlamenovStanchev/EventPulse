from django import forms
from django.core.exceptions import NON_FIELD_ERRORS

from attendees.models import Attendee
from events.models import Event

from .models import Ticket


class EventTicketChoiceField(forms.ModelChoiceField):
    """Render event choices with the venue context needed to issue a ticket."""

    def label_from_instance(self, event):
        return f"{event.name} — {event.venue.name} ({event.venue.capacity} places)"


class AttendeeTicketChoiceField(forms.ModelChoiceField):
    """Render attendee choices with their primary contact identifier."""

    def label_from_instance(self, attendee):
        return f"{attendee.name} ({attendee.email})"


class TicketForm(forms.ModelForm):
    """Collect ticket details while relying on Ticket model validation."""

    event = EventTicketChoiceField(
        queryset=Event.objects.none(),
        empty_label="Select an event",
        label="Event",
        help_text="Venue capacity is checked before the ticket is saved.",
        error_messages={
            "required": "Select the event for this ticket.",
            "invalid_choice": "Select an event from the available list.",
        },
    )
    attendee = AttendeeTicketChoiceField(
        queryset=Attendee.objects.none(),
        empty_label="Select an attendee",
        label="Attendee",
        help_text="Each attendee can hold one ticket per event.",
        error_messages={
            "required": "Select the attendee holding this ticket.",
            "invalid_choice": "Select an attendee from the available list.",
        },
    )
    price = forms.DecimalField(
        min_value=0,
        max_digits=10,
        decimal_places=2,
        label="Ticket price",
        help_text="Enter 0.00 for a complimentary ticket.",
        error_messages={
            "required": "Enter the ticket price.",
            "invalid": "Enter a valid ticket price.",
            "min_value": "Ticket price cannot be negative.",
        },
        widget=forms.NumberInput(
            attrs={"placeholder": "e.g. 25.00", "min": "0", "step": "0.01"}
        ),
    )
    status = forms.ChoiceField(
        choices=Ticket.Status.choices,
        label="Payment status",
        help_text="Paid tickets require both payment details.",
        error_messages={"required": "Select the payment status."},
    )
    payment_date = forms.DateField(
        required=False,
        input_formats=["%Y-%m-%d"],
        label="Payment date",
        help_text="Required when the ticket is paid.",
        widget=forms.DateInput(
            format="%Y-%m-%d", attrs={"type": "date"}
        ),
        error_messages={"invalid": "Enter a valid payment date."},
    )
    payment_method = forms.TypedChoiceField(
        required=False,
        choices=[("", "Select a payment method")] + list(Ticket.PaymentMethod.choices),
        empty_value=None,
        label="Payment method",
        help_text="Required when the ticket is paid.",
        error_messages={"invalid_choice": "Select a valid payment method."},
    )

    class Meta:
        model = Ticket
        fields = [
            "event",
            "attendee",
            "price",
            "status",
            "payment_date",
            "payment_method",
        ]
        labels = {
            "event": "Event",
            "attendee": "Attendee",
            "price": "Ticket price",
            "status": "Payment status",
            "payment_date": "Payment date",
            "payment_method": "Payment method",
        }
        help_texts = {
            "event": "Venue capacity is checked before the ticket is saved.",
            "attendee": "Each attendee can hold one ticket per event.",
            "price": "Enter 0.00 for a complimentary ticket.",
            "status": "Paid tickets require both payment details.",
            "payment_date": "Required when the ticket is paid.",
            "payment_method": "Required when the ticket is paid.",
        }
        error_messages = {
            NON_FIELD_ERRORS: {
                "unique_together": "This attendee already has a ticket for the selected event.",
            },
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["event"].queryset = Event.objects.select_related("venue").order_by(
            "starts_at", "name"
        )
        self.fields["attendee"].queryset = Attendee.objects.order_by("name", "email")


class PaymentForm(forms.ModelForm):
    """Collect payment details while the caller determines the payment status."""
    payment_date = forms.DateField(
        required=False,
        input_formats=["%Y-%m-%d"],
        label="Payment date",
        help_text="Required when the ticket is paid.",
        widget=forms.DateInput(
            format="%Y-%m-%d", attrs={"type": "date"}
        ),
        error_messages={"invalid": "Enter a valid payment date."},
    )
    payment_method = forms.TypedChoiceField(
        required=False,
        choices=[("", "Select a payment method")] + list(Ticket.PaymentMethod.choices),
        empty_value=None,
        label="Payment method",
        help_text="Required when the ticket is paid.",
        error_messages={"invalid_choice": "Select a valid payment method."},
    )

    class Meta:
        model = Ticket
        fields = ["payment_date", "payment_method"]
