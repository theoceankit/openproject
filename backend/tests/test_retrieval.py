from app.core.config import settings
from app.db.models import Chunk, Conversation, ConversationAttachment, Document, Project
from app.retrieval.search import search_attachment_chunks, search_chunks


def make_vector(*nonzero: tuple[int, float]) -> list[float]:
    """A vector of settings.embedding_dim with the given (index, value) entries set."""
    vector = [0.0] * settings.embedding_dim
    for index, value in nonzero:
        vector[index] = value
    return vector


class FakeProvider:
    def __init__(self, query_embedding: list[float]):
        self._query_embedding = query_embedding

    async def generate(self, prompt, *, system=None, format=None, model=None, call_site=None):
        raise NotImplementedError

    async def embed(self, texts, *, call_site=None):
        return [self._query_embedding for _ in texts]


async def make_document(db_session, path: str) -> Document:
    document = Document(path=path, doc_type="markdown", content_hash="abc123")
    db_session.add(document)
    await db_session.flush()
    return document


async def test_search_chunks_orders_by_embedding_similarity(db_session):
    document = await make_document(db_session, "/docs/storefront.md")
    db_session.add_all(
        [
            Chunk(
                document_id=document.id,
                chunk_index=0,
                content="About the Core Team",
                section="Team",
                embedding=make_vector((0, 1.0)),
            ),
            Chunk(
                document_id=document.id,
                chunk_index=1,
                content="About the Cart and SKU terms",
                section="Terminology",
                embedding=make_vector((1, 1.0)),
            ),
        ]
    )
    await db_session.flush()

    provider = FakeProvider(query_embedding=make_vector((1, 1.0)))

    results = await search_chunks(db_session, provider, "What is a SKU?", limit=5)

    assert results[0].content == "About the Cart and SKU terms"
    assert results[0].section == "Terminology"
    assert results[0].document_path == "/docs/storefront.md"
    assert results[1].content == "About the Core Team"


async def test_search_chunks_includes_project_name_when_document_has_a_project(db_session):
    project = Project(name="Storefront Revamp")
    db_session.add(project)
    await db_session.flush()
    document = Document(
        path="/docs/storefront.md", doc_type="markdown", content_hash="abc123", project_id=project.id
    )
    db_session.add(document)
    await db_session.flush()
    db_session.add(
        Chunk(document_id=document.id, chunk_index=0, content="About the SKU", embedding=make_vector((0, 1.0)))
    )
    await db_session.flush()

    provider = FakeProvider(query_embedding=make_vector((0, 1.0)))

    [result] = await search_chunks(db_session, provider, "What is a SKU?", limit=5)

    assert result.project_name == "Storefront Revamp"


async def test_search_chunks_project_name_is_none_for_an_unscoped_document(db_session):
    document = await make_document(db_session, "/docs/storefront.md")
    db_session.add(
        Chunk(document_id=document.id, chunk_index=0, content="About the SKU", embedding=make_vector((0, 1.0)))
    )
    await db_session.flush()

    provider = FakeProvider(query_embedding=make_vector((0, 1.0)))

    [result] = await search_chunks(db_session, provider, "What is a SKU?", limit=5)

    assert result.project_name is None


async def test_search_chunks_respects_limit(db_session):
    document = await make_document(db_session, "/docs/storefront.md")
    db_session.add_all(
        [
            Chunk(document_id=document.id, chunk_index=i, content=f"chunk {i}", embedding=make_vector((i, 1.0)))
            for i in range(3)
        ]
    )
    await db_session.flush()

    provider = FakeProvider(query_embedding=make_vector((0, 1.0)))

    results = await search_chunks(db_session, provider, "query", limit=2)

    assert len(results) == 2


async def test_search_chunks_excludes_attachment_origin_documents(db_session):
    document = Document(path="/tmp/attached.md", doc_type="markdown", content_hash="abc123", origin="attachment")
    db_session.add(document)
    await db_session.flush()
    db_session.add(
        Chunk(document_id=document.id, chunk_index=0, content="About the SKU", embedding=make_vector((0, 1.0)))
    )
    await db_session.flush()

    provider = FakeProvider(query_embedding=make_vector((0, 1.0)))

    results = await search_chunks(db_session, provider, "What is a SKU?", limit=5)

    assert not any(r.document_path == "/tmp/attached.md" for r in results)


