"""Questions 7 and 8 now take one free-text answer each.

Text already written in the retired sub-fields is folded into the remaining
field under its old heading, in live responses and in revision snapshots,
so nothing previously recorded is lost.
"""
from django.db import migrations

MERGES = {
    "7": ("observations", [
        ("performance_gaps", "Performance gaps"),
        ("evidence", "Evidence"),
        ("support_actions", "Proposed support or corrective actions"),
    ]),
    "8": ("achievements", [
        ("evidence", "Evidence of improvement"),
        ("readiness", "Readiness for more responsibility"),
        ("development", "Development opportunities"),
    ]),
}


def merge_answer(question, answer):
    """Return a new answer dict with retired keys folded into the kept key, or None if unchanged."""
    if not isinstance(answer, dict) or question not in MERGES:
        return None
    keep, retired = MERGES[question]
    if not any(k in answer for k, _ in retired):
        return None
    parts = []
    main = str(answer.get(keep) or "").strip()
    if main:
        parts.append(main)
    for key, label in retired:
        text = str(answer.get(key) or "").strip()
        if text:
            parts.append(f"{label}:\n{text}")
    merged = {k: v for k, v in answer.items() if k not in dict(retired)}
    merged[keep] = "\n\n".join(parts)
    return merged


def forwards(apps, schema_editor):
    ReviewResponse = apps.get_model("reviews", "ReviewResponse")
    for resp in ReviewResponse.objects.filter(question__in=[7, 8]):
        merged = merge_answer(str(resp.question), resp.answer)
        if merged is not None:
            resp.answer = merged
            resp.save(update_fields=["answer"])

    ReportRevision = apps.get_model("reviews", "ReportRevision")
    for rev in ReportRevision.objects.all().iterator():
        snap = rev.snapshot or {}
        responses = snap.get("responses") or {}
        changed = False
        for q in MERGES:
            merged = merge_answer(q, responses.get(q))
            if merged is not None:
                responses[q] = merged
                changed = True
        if changed:
            snap["responses"] = responses
            rev.snapshot = snap
            rev.save(update_fields=["snapshot"])


class Migration(migrations.Migration):

    dependencies = [
        ("reviews", "0002_missed_calls_percentage"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
