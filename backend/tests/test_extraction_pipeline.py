from sqlalchemy import select

from app.db.models import Chunk, Document, Person, Relation, Team, Term, Topic
from app.extraction.pipeline import _truncate_sections, extract_document
from app.extraction.schemas import ExtractionResult


class FakeProvider:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def generate(self, prompt, *, system=None, format=None, call_site=None):
        self.calls.append({"prompt": prompt, "system": system, "format": format, "call_site": call_site})
        return self._responses.pop(0)

    async def embed(self, texts, *, call_site=None):
        return [[0.0, 0.0] for _ in texts]


EXTRACTION_RESPONSE = ExtractionResult.model_validate(
    {
        "project": {"name": "Storefront", "description": "Online shop"},
        "people": [{"name": "Alice", "role": "Lead"}],
        "terms": [{"term": "SKU", "definition": "Stock Keeping Unit"}],
        "teams": [{"name": "Core Team", "members": ["Alice"]}],
        "relations": [{"subject": "Alice", "relation": "owns", "object": "Storefront"}],
    }
).model_dump_json()


async def make_document(db_session, content: str = "Alice leads the Core Team on Storefront.") -> Document:
    document = Document(path="/docs/storefront.md", doc_type="markdown", content_hash="abc123")
    db_session.add(document)
    await db_session.flush()
    db_session.add(Chunk(document_id=document.id, chunk_index=0, content=content, section="Overview"))
    await db_session.flush()
    return document


async def test_extract_document_persists_entities_for_new_project(db_session):
    document = await make_document(db_session)
    provider = FakeProvider(responses=[EXTRACTION_RESPONSE])

    outcome = await extract_document(db_session, provider, document)

    assert outcome.project_resolution == "new"
    assert document.project_id == outcome.project_id

    team = (await db_session.execute(select(Team).where(Team.document_id == document.id))).scalar_one()
    assert team.name == "Core Team"
    assert team.project_id == outcome.project_id

    person = (await db_session.execute(select(Person).where(Person.document_id == document.id))).scalar_one()
    assert person.name == "Alice"
    assert person.role == "Lead"
    assert person.team_id == team.id
    assert person.project_id == outcome.project_id

    term = (await db_session.execute(select(Term).where(Term.document_id == document.id))).scalar_one()
    assert term.term == "SKU"
    assert term.definition == "Stock Keeping Unit"

    relation = (await db_session.execute(select(Relation).where(Relation.document_id == document.id))).scalar_one()
    assert relation.subject_type == "person"
    assert relation.subject_id == person.id
    assert relation.relation_label == "owns"
    assert relation.object_type == "project"
    assert relation.object_id == outcome.project_id

    assert (await db_session.execute(select(Topic).where(Topic.document_id == document.id))).scalars().all() == []


async def test_extract_document_replaces_prior_extraction_on_reingest(db_session):
    document = await make_document(db_session)
    provider = FakeProvider(responses=[EXTRACTION_RESPONSE])
    first_outcome = await extract_document(db_session, provider, document)

    second_response = ExtractionResult.model_validate(
        {
            "project": {"name": "Storefront", "description": "Online shop"},
            "people": [{"name": "Bob", "role": "Engineer"}],
            "terms": [],
            "teams": [],
            "relations": [],
        }
    ).model_dump_json()
    provider = FakeProvider(responses=[second_response])

    second_outcome = await extract_document(db_session, provider, document)

    assert second_outcome.project_id == first_outcome.project_id
    assert second_outcome.project_resolution == "match"
    assert [call["call_site"] for call in provider.calls] == ["extraction"]

    people = (await db_session.execute(select(Person).where(Person.document_id == document.id))).scalars().all()
    assert [p.name for p in people] == ["Bob"]

    teams = (await db_session.execute(select(Team).where(Team.document_id == document.id))).scalars().all()
    assert teams == []

    terms = (await db_session.execute(select(Term).where(Term.document_id == document.id))).scalars().all()
    assert terms == []


def test_truncate_sections_keeps_order_and_truncates_last():
    sections = [("A", "12345"), ("B", "678901234"), ("C", "ignored")]

    result = _truncate_sections(sections, max_chars=10)

    assert result == [("A", "12345"), ("B", "67890")]


def test_truncate_sections_keeps_everything_under_limit():
    sections = [("A", "short"), ("B", "also short")]

    result = _truncate_sections(sections, max_chars=1000)

    assert result == sections
