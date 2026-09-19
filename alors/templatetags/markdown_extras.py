from cmarkgfm import github_flavored_markdown_to_html
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter(name="markdown")
def render_markdown(value):
    """Render a Markdown string as safe HTML.

    Rendering uses cmarkgfm (GitHub-flavored Markdown), which brings tables,
    strikethrough, task lists and clickable bare URLs. Raw HTML in the source
    is dropped, which is cmark's default: pass ``Options.CMARK_OPT_UNSAFE`` to
    :func:`github_flavored_markdown_to_html` to allow it instead.
    """
    if not value:
        return ""
    return mark_safe(github_flavored_markdown_to_html(str(value)))
