"""Shared Agent Chat Protocol wrapper for specialist services."""

from __future__ import annotations

import inspect
import json
from typing import Any, Callable

from config import agent_runtime_kwargs


def parse_payload(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text.strip()


def build_text_uagent(name: str, handler: Callable[[Any], Any], *, slot: int):
    """Create a manifest-publishing uAgent around a sync or async handler."""
    from uagents import Agent, Context, Protocol
    from uagents_core.contrib.protocols.chat import (
        ChatAcknowledgement,
        ChatMessage,
        TextContent,
        chat_protocol_spec,
    )

    agent = Agent(**agent_runtime_kwargs(name, slot))
    protocol = Protocol(spec=chat_protocol_spec)

    @protocol.on_message(model=ChatAcknowledgement)
    async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        ctx.logger.debug(
            "Acknowledgement from %s for %s", sender, msg.acknowledged_msg_id
        )

    @protocol.on_message(model=ChatMessage)
    async def handle(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
        try:
            result = handler(parse_payload(msg.text()))
            if inspect.isawaitable(result):
                result = await result
            response = result if isinstance(result, str) else json.dumps(result, default=str)
        except Exception as exc:  # Keep protocol errors structured and observable.
            ctx.logger.exception("Agent request failed")
            response = json.dumps({"status": "error", "error": str(exc)})
        await ctx.send(sender, ChatMessage(content=[TextContent(text=response)]))

    agent.include(protocol, publish_manifest=True)
    return agent

