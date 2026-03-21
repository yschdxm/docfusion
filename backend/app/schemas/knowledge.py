from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class KnowledgeBuildRequest(BaseModel):
    file_ids: List[str]


class KnowledgeQueryRequest(BaseModel):
    query: str


class KnowledgeNode(BaseModel):
    id: str
    name: str
    type: str
    properties: Dict[str, Any] = {}


class KnowledgeEdge(BaseModel):
    source: str
    target: str
    relation_type: str
    properties: Dict[str, Any] = {}


class KnowledgeGraphResponse(BaseModel):
    nodes: List[KnowledgeNode] = []
    edges: List[KnowledgeEdge] = []


class KnowledgeQueryResponse(BaseModel):
    answer: str
    related_nodes: List[KnowledgeNode] = []
    related_edges: List[KnowledgeEdge] = []
