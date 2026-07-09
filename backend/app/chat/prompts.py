from dataclasses import dataclass

from app.retrieval.search import RetrievedChunk

CHAT_SYSTEM_PROMPT = """\
You are an assistant for product and project managers, answering questions about
their connected project documentation.

Answer the question using only the numbered context entries below. Refer to the
entries you use by their number in brackets, like [1]. If the context does not
contain enough information to answer, say so instead of guessing.

A "Known facts" section, if present, lists current values stated by the user for
specific subjects. These override any numbered context entry that gives a different
value for the same subject, for any question about that subject, including plain
factual questions, not only ones that mention a change or correction. When a Known
fact applies, answer using its value and do not present the conflicting context
value as current.

Respond in the same language as the user's question.\
"""

QUERY_REWRITE_SYSTEM_PROMPT = """\
Rewrite the user's latest message as a standalone search query for retrieving relevant
documents, using the conversation history to resolve references like "this project" or
"it". Output only the rewritten query, with no extra commentary.\
"""

TITLE_SYSTEM_PROMPT = """\
Write a short title, six words or fewer, summarizing the exchange below, in the same
language as the user's message. Output only the title, with no quotes, no surrounding
punctuation, and no extra commentary.\
"""

FACT_UPDATE_SYSTEM_PROMPT = """\
Decide whether the user's latest message states a new or changed fact worth remembering
about a project, person, team, or topic, for example a changed SLA, a new owner, or a
decision that was made. Use the conversation history only to resolve what the latest
message refers to (for example "it" or "this project") — never as a source for the value
itself.

If the latest message is a question, or does not assert any new or changed information,
set "should_record" to false and leave the other fields empty.

If it does assert a fact worth remembering, set "should_record" to true and describe the
fact as a (subject, predicate, object or value) triple: "subject" is the name of the
project, person, team, or topic the fact is about; "predicate" is a short label for the
kind of fact (for example "owner", "status", "value"); "object" is the name of another
entity if the fact relates the subject to one, otherwise leave it empty; "value" is a
plain text value if the fact is not a relation to another entity, otherwise leave it
empty. "project" is the name of the project the subject belongs to, if known, otherwise
leave it empty.

The value you record must be the one stated in the latest message itself, even when it
contradicts or corrects a value mentioned earlier in the conversation history (that is
precisely what a correction looks like). Never record a value merely because it appeared
earlier in the conversation history.

Output only JSON matching the given schema, with no extra commentary.\
"""


@dataclass
class HistoryTurn:
    """One prior turn of a conversation, for prompt construction."""

    role: str
    content: str


def build_query_rewrite_prompt(history: list[HistoryTurn], message: str) -> str:
    parts = [f"{turn.role.capitalize()}: {turn.content}" for turn in history]
    parts.append(f"Latest message: {message}")
    return "\n\n".join(parts)


def build_fact_update_prompt(history: list[HistoryTurn], message: str) -> str:
    parts = [f"{turn.role.capitalize()}: {turn.content}" for turn in history]
    parts.append(f"Latest message: {message}")
    return "\n\n".join(parts)


def build_title_prompt(message: str, answer: str) -> str:
    return f"User: {message}\n\nAssistant: {answer}"


def build_chat_prompt(
    message: str,
    context: list[RetrievedChunk],
    history: list[HistoryTurn],
    known_facts: str | None = None,
) -> str:
    parts = []
    if history:
        parts.append(
            "Conversation so far:\n" + "\n".join(f"{turn.role.capitalize()}: {turn.content}" for turn in history)
        )
    for index, chunk in enumerate(context, start=1):
        location = f"attached file: {chunk.document_path}" if chunk.is_attachment else chunk.document_path
        if chunk.section:
            location += f", section: {chunk.section}"
        parts.append(f"[{index}] ({location})\n{chunk.content}")
    if known_facts is not None:
        parts.append(known_facts)
    parts.append(f"Question: {message}")
    return "\n\n".join(parts)