async def test_search_attachment_chunks_is_scoped_to_the_conversation(db_session):
    conversation = Conversation()
    other_conversation = Conversation()
    db_session.add_all([conversation, other_conversation])
    await db_session.flush()

    document = Document(path="/tmp/attached.md", doc_type="markdown", content_hash="abc123", origin="attachment")
    other_document = Document(path="/tmp/other.md", doc_type="markdown", content_hash="def456", origin="attachment")
    db_session.add_all([document, other_document])
    await db_session.flush()
    db_session.add_all(
        [
            Chunk(document_id=document.id, chunk_index=0, content="About the SKU", embedding=make_vector((0, 1.0))),
            Chunk(
                document_id=other_document.id, chunk_index=0, content="Unrelated", embedding=make_vector((0, 1.0))
            ),
        ]
    )
    db_session.add_all(
        [
            ConversationAttachment(conversation_id=conversation.id, document_id=document.id),
            ConversationAttachment(conversation_id=other_conversation.id, document_id=other_document.id),
        ]
    )
    await db_session.flush()

    provider = FakeProvider(query_embedding=make_vector((0, 1.0)))

    [result] = await search_attachment_chunks(db_session, provider, conversation.id, "What is a SKU?", limit=5)

    assert result.document_path == "/tmp/attached.md"
    assert result.is_attachment is True


# --- Document.stored_path / RetrievedChunk.document_id, stored_path (durable file storage) ---
#
# Document.stored_path does not exist on the model yet; these tests exercise the RetrievedChunk
# contract described in the technical spec: both search functions must carry the source
# document's real id and its stored_path (present or None) on every result.


async def test_search_chunks_populates_document_id_and_stored_path_when_set(db_session):
    document = Document(
        path="/docs/storefront.md",
        doc_type="markdown",
        content_hash="abc123",
        stored_path="/storage/some-id/storefront.md",
    )
    db_session.add(document)
    await db_session.flush()
    db_session.add(
        Chunk(document_id=document.id, chunk_index=0, content="About the SKU", embedding=make_vector((0, 1.0)))
    )
    await db_session.flush()

    provider = FakeProvider(query_embedding=make_vector((0, 1.0)))

    [result] = await search_chunks(db_session, provider, "What is a SKU?", limit=5)

    assert result.document_id == document.id
    assert result.stored_path == "/storage/some-id/storefront.md"


async def test_search_chunks_stored_path_is_none_when_document_has_none(db_session):
    document = await make_document(db_session, "/docs/storefront.md")
    db_session.add(
        Chunk(document_id=document.id, chunk_index=0, content="About the SKU", embedding=make_vector((0, 1.0)))
    )
    await db_session.flush()

    provider = FakeProvider(query_embedding=make_vector((0, 1.0)))

    [result] = await search_chunks(db_session, provider, "What is a SKU?", limit=5)

    assert result.document_id == document.id
    assert result.stored_path is None


async def test_search_attachment_chunks_populates_document_id_and_stored_path(db_session):
    conversation = Conversation()
    db_session.add(conversation)
    await db_session.flush()

    document = Document(
        path="/tmp/attached.md",
        doc_type="markdown",
        content_hash="abc123",
        origin="attachment",
        stored_path="/storage/other-id/attached.md",
    )
    db_session.add(document)
    await db_session.flush()
    db_session.add(
        Chunk(document_id=document.id, chunk_index=0, content="About the SKU", embedding=make_vector((0, 1.0)))
    )
    db_session.add(ConversationAttachment(conversation_id=conversation.id, document_id=document.id))
    await db_session.flush()

    provider = FakeProvider(query_embedding=make_vector((0, 1.0)))

    [result] = await search_attachment_chunks(db_session, provider, conversation.id, "What is a SKU?", limit=5)

    assert result.document_id == document.id
    assert result.stored_path == "/storage/other-id/attached.md"


async def test_search_attachment_chunks_stored_path_is_none_when_document_has_none(db_session):
    conversation = Conversation()
    db_session.add(conversation)
    await db_session.flush()

    document = Document(path="/tmp/attached.md", doc_type="markdown", content_hash="abc123", origin="attachment")
    db_session.add(document)
    await db_session.flush()
    db_session.add(
        Chunk(document_id=document.id, chunk_index=0, content="About the SKU", embedding=make_vector((0, 1.0)))
    )
    db_session.add(ConversationAttachment(conversation_id=conversation.id, document_id=document.id))
    await db_session.flush()

    provider = FakeProvider(query_embedding=make_vector((0, 1.0)))

    [result] = await search_attachment_chunks(db_session, provider, conversation.id, "What is a SKU?", limit=5)

    assert result.document_id == document.id
    assert result.stored_path is None
