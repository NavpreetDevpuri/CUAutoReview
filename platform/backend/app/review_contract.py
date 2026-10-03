"""Strict JSON output contracts for model reviews and label consolidation.

The platform owns this copy; it mirrors poc/schemas.py, and tests/test_review_contract.py fails if the two drift.
"""


def obj(**properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def array(item):
    return {"type": "array", "items": item}


TEXT = {"type": "string"}
STRINGS = array(TEXT)


def enum(*values):
    return {"type": "string", "enum": list(values)}


STEP = obj(
    step_id=TEXT,
    review_status=enum("reviewed", "not_reviewed", "insufficient_evidence"),
    intent=obj(kind=enum("declared", "inferred", "unknown"), text=TEXT),
    action=TEXT,
    observed_ui=TEXT,
    effect=TEXT,
    assessment=TEXT,
    evidence_refs=STRINGS,
    episode_refs=STRINGS,
)

# Immutable legacy contract for saved, unversioned reviews.
EPISODE_V1 = obj(
    episode_id=TEXT,
    mechanism=TEXT,
    onset_step_ids=STRINGS,
    recovery=obj(
        status=enum("not_assessed", "none_observed", "partial", "recovered", "unknown"),
        step_ids=STRINGS,
        evidence_refs=STRINGS,
        rationale=TEXT,
    ),
    outcome_contribution=enum("contributing", "noncontributing", "uncertain", "not_applicable"),
    label_id=TEXT,
    label_name=TEXT,
    evidence_refs=STRINGS,
    uncertainty=TEXT,
)
REVIEW_V1 = obj(
    review_kind=enum("failure_analysis", "pass_recovery"),
    summary=TEXT,
    result=enum("issues_observed", "no_issue_observed", "inconclusive"),
    coverage_notes=STRINGS,
    steps=array(STEP),
    episodes=array(EPISODE_V1),
)

REVIEW_SCHEMA_VERSION = "2"
EPISODE_V2 = obj(
    episode_id=TEXT,
    problem_number={"type": "integer", "minimum": 1},
    first_observed_step_id=TEXT,
    mechanism=TEXT,
    onset_step_ids=STRINGS,
    recovery=obj(
        status=enum("not_assessed", "none_observed", "partial", "recovered", "unknown"),
        step_ids=STRINGS,
        evidence_refs=STRINGS,
        rationale=TEXT,
    ),
    outcome_contribution=enum("contributing", "noncontributing", "uncertain", "not_applicable"),
    label_id=TEXT,
    label_name=TEXT,
    evidence_refs=STRINGS,
    uncertainty=TEXT,
)
REVIEW_V2 = obj(
    schema_version=enum(REVIEW_SCHEMA_VERSION),
    review_kind=enum("failure_analysis", "pass_recovery"),
    summary=TEXT,
    result=enum("issues_observed", "no_issue_observed", "inconclusive"),
    coverage_notes=STRINGS,
    steps=array(STEP),
    episodes=array(EPISODE_V2),
)

# New invocations use v2; validate_review still accepts the immutable v1 contract.
REVIEW = REVIEW_V2
LABEL = obj(id=TEXT, name=TEXT, description=TEXT, aliases=STRINGS, status=enum("draft"))
DEDUP = obj(
    summary=TEXT,
    labels=array(LABEL),
    mappings=array(obj(proposal_id=TEXT, canonical_label_id=TEXT, rationale=TEXT)),
    unresolved=STRINGS,
)
