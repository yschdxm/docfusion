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
                SET e.value = $value,
                    e.context = $context
                """,
                {
                    "name": entity.get("entity_name"),
                    "type": entity.get("entity_type"),
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
        
        for entity in entities:
            await run_cypher(
                """
                MATCH (d:Document {id: $doc_id})
                MATCH (e:Entity {name: $name, type: $type})
                MERGE (d)-[:HAS_ENTITY]->(e)
                """,
                {
                    "doc_id": document_id,
                    "name": entity.get("entity_name"),
                    "type": entity.get("entity_type")
                }
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
            MATCH (e:Entity)<-[:HAS_ENTITY]-(d:Document)
            RETURN e.name AS name, e.type AS type, e.value AS value, 
                   collect(DISTINCT d.id) AS document_ids
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
                "document_ids": r.get("document_ids", [])
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
            MATCH (d1:Document {id: $doc_id1})-[:HAS_ENTITY]->(e:Entity)<-[:HAS_ENTITY]-(d2:Document {id: $doc_id2})
            WHERE d1.id < d2.id
            RETURN e.name AS entity_name, e.type AS entity_type,
                   d1.id AS doc1, d2.id AS doc2
            LIMIT 50
            """,
            {"doc_id1": doc_ids[0] if doc_ids else "", "doc_id2": doc_ids[1] if len(doc_ids) > 1 else ""}
        )
        
        shared_entities = [
            {
                "entity_name": r["entity_name"],
                "entity_type": r["entity_type"],
                "doc1": r["doc1"],
                "doc2": r["doc2"]
            }
            for r in result
        ]
        
        return {"shared_entities": shared_entities}


knowledge_graph_service = KnowledgeGraphService()
