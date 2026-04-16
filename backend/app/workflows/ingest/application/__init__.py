"""Canonical ingest application entrypoints with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "IngestFileClassifiedEvent",
    "IngestFileEnhanceFailedEvent",
    "IngestFileEnhanceStartedEvent",
    "IngestFileFastParsedEvent",
    "IngestFileParseFailedEvent",
    "IngestFileParsedEvent",
    "IngestFileReadyForDigestEvent",
    "IngestParseRequestedEvent",
    "WORKFLOW_EXPORTS",
    "_run_deep_enhance_background",
    "create_parse_file_initial_state",
    "recover_stalled_enhancements",
    "run_parse_file_workflow",
]

_ATTR_TO_MODULE = {
    "IngestFileClassifiedEvent": "app.workflows.ingest.application.events",
    "IngestFileEnhanceFailedEvent": "app.workflows.ingest.application.events",
    "IngestFileEnhanceStartedEvent": "app.workflows.ingest.application.events",
    "IngestFileFastParsedEvent": "app.workflows.ingest.application.events",
    "IngestFileParseFailedEvent": "app.workflows.ingest.application.events",
    "IngestFileParsedEvent": "app.workflows.ingest.application.events",
    "IngestFileReadyForDigestEvent": "app.workflows.ingest.application.events",
    "IngestParseRequestedEvent": "app.workflows.ingest.application.events",
    "WORKFLOW_EXPORTS": "app.workflows.ingest.application.exports",
    "_run_deep_enhance_background": "app.workflows.ingest.application.parse_files",
    "create_parse_file_initial_state": "app.workflows.ingest.application.parse_files",
    "recover_stalled_enhancements": "app.workflows.ingest.application.recovery",
    "run_parse_file_workflow": "app.workflows.ingest.application.parse_files",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
