"""ASI:One Interactive Card builders for the supervisor chat experience."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any
from uuid import uuid4

from uagents_core.contrib.protocols.chat import MetadataContent
from uagents_core.contrib.protocols.chat.cards import (
    BadgeNode,
    ButtonAction,
    ButtonNode,
    CtaAction,
    CustomCardPayload,
    DividerNode,
    GroupNode,
    HeadingNode,
    ListItem,
    ListNode,
    ReviewCardPayload,
    ReviewSummaryRow,
    SectionNode,
    TextNode,
    create_card_content,
)

from services.integration_advisor import IntegrationRequirement


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


def workflow_result_card(
    text: str,
    *,
    activity: Sequence[str] = (),
    integrations: Sequence[IntegrationRequirement] = (),
    execution_results: Sequence[dict[str, Any]] = (),
    session_id: str | None = None,
) -> MetadataContent:
    """Build a compact result dashboard with evidence and next actions.

    The complete narrative remains in TextContent as an accessibility/fallback
    path. This card deliberately summarizes rather than repeating that answer.
    """

    failed = sum(
        str(result.get("status", "")).casefold()
        in {"failed", "blocked", "blocked_by_consent"}
        for result in execution_results
    )
    status = "Attention needed" if failed else "Completed"
    variant = "warning" if failed else "success"
    children: list[Any] = [
        GroupNode(
            type="group",
            direction="row",
            gap=8,
            children=[
                BadgeNode(type="badge", label=status, variant=variant),
                BadgeNode(type="badge", label="Auditable", variant="info"),
            ],
        )
    ]

    summary = _first_summary_line(text)
    if summary:
        children.append(TextNode(type="text", value=summary, style="body"))

    chart = _markdown_table_chart(text)
    if chart:
        children.extend([
            DividerNode(type="divider"),
            HeadingNode(type="heading", value=chart[0], level=3),
            *[TextNode(type="text", value=line, style="body") for line in chart[1:]],
        ])

    trace = list(dict.fromkeys(item.strip() for item in activity if item.strip()))[-6:]
    if not trace:
        trace = [
            "Supervisor interpreted the objective and selected bounded specialists.",
            "Deterministic specialists returned grounded dataset results.",
            "Safety and presentation checks completed before this response.",
        ]
    children.extend([
        DividerNode(type="divider"),
        HeadingNode(type="heading", value="Agent activity", level=3),
        ListNode(
            type="list",
            items=[
                ListItem(children=[TextNode(type="text", value=item[:500], style="body")])
                for item in trace
            ],
        ),
    ])

    if integrations:
        children.extend([
            DividerNode(type="divider"),
            HeadingNode(type="heading", value="Integration readiness", level=3),
        ])
        for item in integrations:
            ready_label = "Ready" if item.ready else "Setup needed"
            children.append(
                GroupNode(
                    type="group",
                    direction="row",
                    gap=8,
                    children=[
                        BadgeNode(
                            type="badge",
                            label=f"{item.label}: {ready_label}",
                            variant="success" if item.ready else "warning",
                        ),
                        TextNode(type="text", value=item.purpose[:240], style="muted"),
                    ],
                )
            )

    if execution_results:
        children.extend([
            DividerNode(type="divider"),
            HeadingNode(type="heading", value="Execution receipts", level=3),
            ListNode(
                type="list",
                items=[
                    ListItem(
                        children=[
                            TextNode(
                                type="text",
                                value=_receipt_summary(result),
                                style="body",
                            )
                        ]
                    )
                    for result in execution_results[:8]
                ],
            ),
        ])

    context = {"session_id": session_id} if session_id else {}
    children.extend([
        DividerNode(type="divider"),
        GroupNode(
            type="group",
            direction="row",
            gap=8,
            children=[
                ButtonNode(
                    type="button",
                    label="Generate PDF",
                    primary=True,
                    action=ButtonAction(
                        selection={"action": "generate_pdf_report", **context}
                    ),
                ),
                ButtonNode(
                    type="button",
                    label="Save to Sheets",
                    action=ButtonAction(
                        selection={"action": "save_to_google_sheets", **context}
                    ),
                ),
                ButtonNode(
                    type="button",
                    label="Schedule review",
                    action=ButtonAction(
                        selection={"action": "schedule_review", **context}
                    ),
                ),
            ],
        ),
    ])
    payload = CustomCardPayload(
        root=SectionNode(
            type="section",
            title="CareFlow operations result",
            subtitle="Grounded result, execution trace, and safe next actions",
            children=children,
        )
    )
    return create_card_content(
        payload,
        card_id=uuid4(),
        preferred_drawer_width_px=720,
    )


def _first_summary_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip().strip("#*")
        if stripped and not stripped.startswith("|") and len(stripped) > 12:
            return stripped[:500]
    return ""


def _markdown_table_chart(text: str) -> list[str]:
    """Convert the first numeric Markdown table into a small text bar chart."""

    lines = [line.strip() for line in text.splitlines()]
    for index in range(len(lines) - 2):
        if not lines[index].startswith("|") or not lines[index + 1].startswith("|"):
            continue
        separator = lines[index + 1].replace("|", "").replace(":", "").replace("-", "").strip()
        if separator:
            continue
        headers = _table_cells(lines[index])
        rows: list[list[str]] = []
        for line in lines[index + 2:]:
            if not line.startswith("|"):
                break
            cells = _table_cells(line)
            if len(cells) == len(headers):
                rows.append(cells)
        if not rows or len(headers) < 2:
            continue
        numeric_columns: list[tuple[int, list[float]]] = []
        for column in range(1, len(headers)):
            values = [_number(cell) for cell in (row[column] for row in rows[:8])]
            if all(value is not None for value in values):
                numeric_columns.append((column, [float(value) for value in values]))
        if not numeric_columns:
            continue
        preferred = next(
            (
                item
                for item in numeric_columns
                if any(word in headers[item[0]].casefold() for word in ("total", "amount", "billing"))
            ),
            numeric_columns[0],
        )
        column, values = preferred
        maximum = max(values) or 1.0
        rendered = [f"{headers[column]} by {headers[0]}"]
        for row, value in zip(rows[:5], values[:5]):
            width = max(1, round((value / maximum) * 12))
            rendered.append(f"{row[0][:28]}  {'█' * width}  {row[column]}")
        return rendered
    return []


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _number(value: str) -> float | None:
    cleaned = re.sub(r"[^0-9.\-]", "", value)
    if not cleaned or cleaned in {"-", ".", "-."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _receipt_summary(result: dict[str, Any]) -> str:
    status = str(result.get("status", "unknown")).replace("_", " ")
    action = str(result.get("action") or result.get("reason") or "workspace action")
    identifier = result.get("message_id") or result.get("event_id") or result.get("worksheet")
    suffix = f" · receipt {identifier}" if identifier else ""
    return f"{action}: {status}{suffix}"[:500]
