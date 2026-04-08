"""Neo4j Cypher查询生成Prompt模板"""

NEO4J_QUERY_PROMPT = """你是Neo4j Cypher查询专家。根据用户需求和数据库schema生成查询。

## 用户需求
{question}

## 表格表头（需要提取的字段）
{table_headers}

## Neo4j数据库Schema
{schema}

## 文档ID过滤（只查询这些文档的实体）
{doc_ids}
- 如果 doc_ids 非空：只查询这些文档的实体
- 如果 doc_ids 为空：工具将返回错误，提示需要指定查询范围

## 文档标题（数据范围约束）
{document_title}

## 数据范围要求
- 根据文档标题，只查询与该主题直接相关的数据
- 排除与主题无关的数据

## 重要说明：实体存储结构
1. 实体使用动态Label（如:Location, :Person等），不是固定的:Entity
2. 属性是平铺存储的（n.name, n.city, n.GDP等），不是JSON格式的attributes字段
3. 每个节点都有name属性（实体名称）和document_ids属性（文档ID列表）

## 要求
1. 使用Cypher语法
2. **重要**：必须包含文档过滤: WHERE any(did IN $doc_ids WHERE did IN n.document_ids)
   - 如果 doc_ids 为空，工具将返回错误，提示需要指定查询范围
   - 在实际查询中，doc_ids 参数由用户提供或从上下文获取
3. 返回的字段名应与表头对应，但**重要**：AS别名只能使用英文字母、数字、下划线，不能包含中文括号（）或特殊字符
4. 首次查询可使用精确匹配或模糊匹配（CONTAINS）
5. 直接查询节点的属性（如n.city, n.GDP），不要查询n.attributes
6. 使用LIMIT限制返回数量（最多100条）

## 输出格式（JSON）
{{"cypher": "MATCH (n)... WHERE ... RETURN ...", "explanation": "查询说明"}}

只返回JSON，不要其他说明。"""

NEO4J_RETRY_PROMPT = """前一次Neo4j查询未能获取有效结果，请分析原因并调整查询。

## 前一次查询
{cypher}

## 失败原因
{error_or_empty_reason}

## Neo4j数据库Schema
{schema}

## 文档ID
{doc_ids}

## 重要说明
1. 实体使用动态Label（如:Location, :Person等）
2. 属性是平铺存储的（n.name, n.city, n.GDP等），不是JSON格式的attributes字段
3. 不要使用apoc.convert.fromJsonMap(n.attributes)，直接访问属性如n.city

## 调整策略建议
1. 如果按名称精确匹配无结果，尝试使用CONTAINS模糊匹配
2. 如果特定节点类型无结果，尝试查询其他相关节点类型（MATCH (n) 不限定Label）
3. 如果关系查询无结果，尝试直接查询节点属性
4. 检查是否正确使用了doc_id过滤（any(did IN $doc_ids WHERE did IN n.document_ids)）
5. 放宽查询条件，返回更多节点再筛选
6. 直接查询属性如n.city, n.GDP，不要用n.attributes['city']
7. **重要**：AS别名只能使用英文字母、数字、下划线，不能包含中文括号（）或特殊字符

## 输出格式（JSON）
{{"cypher": "MATCH (n)... WHERE ... RETURN ...", "explanation": "调整说明"}}

只返回JSON，不要其他说明。"""

NEO4J_EXTRACT_PROMPT = """从Neo4j查询结果中提取符合表格结构的结构化数据记录。

## 表格表头
{table_headers}

## Neo4j查询结果（JSON格式）
{results}

## 重要说明
1. 属性是平铺存储的（n.name, n.city, n.GDP等），不是JSON格式的attributes字段
2. 直接从返回的字段中提取值，不需要解析JSON

## 要求
1. 从Neo4j返回的数据中提取字段值
2. 字段名应与表头对应，必要时进行映射（如name->城市名）
3. 每个记录必须包含表头中的所有字段，没有的设为null
4. 数值保持原始精度

## 输出格式（JSON）
{{"records": [
  {{"表头1": "值1", "表头2": "值2", ...}},
  {{"表头1": "值3", "表头2": "值4", ...}}
]}}

只返回JSON，不要其他说明。"""
