"""
LangChain integration layer for DocFusion.

This package provides a low-intrusion orchestration layer on top of the
existing services. Core services such as llm_service, rag_service,
embedding_service and vector_store_service remain unchanged.
"""

from app.services.langchain.chains import answer_with_langchain_rag
from app.services.langchain.llm_adapter import get_langchain_chat_model
from app.services.langchain.retriever import DocFusionRetriever

__all__ = [
    "answer_with_langchain_rag",
    "get_langchain_chat_model",
    "DocFusionRetriever",
]