import json

from app.extraction.prompts import build_extraction_prompt, build_resolution_prompt
from app.extraction.schemas import ExtractionResult, FactUpdateResult, ProjectResolutionResult


def test_extraction_result_round_trips_through_json():
    payload = {
        "project": {"name": "Storefront", "description": "Online shop"},
        "people": [{"name": "Alice", "role": "Lead"}],
        "terms": [{"term": "SKU", "definition": "Stock Keeping Unit"}],
        "teams": [{"name": "Core Team", "members": ["Alice"]}],
        "relations": [{"subject": "Alice", "relation": "owns", "object": "Storefront"}],
    }

    result = ExtractionResult.model_validate_json(json.dumps(payload))

    assert result.project.name == "Storefront"
    assert result.people[0].role == "Lead"
    assert result.teams[0].members == ["Alice"]
    assert result.relations[0].relation == "owns"


def test_extraction_result_defaults_to_empty_lists():
    result = ExtractionResult.model_validate({"project": {"name": "Storefront"}})

    assert result.project.description == ""
    assert result.people == []
    assert result.terms == []
    assert result.teams == []
    assert result.relations == []


def test_project_resolution_result_outcomes():
    match = ProjectResolutionResult.model_validate({"outcome": "match", "project_id": "abc"})
    new = ProjectResolutionResult.model_validate({"outcome": "new"})
    ambiguous = ProjectResolutionResult.model_validate({"outcome": "ambiguous", "candidate_ids": ["a", "b"]})

    assert match.project_id == "abc"
    assert new.candidate_ids == []
    assert ambiguous.candidate_ids == ["a", "b"]


def test_build_extraction_prompt_includes_path_and_sections():
    prompt = build_extraction_prompt("docs/overview.md", [("Intro", "Hello"), (None, "World")])

    assert "Document: docs/overview.md" in prompt
    assert "## Intro" in prompt
    assert "Hello" in prompt
    assert "World" in prompt


def test_build_resolution_prompt_includes_candidate_and_existing_projects():
    candidate = {"name": "Storefront", "description": "Online shop"}
    existing = [{"id": "1", "name": "Storefront API", "description": "Backend service"}]

    prompt = build_resolution_prompt(candidate, existing)

    assert "Storefront" in prompt
    assert "Storefront API" in prompt


def test_fact_update_result_round_trips_through_json():
    payload = {
        "should_record": True,
        "project": "Storefront Redesign",
        "subject": "Storefront Redesign SLA",
        "predicate": "value",
        "object": "",
        "value": "80%",
    }

    result = FactUpdateResult.model_validate_json(json.dumps(payload))

    assert result.should_record is True
    assert result.project == "Storefront Redesign"
    assert result.subject == "Storefront Redesign SLA"
    assert result.predicate == "value"
    assert result.object == ""
    assert result.value == "80%"


def test_fact_update_result_minimal_defaults_to_empty_strings():
    result = FactUpdateResult.model_validate_json(json.dumps({"should_record": False}))

    assert result.should_record is False
    assert result.project == ""
    assert result.subject == ""
    assert result.predicate == ""
    assert result.object == ""
    assert result.value == ""
