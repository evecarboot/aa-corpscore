"""Template tags for AA CorpScore."""

from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Lookup a key in a dict. Returns None if missing or not a dict."""
    if not isinstance(dictionary, dict):
        return None
    return dictionary.get(key)


@register.filter
def sub(a, b):
    """Subtract b from a (Django templates lack arithmetic by default)."""
    try:
        return float(a) - float(b)
    except (TypeError, ValueError):
        return 0
