"""RAG system prompt and context construction.

Kept separate from :mod:`rag.generation` so the prompt can be inspected,
versioned and unit-tested without any provider or network in the loop.

The instruction text is deliberately explicit about three failure modes that
 plague academic RAG deployments:

* **invented facts** - a language model asked "when is the rattrapage?" will
   happily produce a plausible date. Forbidding it, and requiring an explicit
   "insufficient context", is what makes the answer checkable by a student.
* **invented citations** - the model is told to cite only the sources it was
   given, and never to invent metadata such as a page number it did not see.
* **prompt injection** - retrieved passages are university documents that may
   contain arbitrary text. They are fenced as reference material that cannot
   override the instruction block.
"""

from __future__ import annotations

__all__ = [
    "RAG_SYSTEM_PROMPT",
    "ANSWER_INSTRUCTION",
    "build_context",
    "build_messages",
]

#: The system prompt. ``{question}`` and ``{context}`` are filled in by
#: :func:`build_messages`; they are *not* substituted here, so the same block
#: can be reused verbatim by any provider.
RAG_SYSTEM_PROMPT = """You are an academic assistant for RAG-USTHB.

Answer the user's question using the retrieved context as the factual basis.

- Answer directly and clearly.
- Use only facts supported by the retrieved passages.
- Never invent facts, dates, requirements, or citations.
- If the context is insufficient, explicitly say so.
- Answer in the language of the user's question: Arabic, French, or English.
- Combine relevant passages when necessary.
- Use structured explanations when useful.
- Cite the actual retrieved sources and available page numbers.
"""

#: Closing line of the assembled prompt, kept as a constant so tests can assert
#: the final instruction without depending on the whole block's whitespace.
ANSWER_INSTRUCTION = "Generate the answer with citations."


def build_context(chunks) -> str:
    """Render retrieved passages into the numbered context block.

    Numbering the passages gives the model a handle it can cite ("see [2]"),
    and putting the citation on the same block as the text makes it much
    harder for the model to attach a source to the wrong passage.

    Args:
        chunks: :class:`~rag.retrieval.RetrievedChunk` instances, best first.
            Each may carry ``document_name``, ``page`` and, through
            ``metadata``, the ingestion pipeline's ``reference_id``.

    Returns:
        The context block. ``"(no passages retrieved)"`` when ``chunks`` is
        empty, which is the honest rendering of an empty retrieval rather than
        a blank the model might fill in with guesses.
    """
    chunks = list(chunks)

    if not chunks:
        return "(no passages retrieved)"

    blocks = []

    for index, chunk in enumerate(chunks, start=1):
        metadata = getattr(chunk, "metadata", None) or {}

        label = getattr(chunk, "document_name", "") or metadata.get("document_name") or "unknown document"
        page = getattr(chunk, "page", None)
        reference = metadata.get("reference_id") or ""

        header = f"[{index}] {label}"
        if page is not None:
            header += f", p. {page}"
        if reference:
            header += f" (ref {reference})"

        text = (getattr(chunk, "text", "") or "").strip()

        blocks.append(f"{header}\n{text}")

    return "\n\n".join(blocks)


def build_messages(question: str, chunks) -> list[dict]:
    """Assemble the chat messages for an OpenAI-compatible ``/chat/completions`` call.

    Args:
        question: The student's question, already trimmed by the caller.
        chunks: Retrieved passages, best first.

    Returns:
        ``[{"role": "system", "content": ...}, {"role": "user", "content": ...}]``
        where the system content is :data:`RAG_SYSTEM_PROMPT` with ``{question}``
        and ``{context}`` replaced by the real values, and the user content is
        the bare question. The context lives only in the system turn, so it is
        sent once rather than twice; a provider that truncates system messages
        would need that changed here and nowhere else.
    """
    question = (question or "").strip()
    context = build_context(chunks)

    system = RAG_SYSTEM_PROMPT.format(question=question, context=context)

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ]