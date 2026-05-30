from pydantic import BaseModel
from typing import List


class KnowledgeBuildRequest(BaseModel):
    file_ids: List[str]


class KnowledgeQueryRequest(BaseModel):
    query: str


class KnowledgeNode(BaseModel):
    id: str
    name: str
    type: str
    document_ids: List[str] = []
    value: str = ""


class KnowledgeEdge(BaseModel):
    source: str
    target: str
    type: str = ""
    description: str = ""


class KnowledgeGraphResponse(BaseModel):
    nodes: List[KnowledgeNode] = []
    edges: List[KnowledgeEdge] = []


class KnowledgeQueryResponse(BaseModel):
    answer: str
    related_nodes: List[KnowledgeNode] = []
    related_edges: List[KnowledgeEdge] = []
