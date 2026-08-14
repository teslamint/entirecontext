"""Migration to schema v18: index feedback-bearing lessons by verdict and recency."""

MIGRATION_STEPS = [
    """CREATE INDEX IF NOT EXISTS idx_assessments_feedback_recency
    ON assessments(verdict, created_at DESC, id DESC)
    WHERE feedback IS NOT NULL"""
]
