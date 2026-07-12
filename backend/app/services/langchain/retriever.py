from __future__ import annotations

from typing import Any, List

from langchain_core.callbacks import (
    AsyncCallbackManagerForRetrieverRun,
    CallbackManagerForRetrieverRun,
)
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import Field

from app.services.rag_service import rag_service


class DocFusionRetriever(BaseRetriever):
    """
    LangChain retriever wrapper around the existing rag_service.

    It keeps the current DocFusion retrieval stack unchanged:
    - embedding_service
    - vector_store_service
    - rerank_service
    - custom metadata handling
    """

    top_k: int = Field(default=5, ge=1)
    rerank_top_n: int = Field(default=5, ge=1)

    def _to_documents(self, results: List[dict[str, Any]]) -> List[Document]:
        documents: List[Document] = []
        for item in results:
            documents.append(
                Document(
                    page_content=item.get("content", ""),
                    metadata={
                        **item.get("metadata", {}),
                        "score": item.get("score"),
                        "rerank_score": item.get("rerank_score"),
                        "doc_id": item.get("doc_id"),
                    },
                )
            )
        return documents

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> List[Document]:
        raise NotImplementedError(
            "DocFusionRetriever 依赖异步 rag_service，请使用 aget_relevant_documents。"
        )

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager: AsyncCallbackManagerForRetrieverRun,
    ) -> List[Document]:
        results = await rag_service.search_relevant_documents(
            query=query,
            top_k=self.top_k,
            rerank_top_n=self.rerank_top_n,
        )
        return self._to_documents(results)