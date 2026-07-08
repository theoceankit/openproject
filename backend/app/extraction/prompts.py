import json

EXTRACTION_SYSTEM_PROMPT = """\
You are an information extraction assistant for a project management tool.
Given the text of a project document, extract structured information about
the project it describes. Respond only with JSON matching the given schema.

Guidelines:
- "project": the single project this document is about. Give it a short name
  and a 1-3 sentence description based on the document.
- "people": people mentioned by name, with their role if stated.
- "terms": project-specific terms that the document defines or explains,
  with their definition. Do not invent terms that are not defined.
- "teams": named groups of people, with the names of their members (members
  must also appear in "people").
- "relations": other relationships described in the document, as short
  (subject, relation, object) triples, for example ("Storefront", "depends
  on", "Checkout") or ("Alice", "owns", "Storefront"). Use the same names as
  used elsewhere in your output where applicable.

If something is not mentioned, return an empty list or empty string. Do not
fabricate information that is not in the document.\
"""

RESOLUTION_SYSTEM_PROMPT = """\
You resolve whether a newly extracted project refers to the same project as
one of a list of already-known projects, is a new project, or is ambiguous
between several known projects. Respond only with JSON matching the given
schema.

- "match": the candidate clearly refers to one existing project. Set
  "project_id" to that project's id.
- "new": the candidate clearly does not refer to any existing project.
- "ambiguous": the candidate could plausibly refer to more than one existing
  project, and you cannot tell which. Set "candidate_ids" to those projects'
  ids.

Compare based on name and description. Prefer "new" unless there is a clear
match.\
"""


def build_extraction_prompt(document_path: str, sections: list[tuple[str | None, str]]) -> str:
    parts = [f"Document: {document_path}", ""]
    for section, content in sections:
        if section:
            parts.append(f"## {section}")
        parts.append(content)
        parts.append("")
    return "\n".join(parts)


def build_resolution_prompt(candidate: dict, existing_projects: list[dict]) -> str:
    payload = {"candidate": candidate, "existing_projects": existing_projects}
    return json.dumps(payload, ensure_ascii=False, indent=2)
