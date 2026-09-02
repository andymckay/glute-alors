import markdown as md
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter(name="markdown")
def render_markdown(value):
    """Render a Markdown string as safe HTML."""
    if not value:
        return ""
    html = md.markdown(str(value), extensions=["extra", "sane_lists"])
    return mark_safe(html)
