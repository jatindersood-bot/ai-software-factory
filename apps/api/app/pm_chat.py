"""
Product Manager chat: collect a structured Project Brief via one question at a time.
State: { step: int, brief_partial: dict }. When step reaches len(BRIEF_QUESTIONS), done=True.
"""

from typing import Any

BRIEF_FIELDS = [
    "problem_statement",
    "target_users",
    "core_features",
    "non_goals",
    "success_metrics",
    "constraints",
    "integration_needs",
    "data_privacy",
    "ui_expectations",
    "milestones",
    "acceptance_criteria",
]

BRIEF_QUESTIONS = [
    "What problem are you trying to solve? (Problem statement)",
    "Who are the target users?",
    "What are the core features for the MVP?",
    "What is explicitly out of scope? (Non-goals)",
    "How will you measure success?",
    "Any constraints (tech, time, budget)?",
    "Any integration needs (APIs, services)?",
    "Data or privacy requirements?",
    "Any UI/UX expectations or references?",
    "Key milestones or phases?",
    "Acceptance criteria for the first deliverable?",
]


def pm_chat_turn(
    message: str,
    state: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any], dict[str, Any], bool]:
    """
    Process one user message. Returns (assistant_message, new_state, brief_partial, done).
    If message is empty and state is empty, returns first question.
    """
    if state is None:
        state = {"step": 0, "brief_partial": {}}

    step = state.get("step", 0)
    brief = dict(state.get("brief_partial") or {})

    if step < len(BRIEF_QUESTIONS):
        # Store user's answer for current step (unless this is the very first request with no message)
        if message.strip():
            field = BRIEF_FIELDS[step]
            brief[field] = (message or "").strip() or "(Not provided)"
            next_step = step + 1
        else:
            next_step = step

        new_state = {"step": next_step, "brief_partial": brief}

        if next_step >= len(BRIEF_QUESTIONS):
            return (
                "Thanks! Your project brief is complete. Review it below and click Submit when ready.",
                new_state,
                new_state["brief_partial"],
                True,
            )

        next_question = BRIEF_QUESTIONS[next_step]
        return next_question, new_state, new_state["brief_partial"], False

    # Already done; could allow editing
    return (
        "Brief is already complete. You can submit it or edit from the review section.",
        state,
        brief,
        True,
    )
