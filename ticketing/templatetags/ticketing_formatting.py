from decimal import Decimal, InvalidOperation

from django import template


register = template.Library()


@register.filter
def money(value):
    """Render a finite monetary value with two decimal places."""
    if value is None:
        return ""

    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return ""

    return format(amount, ".2f") if amount.is_finite() else ""
