"""ASI:One Interactive Card builders for the supervisor chat experience."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

from uagents_core.contrib.protocols.chat import MetadataContent
from uagents_core.contrib.protocols.chat.cards import (
    BadgeNode,
    CtaAction,
    CustomCardPayload,
    ReviewCardPayload,
    ReviewSummaryRow,
    SectionNode,
    TextNode,
    create_card_content,
)


def approval_card(
    actions: Sequence[str], *, session_id: str | None = None
) -> MetadataContent:
    """Build a native approve/deny card for one pending tool-call batch."""

    rows = [
        ReviewSummaryRow(label=f"Action {index}", value=description[:500])
        for index, description in enumerate(actions, start=1)
    ]
    selection_context = {"session_id": session_id} if session_id else {}
    payload = ReviewCardPayload(
        title="Review proposed healthcare workflow actions",
        summary_rows=rows,
        approve_cta=CtaAction(
            label="Approve actions",
            selection={"action": "approve", **selection_context},
            primary=True,
        ),
        reject_cta=CtaAction(
            label="Deny actions",
            selection={"action": "deny", **selection_context},
        ),
    )
    return create_card_content(payload, card_id=uuid4())


def outcome_card(
    text: str,
    *,
    status: str = "Completed",
    session_id: str | None = None,
) -> MetadataContent:
    """Build a terminal summary card while retaining a plain-text fallback."""

    details = text.strip() or "The workflow finished without a narrative response."
    children = [
        BadgeNode(type="badge", label=status[:80], variant="success"),
        TextNode(type="text", value=details[:4000], style="body"),
    ]
    if session_id:
        children.append(
            TextNode(
                type="text",
                value=f"Planner session: {session_id}",
                style="muted",
            )
        )
    payload = CustomCardPayload(
        root=SectionNode(
            type="section",
            title="CareFlow outcome",
            subtitle="Grounded specialist results with deterministic safety checks",
            children=children,
        )
    )
    return create_card_content(payload, card_id=uuid4(), is_terminal=True)
