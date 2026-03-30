"""Raw file model definition."""

from __future__ import annotations

import json
from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.enums import IngestStatus, TaskStatus
from app.utils.time import utcnow


class RawFile(SQLModel, table=True):
    """User-uploaded source material."""

    __tablename__ = "raw_file"

    id: int | None = Field(default=None, primary_key=True)
    uid: str = Field(index=True, unique=True)
    subject: str = Field(index=True)
    filename: str
    filetype: str
    file_path: str
    mime_type: str | None = None
    storage_backend: str = Field(default="local")
    markdown_path: str | None = None
    markdown_content: str = ""
    asset_dir: str | None = None
    storage_uri: str | None = None
    markdown_uri: str | None = None
    asset_manifest_json: str = Field(default="[]")
    user_note: str | None = None
    status: str = Field(default=TaskStatus.PENDING.value, index=True)
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    content_hash: str | None = Field(default=None)
    file_size_bytes: int | None = Field(default=None)
    estimated_pages: int | None = Field(default=None)
    detected_language: str | None = Field(default=None)
    detected_discipline: str | None = Field(default=None, index=True)
    detected_sub_discipline: str | None = Field(default=None)
    detected_content_type: str | None = Field(default=None)
    classification_result: str | None = Field(default=None)
    quality_score: float | None = Field(default=None)
    parse_metadata: str | None = Field(default=None)
    material_profile_json: str = Field(default="{}")
    parse_metadata_json: str = Field(default="{}")
    image_count: int | None = Field(default=None)
    ingest_status: str = Field(default=IngestStatus.PENDING.value, index=True)
    current_step: str | None = Field(default=None, index=True)

    @property
    def original_filename(self) -> str:
        return self.filename

    @original_filename.setter
    def original_filename(self, value: str) -> None:
        self.filename = value

    @property
    def file_ext(self) -> str:
        return f".{self.filetype}" if self.filetype and not self.filetype.startswith(".") else self.filetype

    @file_ext.setter
    def file_ext(self, value: str) -> None:
        self.filetype = value.lstrip(".")

    @property
    def storage_key(self) -> str:
        from app.utils.path_helpers import to_storage_key

        return to_storage_key(self.file_path)

    @storage_key.setter
    def storage_key(self, value: str) -> None:
        from app.utils.path_helpers import resolve_storage_key_path

        self.file_path = str(resolve_storage_key_path(value))

    @property
    def parsed_markdown(self) -> str:
        return self.markdown_content

    @parsed_markdown.setter
    def parsed_markdown(self, value: str) -> None:
        self.markdown_content = value

    @property
    def parse_error_message(self) -> str | None:
        return self.error_message

    @parse_error_message.setter
    def parse_error_message(self, value: str | None) -> None:
        self.error_message = value

    @property
    def classification_json(self) -> str:
        return self.classification_result or "{}"

    @classification_json.setter
    def classification_json(self, value: str) -> None:
        self.classification_result = value

    @property
    def parser_used(self) -> str | None:
        payloads = [self.parse_metadata_json, self.parse_metadata]
        for payload in payloads:
            if not payload:
                continue
            try:
                decoded = json.loads(payload)
            except json.JSONDecodeError:
                continue
            parser_used = decoded.get("parser_used")
            if parser_used:
                return str(parser_used)
        return None

    @parser_used.setter
    def parser_used(self, value: str | None) -> None:
        try:
            decoded = json.loads(self.parse_metadata_json or "{}")
        except json.JSONDecodeError:
            decoded = {}
        if value:
            decoded["parser_used"] = value
        else:
            decoded.pop("parser_used", None)
        self.parse_metadata_json = json.dumps(decoded, ensure_ascii=False)

    @property
    def digest_current_step(self) -> str | None:
        return self.current_step

    @digest_current_step.setter
    def digest_current_step(self, value: str | None) -> None:
        self.current_step = value

    @property
    def size_bytes(self) -> int | None:
        return self.file_size_bytes

    @size_bytes.setter
    def size_bytes(self, value: int | None) -> None:
        self.file_size_bytes = value

    @property
    def checksum_sha256(self) -> str | None:
        return self.content_hash

    @checksum_sha256.setter
    def checksum_sha256(self, value: str | None) -> None:
        self.content_hash = value


class RawFileAsset(SQLModel):
    """Compatibility asset descriptor derived from the filesystem, not a DB table."""

    id: int | None = None
    raw_file_id: int
    asset_name: str
    asset_kind: str = "image"
    storage_backend: str = "local"
    storage_key: str
    mime_type: str | None = None
    page_num: int | None = None
    width: int | None = None
    height: int | None = None
    ocr_text: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
