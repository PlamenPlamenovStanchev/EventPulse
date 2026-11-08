from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.validators import MinValueValidator
from django.db import models


class Ticket(models.Model):
    """A reservation and its payment state.

    ``save()`` calls ``full_clean()`` so normal application write paths enforce
    model validation. Bulk operations and queryset updates bypass Django model
    methods and must not be used for ticket issuance or changes. SQLite cannot
    provide a race-free count-then-insert capacity guarantee under concurrency;
    a production multi-writer deployment needs database-level locking support.
    """

    class Status(models.TextChoices):
        PAID = "PAID", "Paid"
        UNPAID = "UNPAID", "Unpaid"

    class PaymentMethod(models.TextChoices):
        CASH = "CASH", "Cash"
        CARD = "CARD", "Card"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank transfer"

    event = models.ForeignKey(
        "events.Event",
        on_delete=models.CASCADE,
        related_name="tickets",
        verbose_name="event",
        help_text="The event for which this place is reserved.",
    )
    attendee = models.ForeignKey(
        "attendees.Attendee",
        on_delete=models.PROTECT,
        related_name="tickets",
        verbose_name="attendee",
        help_text="The attendee holding this ticket.",
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="price",
        help_text="Ticket value; it cannot be negative.",
        validators=[MinValueValidator(0, message="Ticket price cannot be negative.")],
    )
    status = models.CharField(
        max_length=6,
        choices=Status.choices,
        default=Status.UNPAID,
        verbose_name="payment status",
        help_text="Whether payment has been received.",
    )
    payment_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="payment date",
        help_text="The date on which payment was received, if applicable.",
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        null=True,
        blank=True,
        verbose_name="payment method",
        help_text="The payment channel, if payment has been received.",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="created at",
        help_text="When this ticket was issued.",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "ticket"
        verbose_name_plural = "tickets"
        constraints = [
            models.UniqueConstraint(
                fields=["event", "attendee"], name="unique_ticket_per_event_attendee"
            ),
            models.CheckConstraint(
                condition=models.Q(price__gte=0),
                name="ticket_price_nonnegative",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="PAID",
                        payment_date__isnull=False,
                        payment_method__isnull=False,
                    )
                    & ~models.Q(payment_method="")
                )
                | models.Q(
                    status="UNPAID",
                    payment_date__isnull=True,
                    payment_method__isnull=True,
                ),
                name="ticket_payment_details_match_status",
            ),
        ]

    def __str__(self):
        return f"{self.attendee} — {self.event}"

    def clean(self):
        super().clean()
        self._validate_payment_details()
        self._validate_event_capacity()

    def _validate_payment_details(self):
        if self.status == self.Status.PAID:
            errors = {}
            if not self.payment_date:
                errors["payment_date"] = "Paid tickets require a payment date."
            if not self.payment_method:
                errors["payment_method"] = "Paid tickets require a payment method."
            if errors:
                raise ValidationError(errors)
        elif self.status == self.Status.UNPAID and (
            self.payment_date or self.payment_method
        ):
            raise ValidationError(
                "Unpaid tickets cannot have payment date or payment method details."
            )

    def _validate_event_capacity(self):
        if not self.event_id:
            return

        try:
            event = self.event
        except ObjectDoesNotExist:
            return

        reserved_tickets = event.tickets.exclude(pk=self.pk).count()
        if reserved_tickets >= event.venue.capacity:
            raise ValidationError(
                {"event": "This event's venue is already at full capacity."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
