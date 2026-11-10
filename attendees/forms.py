from django import forms

from .models import Attendee


class AttendeeForm(forms.ModelForm):
    """Collect attendee contact details with clear, form-level validation."""

    phone = forms.CharField(
        label="Phone number",
        max_length=30,
        help_text="Include the country code when available.",
        widget=forms.TelInput(
            attrs={"placeholder": "e.g. +44 20 7946 0958", "autocomplete": "tel"}
        ),
        error_messages={
            "required": "Enter a phone number.",
            "max_length": "Enter a phone number with no more than 30 characters.",
        },
    )

    class Meta:
        model = Attendee
        fields = ["name", "email", "phone"]
        labels = {
            "name": "Full name",
            "email": "Email address",
            "phone": "Phone number",
        }
        help_texts = {
            "name": "Enter the attendee's full name as they would like it shown.",
            "email": "Use an email address the attendee can access.",
        }
        error_messages = {
            "name": {"required": "Enter the attendee's name."},
            "email": {
                "required": "Enter an email address.",
                "invalid": "Enter a valid email address.",
            },
        }
        widgets = {
            "name": forms.TextInput(
                attrs={"placeholder": "e.g. Alex Morgan", "autocomplete": "name"}
            ),
            "email": forms.EmailInput(
                attrs={
                    "placeholder": "e.g. alex.morgan@example.com",
                    "autocomplete": "email",
                }
            ),
        }

    def clean_name(self):
        value = self.cleaned_data["name"]
        cleaned_value = " ".join(value.split())
        if not cleaned_value:
            raise forms.ValidationError("Enter the attendee's name.")
        return cleaned_value

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        duplicate_emails = Attendee.objects.filter(email__iexact=email)
        if self.instance.pk:
            duplicate_emails = duplicate_emails.exclude(pk=self.instance.pk)
        if duplicate_emails.exists():
            raise forms.ValidationError(
                "An attendee with this email address already exists."
            )
        return email

    def clean_phone(self):
        value = " ".join(self.cleaned_data["phone"].split())
        allowed_characters = set("0123456789+() -")
        digit_count = sum(character.isdigit() for character in value)
        if (
            not value
            or any(character not in allowed_characters for character in value)
            or "+" in value[1:]
            or ("+" in value and not value.startswith("+"))
            or value.count("(") != value.count(")")
            or not 7 <= digit_count <= 15
        ):
            raise forms.ValidationError("Enter a valid phone number.")
        return value
