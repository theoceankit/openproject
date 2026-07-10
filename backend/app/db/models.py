import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Project(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Top-level container other Stage 1 entities are organized under."""

    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class Document(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A connected source document (markdown file or PDF)."""

    __tablename__ = "documents"

    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True, nullable=True)
    path: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    doc_type: Mapped[str] = mapped_column(String, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    origin: Mapped[str] = mapped_column(String, nullable=False, default="ingested", server_default="ingested")
    stored_path: Mapped[str | None] = mapped_column(String, nullable=True)


class Chunk(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Raw layer: a retrievable piece of a document, with its embedding."""

    __tablename__ = "chunks"
    __table_args__ = (
        Index(
            "ix_chunks_embedding_hnsw_cosine",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    section: Mapped[str | None] = mapped_column(String, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.embedding_dim), nullable=True)


class Term(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A project-specific term and its definition."""

    __tablename__ = "terms"

    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True, nullable=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True, nullable=False)
    source_section: Mapped[str | None] = mapped_column(String, nullable=True)
    term: Mapped[str] = mapped_column(String, nullable=False)
    definition: Mapped[str] = mapped_column(Text, nullable=False)


class Team(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A named group of people."""

    __tablename__ = "teams"

    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True, nullable=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True, nullable=False)
    source_section: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)


class Person(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A person, with name and role, optionally a member of a Team."""

    __tablename__ = "people"

    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True, nullable=True)
    team_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teams.id"), index=True, nullable=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True, nullable=False)
    source_section: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str | None] = mapped_column(String, nullable=True)


class Topic(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A lightweight, unstructured concept that generic relations can point at."""

    __tablename__ = "topics"

    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True, nullable=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"), index=True, nullable=True)
    source_section: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProjectResolution(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An ambiguous Project match for a document, awaiting user confirmation."""

    __tablename__ = "project_resolutions"

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True, nullable=False)
    candidate_name: Mapped[str] = mapped_column(String, nullable=False)
    candidate_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    candidate_project_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    resolved_project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id"), index=True, nullable=True
    )


class Conversation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A chat session: an ordered sequence of user and assistant messages."""

    __tablename__ = "conversations"

    title: Mapped[str | None] = mapped_column(String, nullable=True)


class Message(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A single turn in a Conversation."""

    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list | None] = mapped_column(JSONB, nullable=True)


class ConversationAttachment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A file attached to a message in a Conversation, staged as one-off context (origin="attachment")."""

    __tablename__ = "conversation_attachments"

    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), index=True, nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True, nullable=False)


class Relation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A generic (subject, relation_label, object) triple between any two entities."""

    __tablename__ = "relations"

    subject_type: Mapped[str] = mapped_column(String, nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    relation_label: Mapped[str] = mapped_column(String, nullable=False)
    object_type: Mapped[str] = mapped_column(String, nullable=False)
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True, nullable=False)
    source_section: Mapped[str | None] = mapped_column(String, nullable=True)


class ModelSettings(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Singleton row holding the user's model selection (default plus per-task overrides).

    A null override means "use default_model"; there is intentionally no embeddings override
    here yet, changing the embedding model would desync it from already-embedded Chunk vectors
    (see app/model_settings/service.py).
    """

    __tablename__ = "model_settings"

    default_model: Mapped[str] = mapped_column(String, nullable=False)
    chat_model: Mapped[str | None] = mapped_column(String, nullable=True)
    extraction_model: Mapped[str | None] = mapped_column(String, nullable=True)
    orchestration_model: Mapped[str | None] = mapped_column(String, nullable=True)


class ModelCall(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A single completed generate()/embed() call, recorded for the Statistics settings panel.

    Written best-effort by the provider layer itself (see app/providers/usage.py); a failed
    write must never break the generate()/embed() call it would have recorded.
    """

    __tablename__ = "model_calls"

    operation: Mapped[str] = mapped_column(String, nullable=False)
    call_site: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str] = mapped_column(String, nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Fact(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An assertion about a subject, stated by the user in chat (or another future source)."""

    __tablename__ = "facts"

    subject_type: Mapped[str] = mapped_column(String, nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    predicate: Mapped[str] = mapped_column(String, nullable=False)
    object_type: Mapped[str | None] = mapped_column(String, nullable=True)
    object_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True, nullable=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
