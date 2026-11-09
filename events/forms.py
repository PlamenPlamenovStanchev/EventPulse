from django import forms

from .models import Event, Venue


class VenueForm(forms.ModelForm):
    """Collect venue details without bypassing the model's safeguards."""

    capacity = forms.IntegerField(
        min_value=1,
        error_messages={
            "required": "Enter the venue capacity.",
            "invalid": "Enter a whole-number capacity.",
            "min_value": "Venue capacity must be at least 1.",
        },
    )

    class Meta:
        model = Venue
        fields = ["name", "address", "capacity", "description"]
        labels = {
            "name": "Venue name",
            "address": "Venue address",
            "capacity": "Maximum capacity",
            "description": "Operational notes",
        }
        help_texts = {
            "name": "Use the name attendees and staff will recognize.",
            "address": "Include enough location detail for staff and attendees.",
            "capacity": "Maximum number of ticket reservations; at least 1.",
            "description": "Optional details for planning or accessibility.",
        }
        error_messages = {
            "name": {"required": "Enter a venue name."},
            "address": {"required": "Enter the venue address."},
        }
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Riverside Hall", "autocomplete": "organization"}),
            "address": forms.TextInput(attrs={"placeholder": "e.g. 1 Main Street, Sofia", "autocomplete": "street-address"}),
            "capacity": forms.NumberInput(attrs={"placeholder": "e.g. 250", "min": 1}),
            "description": forms.Textarea(attrs={"placeholder": "Accessibility, setup, or operating notes", "rows": 5}),
        }

    def clean_name(self):
        return self._clean_meaningful_text("name", "Enter a venue name.")

    def clean_address(self):
        return self._clean_meaningful_text("address", "Enter the venue address.")

    def _clean_meaningful_text(self, field_name, message):
        value = self.cleaned_data[field_name]
        cleaned_value = " ".join(value.split())
        if not cleaned_value:
            raise forms.ValidationError(message)
        return cleaned_value


class EventForm(forms.ModelForm):
    """Collect event details while preserving model-level capacity validation."""

    starts_at = forms.DateTimeField(
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={"type": "datetime-local"},
        ),
        error_messages={
            "required": "Enter when the event starts.",
            "invalid": "Enter a valid date and time.",
        },
    )
    venue = forms.ModelChoiceField(
        queryset=Venue.objects.none(),
        empty_label="Select a venue",
        error_messages={
            "required": "Select the venue hosting this event.",
            "invalid_choice": "Select a venue from the available list.",
        },
    )

    class Meta:
        model = Event
        fields = ["name", "starts_at", "venue", "description"]
        labels = {
            "name": "Event name",
            "starts_at": "Start date and time",
            "venue": "Venue",
            "description": "Event details",
        }
        help_texts = {
            "name": "Use the name attendees and staff will recognize.",
            "starts_at": "Enter the event's local scheduled start time.",
            "venue": "Capacity is checked before this event can be saved.",
            "description": "Share the essential details for this event.",
        }
        error_messages = {
            "name": {"required": "Enter an event name."},
            "description": {"required": "Enter event details."},
        }
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Autumn Conference"}),
            "description": forms.Textarea(attrs={"placeholder": "What should attendees and staff know?", "rows": 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["venue"].queryset = Venue.objects.order_by("name")

    def clean_name(self):
        return self._clean_meaningful_text("name", "Enter an event name.")

    def clean_description(self):
        return self._clean_meaningful_text("description", "Enter event details.")

    def _clean_meaningful_text(self, field_name, message):
        value = self.cleaned_data[field_name]
        cleaned_value = " ".join(value.split())
        if not cleaned_value:
            raise forms.ValidationError(message)
        return cleaned_value
