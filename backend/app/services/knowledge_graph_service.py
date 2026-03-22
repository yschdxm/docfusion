from typing import List, Dict, Any, Optional
from uuid import UUID
from app.db.neo4j_db import run_cypher, get_neo4j_driver
from app.services.llm_service import llm_service
from app.db.mongodb import get_collection


class KnowledgeGraphService:
    async def build_graph_from_entities(
        self,
        document_id: str,
        entities: List[Dict[str, Any]]
    ):
        for entity in entities:
            await run_cypher(
                """
                MERGE (e:Entity {name: $name, type: $type})
                SET e.document_id = $document_id,
                    e.value = $value,
                    e.context = $context
                """,
                {
                    "name": entity.get("entity_name"),
                    "type": entity.get("entity_type"),
                    "document_id": document_id,
                    "value": entity.get("entity_value", ""),
                    "context": entity.get("context", "")
                }
            )
        
        await run_cypher(
            """
            MERGE (d:Document {id: $doc_id})
            SET d.entity_count = $count
            """,
            {"doc_id": document_id, "count": len(entities)}
        )
        
        relations = await llm_service.analyze_relationships(entities)
        
        for rel in relations:
            await run_cypher(
                """
                MATCH (a:Entity {name: $source})
                MATCH (b:Entity {name: $target})
                MERGE (a)-[r:RELATED_TO {type: $rel_type}]->(b)
                SET r.description = $description
                """,
                {
                    "source": rel.get("source"),
                    "target": rel.get("target"),
                    "rel_type": rel.get("relation_type", "RELATED"),
                    "description": rel.get("description", "")
                }
            )
        
        return {"entities_count": len(entities), "relations_count": len(relations)}
    
    async def get_graph(self, limit: int = 100) -> Dict[str, Any]:
        nodes_result = await run_cypher(
            """
            MATCH (e:Entity)
            RETURN e.name AS name, e.type AS type, e.value AS value, e.document_id AS document_id
            LIMIT $limit
            """,
            {"limit": limit}
        )
        
        edges_result = await run_cypher(
            """
            MATCH (a:Entity)-[r:RELATED_TO]->(b:Entity)
            RETURN a.name AS source, b.name AS target, r.type AS type, r.description AS description
            LIMIT $limit
            """,
            {"limit": limit}
        )
        
        nodes = [
            {
                "id": r["name"], 
                "name": r["name"], 
                "type": r["type"], 
                "value": r.get("value", ""),
                "document_id": r.get("document_id", "")
            }
            for r in nodes_result
        ]
        
        edges = [
            {"source": r["source"], "target": r["target"], "type": r["type"], "description": r.get("description", "")}
            for r in edges_result
        ]
        
        return {"nodes": nodes, "edges": edges}
    
    async def query_graph(self, query: str) -> Dict[str, Any]:
        search_result = await run_cypher(
            """
            MATCH (e:Entity)
            WHERE e.name CONTAINS $query OR e.value CONTAINS $query
            RETURN e.name AS name, e.type AS type, e.value AS value, e.context AS context
            LIMIT 20
            """,
            {"query": query}
        )
        
        related_entities = [
            {
                "name": r["name"],
                "type": r["type"],
                "value": r.get("value", ""),
                "context": r.get("context", "")
            }
            for r in search_result
        ]
        
        if related_entities:
            context = "\n".join([
                f"- {e['name']} ({e['type']}): {e.get('value', '')}"
                for e in related_entities
            ])
            
            prompt = f"""基于以下知识图谱信息回答用户问题。

知识图谱相关信息：
{context}

用户问题：{query}

请根据提供的信息回答问题。"""
            
            messages = [{"role": "user", "content": prompt}]
            answer = await llm_service.chat_completion(messages, temperature=0.5)
        else:
            answer = "未找到相关实体信息。"
        
        return {
            "answer": answer,
            "related_entities": related_entities
        }
    
    async def find_document_relations(self, doc_ids: List[str]) -> Dict[str, Any]:
        result = await run_cypher(
            """
            MATCH (e1:Entity)-[r:RELATED_TO]-(e2:Entity)
            WHERE e1.document_id IN $doc_ids AND e2.document_id IN $doc_ids
              AND e1.document_id <> e2.document_id
            RETURN e1.name AS entity1, e1.document_id AS doc1,
                   e2.name AS entity2, e2.document_id AS doc2,
                   r.type AS relation_type
            LIMIT 50
            """,
            {"doc_ids": doc_ids}
        )
        
        cross_relations = [
            {
                "entity1": r["entity1"],
                "doc1": r["doc1"],
                "entity2": r["entity2"],
                "doc2": r["doc2"],
                "relation_type": r["relation_type"]
            }
            for r in result
        ]
        
        return {"cross_relations": cross_relations}


knowledge_graph_service = KnowledgeGraphService()
