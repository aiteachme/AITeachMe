"""Compatibility wrapper exposing interact chat prompts."""

from app.workflows.interact.prompts import build_chat_messages, get_execution_instruction

__all__ = ["build_chat_messages", "get_execution_instruction"]
