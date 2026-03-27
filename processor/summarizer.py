"""
processor/summarizer.py — Generate summaries and manage the vector store
                           for semantic search over Oracle update records.
"""

import logging
import os
from typing import Optional

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import (
    EMBEDDINGS_MODEL, EMBEDDINGS_PROVIDER, LLM_PROVIDER,
    OLLAMA_BASE_URL, OLLAMA_MODEL, OPENAI_API_KEY, OPENAI_MODEL, VECTOR_DIR,
)

log = logging.getLogger(__name__)

# ── Embeddings ─────────────────────────────────────────────────────────────────

_embeddings = None


def get_embeddings():
    global _embeddings
    if _embeddings is not None:
        return _embeddings

    try:
        if EMBEDDINGS_PROVIDER == "openai" and OPENAI_API_KEY:
            from langchain_openai import OpenAIEmbeddings
            _embeddings = OpenAIEmbeddings(openai_api_key=OPENAI_API_KEY)
            log.info("Embeddings: OpenAI")
        else:
            # sentence-transformers is optional (not in core requirements)
            try:
                import sentence_transformers  # noqa: F401
            except ImportError:
                log.info("sentence-transformers not installed — semantic search disabled. "
                         "Install requirements-full.txt to enable it.")
                return None
            from langchain_community.embeddings import HuggingFaceEmbeddings
            _embeddings = HuggingFaceEmbeddings(
                model_name=EMBEDDINGS_MODEL,
                model_kwargs={"device": "cpu"},
                encode_kwargs={"normalize_embeddings": True},
            )
            log.info("Embeddings: HuggingFace %s (local)", EMBEDDINGS_MODEL)
    except Exception as exc:
        log.warning("Embeddings init failed: %s. Semantic search disabled.", exc)
        _embeddings = None

    return _embeddings


# ── Vector store ───────────────────────────────────────────────────────────────

_vectorstore = None


def get_vectorstore():
    global _vectorstore
    if _vectorstore is not None:
        return _vectorstore

    emb = get_embeddings()
    if emb is None:
        return None

    try:
        import chromadb
        from langchain_community.vectorstores import Chroma

        _vectorstore = Chroma(
            collection_name="oracle_updates",
            embedding_function=emb,
            persist_directory=str(VECTOR_DIR),
        )
        log.info("Vector store: Chroma at %s", VECTOR_DIR)
    except Exception as exc:
        log.warning("ChromaDB init failed: %s. Semantic search disabled.", exc)
        _vectorstore = None

    return _vectorstore


def add_to_vectorstore(record_id: int, title: str, content: str, metadata: dict) -> Optional[str]:
    """
    Embed and add a document to Chroma.  Returns the document ID.
    """
    vs = get_vectorstore()
    if vs is None:
        return None

    try:
        doc_id = f"update_{record_id}"
        text   = f"{title}\n\n{content}"
        vs.add_texts(
            texts=[text],
            ids=[doc_id],
            metadatas=[{
                "record_id":    str(record_id),
                "category":     metadata.get("category", ""),
                "service":      metadata.get("service", ""),
                "impact_level": metadata.get("impact_level", ""),
            }],
        )
        log.debug("Vectorised record %s", doc_id)
        return doc_id
    except Exception as exc:
        log.warning("Vectorisation failed for record %d: %s", record_id, exc)
        return None


def semantic_search(query: str, k: int = 8) -> list[dict]:
    """
    Perform semantic similarity search.
    Returns list of {record_id, score, snippet}.
    """
    vs = get_vectorstore()
    if vs is None:
        return []

    try:
        results = vs.similarity_search_with_score(query, k=k)
        out = []
        for doc, score in results:
            out.append({
                "record_id": int(doc.metadata.get("record_id", 0)),
                "score":     round(float(score), 4),
                "snippet":   doc.page_content[:300],
            })
        return out
    except Exception as exc:
        log.warning("Semantic search failed: %s", exc)
        return []


# ── Summary generation ─────────────────────────────────────────────────────────

def rule_based_summary(title: str, content: str) -> str:
    """
    Simple extractive summary — first 2 sentences of content.
    Always available without any LLM.
    """
    sentences = [s.strip() for s in content.split(".") if len(s.strip()) > 20]
    if not sentences:
        return content[:200]
    return ". ".join(sentences[:2]) + "."


_summary_chain = None


def _get_summary_chain():
    global _summary_chain
    if _summary_chain is not None:
        return _summary_chain

    if LLM_PROVIDER not in ("openai", "ollama"):
        return None

    try:
        from processor.classifier import _get_llm
        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.prompts import ChatPromptTemplate

        llm = _get_llm()
        if llm is None:
            return None

        template = ChatPromptTemplate.from_messages([
            ("system", (
                "You are a technical writer specialising in Oracle Cloud. "
                "Write a concise 2-3 sentence plain-English summary of the following "
                "Oracle OCI/OIC release note. Focus on what changed, who it affects, "
                "and what action (if any) is required. Be direct and specific."
            )),
            ("human", "Title: {title}\n\nContent:\n{content}"),
        ])
        _summary_chain = template | llm | StrOutputParser()
        log.info("Summary chain initialised")
    except Exception as exc:
        log.warning("Summary chain init failed: %s", exc)
        _summary_chain = None

    return _summary_chain


def generate_summary(title: str, content: str) -> str:
    chain = _get_summary_chain()
    if chain is None:
        return rule_based_summary(title, content)

    try:
        return chain.invoke({"title": title, "content": content[:1500]}).strip()
    except Exception as exc:
        log.warning("Summary generation failed: %s", exc)
        return rule_based_summary(title, content)


# ── Q&A over stored documents ──────────────────────────────────────────────────

_qa_chain = None


def _get_qa_chain():
    global _qa_chain
    if _qa_chain is not None:
        return _qa_chain

    vs = get_vectorstore()
    if vs is None:
        return None

    if LLM_PROVIDER not in ("openai", "ollama"):
        return None

    try:
        from processor.classifier import _get_llm
        from langchain.chains import RetrievalQA

        llm = _get_llm()
        if llm is None:
            return None

        _qa_chain = RetrievalQA.from_chain_type(
            llm=llm,
            retriever=vs.as_retriever(search_kwargs={"k": 5}),
            chain_type="stuff",
        )
        log.info("Q&A chain initialised")
    except Exception as exc:
        log.warning("Q&A chain init failed: %s", exc)
        _qa_chain = None

    return _qa_chain


def ask(question: str) -> str:
    """
    Answer a natural-language question about the stored Oracle updates.
    Falls back to semantic search if no LLM is configured.
    """
    chain = _get_qa_chain()
    if chain:
        try:
            return chain.invoke({"query": question})["result"]
        except Exception as exc:
            log.warning("Q&A failed: %s", exc)

    # Fallback: return top semantic search snippets
    results = semantic_search(question, k=3)
    if results:
        snippets = "\n\n".join(f"• {r['snippet']}" for r in results)
        return f"(Semantic search results — configure LLM_PROVIDER for full Q&A)\n\n{snippets}"
    return "No relevant information found."
