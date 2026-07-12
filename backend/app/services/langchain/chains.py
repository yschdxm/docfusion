from __future__ import annotations

from typing import Any, Literal

from app.services.langchain.llm_adapter import get_langchain_chat_model
from app.services.langchain.prompts import QA_PROMPT
from app.services.langchain.retriever import DocFusionRetriever

Provider = Literal["deepseek", "mimo"]


async def answer_with_langchain_rag(
    question: str,
    provider: Provider = "deepseek",
    top_k: int = 5,
    rerank_top_n: int | None = None,
) -> dict[str, Any]:
    """
    Minimal LangChain-based RAG QA entry.

    This function intentionally wraps the existing rag_service instead of
    replacing it. LangChain is only used for:
    - retriever wrapper
    - prompt management
    - chain orchestration
    """
    actual_rerank_top_n = rerank_top_n or min(top_k, 5)
    retriever = DocFusionRetriever(top_k=top_k, rerank_top_n=actual_rerank_top_n)
    docs = await retriever.ainvoke(question)

    context = "\n\n---\n\n".join(doc.page_content for doc in docs) if docs else "无可用上下文"
    model = get_langchain_chat_model(provider=provider, temperature=0.3)

    chain = QA_PROMPT | model
    response = await chain.ainvoke(
        {
            "question": question,
            "context": context,
        }
    )

    return {
        "question": question,
        "answer": getattr(response, "content", str(response)),
        "provider": provider,
        "context_count": len(docs),
        "sources": [doc.metadata for doc in docs],
    }