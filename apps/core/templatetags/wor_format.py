"""Formatting filters for metric values and comparisons."""
from decimal import Decimal

from django import template

register = template.Library()


def _num(value, places):
    if value is None:
        return None
    value = Decimal(value)
    if places == 0:
        return f"{value:,.0f}"
    text = f"{value:,.{places}f}"
    return text


@register.filter
def metric_value(value, unit):
    """Format a metric value with its unit; None → 'Not entered'."""
    if value is None:
        return "Not entered"
    if unit == "%":
        return f"{_num(value, 1)}%"
    if unit == "min":
        return f"{_num(value, 1)} min"
    return _num(value, 0)


@register.filter
def signed(value, unit=""):
    if value is None:
        return "Not available"
    value = Decimal(value)
    sign = "+" if value > 0 else ("−" if value < 0 else "±")
    mag = abs(value)
    if unit == "pp":
        return f"{sign}{_num(mag, 1)} pp"
    if unit == "%":
        return f"{sign}{_num(mag, 1)}%"
    if unit == "min":
        return f"{sign}{_num(mag, 1)} min"
    if unit == "calls":
        return f"{sign}{_num(mag, 0)}"
    return f"{sign}{_num(mag, 1)}"


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.simple_tag
def sparkline(values, width=120, height=32):
    """Inline SVG path for a series with gaps (None). Numbers only — safe markup."""
    from django.utils.safestring import mark_safe

    pts = [(i, float(v)) for i, v in enumerate(values or []) if v is not None]
    if len(pts) < 2:
        return ""
    n = max(len(values) - 1, 1)
    lo = min(v for _, v in pts)
    hi = max(v for _, v in pts)
    span = (hi - lo) or 1.0
    pad = 3

    def xy(i, v):
        return (round(i / n * width, 2), round(pad + (1 - (v - lo) / span) * (height - 2 * pad), 2))

    d, prev = [], None
    for i, v in pts:
        x, y = xy(i, v)
        d.append(f"{'L' if prev is not None and i == prev + 1 else 'M'}{x},{y}")
        prev = i
    lx, ly = xy(*pts[-1])
    return mark_safe(
        f'<svg class="spark" viewBox="0 -2 {width} {height + 4}" preserveAspectRatio="none" aria-hidden="true">'
        f'<path d="{" ".join(d)}"/><path class="dot" d="M{lx},{ly} l0,0"/></svg>'
    )


@register.simple_tag
def ring(percent, size=76):
    """Circular progress indicator (SVG presentation attributes only; CSP-safe)."""
    from django.utils.safestring import mark_safe

    try:
        pct = max(0, min(100, int(percent)))
    except (TypeError, ValueError):
        pct = 0
    r = 32
    circ = 2 * 3.14159265 * r
    dash = round(circ * pct / 100, 2)
    return mark_safe(
        f'<svg class="ring" viewBox="0 0 76 76" role="img" aria-label="{pct}% complete">'
        f'<circle class="track" cx="38" cy="38" r="{r}"/>'
        f'<circle class="value" cx="38" cy="38" r="{r}" stroke-dasharray="{dash} {round(circ, 2)}"/>'
        f'<text x="38" y="44" text-anchor="middle">{pct}%</text></svg>'
    )


@register.filter
def metric_number(value, unit):
    """Value without unit suffix, for display with a separately styled unit."""
    if value is None:
        return ""
    if unit == "calls":
        return _num(value, 0)
    return _num(value, 1)


@register.filter
def initials(user):
    name = (user.get_full_name() or user.username or "?").split()
    return "".join(p[0] for p in name[:2])
