"""Definitions of the 12 management review questions.

Each question has structured sub-fields. Questions 1, 2 and 10 have
additional structured data stored elsewhere (priorities, metrics,
commitments); their sub-fields here hold the accompanying narrative.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SubField:
    key: str
    label: str
    required: bool = True
    help: str = ""
    rows: int = 3


@dataclass(frozen=True)
class Question:
    number: int
    section: str
    text: str
    fields: tuple = field(default_factory=tuple)
    kind: str = "text"  # text | priorities | metrics | commitments
    confidential: bool = False
    comment_category: str = "other"

    @property
    def required_keys(self):
        return [f.key for f in self.fields if f.required]


SECTIONS = [
    ("outcomes", "Section 1: Weekly Outcomes"),
    ("execution", "Section 2: Support Execution"),
    ("leadership", "Section 3: Leadership & Capacity"),
    ("commitments", "Section 4: Commitments"),
]

QUESTIONS = [
    Question(
        1, "outcomes", "What were last week's top 3 priorities? What shipped?",
        fields=(SubField("summary", "Additional explanation", required=False,
                         help="Context that applies across the priorities."),),
        kind="priorities", comment_category="outcomes",
    ),
    Question(
        2, "outcomes",
        "What measurable progress did we make toward support response time / SLA, missed calls, and CSAT?",
        fields=(SubField("interpretation", "Your interpretation of the movement", rows=4,
                         help="Explain what the figures show. The comparison is calculated from saved records."),),
        kind="metrics", comment_category="outcomes",
    ),
    Question(
        3, "outcomes", "What trend did you notice this week that management should be aware of?",
        fields=(
            SubField("trends", "Significant trends", rows=4),
            SubField("risks", "Risks and changes", required=False),
            SubField("observations", "Other observations", required=False),
        ),
        comment_category="outcomes",
    ),
    Question(
        4, "execution", "Where did customers experience the most friction?",
        fields=(
            SubField("friction_points", "Main friction points"),
            SubField("impact", "Impact on customers"),
            SubField("examples", "Examples", required=False),
        ),
        comment_category="execution",
    ),
    Question(
        5, "execution", "What root cause or recurring issue appeared more than once?",
        fields=(
            SubField("recurring_issues", "Recurring problems"),
            SubField("suspected_causes", "Suspected root causes"),
            SubField("evidence", "Evidence", required=False),
            SubField("affected_processes", "Affected processes", required=False),
        ),
        comment_category="root_causes",
    ),
    Question(
        6, "execution", "What system, process, or training change will prevent that from happening again?",
        fields=(
            SubField("corrective_actions", "Corrective actions"),
            SubField("expected_impact", "Expected impact"),
            SubField("implementation", "Implementation approach"),
        ),
        comment_category="root_causes",
    ),
    Question(
        7, "leadership", "Who on your team is underperforming, and why?",
        fields=(
            SubField("observations", "Observations",
                     help="Keep entries factual. Write 'No concerns this week' if none."),
            SubField("performance_gaps", "Performance gaps", required=False),
            SubField("evidence", "Evidence", required=False),
            SubField("support_actions", "Proposed support or corrective actions", required=False),
        ),
        confidential=True, comment_category="leadership",
    ),
    Question(
        8, "leadership", "Who is improving or ready for more responsibility?",
        fields=(
            SubField("achievements", "Achievements"),
            SubField("evidence", "Evidence of improvement", required=False),
            SubField("readiness", "Readiness for more responsibility", required=False),
            SubField("development", "Development opportunities", required=False),
        ),
        confidential=True, comment_category="leadership",
    ),
    Question(
        9, "leadership", "If support volume doubled tomorrow, what would break first?",
        fields=(
            SubField("first_to_break", "What would break first (capacity constraints)"),
            SubField("operational_risks", "Operational risks", required=False),
            SubField("staffing", "Staffing concerns", required=False),
            SubField("bottlenecks", "Process bottlenecks", required=False),
            SubField("mitigation", "Mitigation strategies"),
        ),
        comment_category="leadership",
    ),
    Question(
        10, "commitments", "What are your 3 outcomes for next week?",
        fields=(SubField("notes", "Additional notes", required=False),),
        kind="commitments", comment_category="commitments",
    ),
    Question(
        11, "commitments", "What will you do differently next week based on what you learned this week?",
        fields=(
            SubField("change", "Specific change"),
            SubField("reason", "Reason (what you learned)"),
            SubField("expected_result", "Expected result"),
        ),
        comment_category="commitments",
    ),
    Question(
        12, "commitments", "What will I see in the dashboard that proves success?",
        fields=(
            SubField("indicators", "Observable indicators"),
            SubField("targets", "Target values", required=False),
            SubField("evidence", "Evidence that will demonstrate success"),
        ),
        comment_category="commitments",
    ),
]

QUESTIONS_BY_NUMBER = {q.number: q for q in QUESTIONS}
QUESTION_CHOICES = [(q.number, f"Q{q.number}: {q.text}") for q in QUESTIONS]
CONFIDENTIAL_QUESTIONS = {q.number for q in QUESTIONS if q.confidential}


def questions_by_section():
    return [(key, title, [q for q in QUESTIONS if q.section == key]) for key, title in SECTIONS]
