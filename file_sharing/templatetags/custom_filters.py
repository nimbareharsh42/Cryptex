from django import template

register = template.Library()

@register.filter
def endswith(value, suffix):
    """Check if a string ends with the given suffix."""
    if not isinstance(value, str):
        return False
    return value.lower().endswith(suffix.lower())