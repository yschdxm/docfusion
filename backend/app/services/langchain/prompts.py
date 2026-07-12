from langchain_core.prompts import ChatPromptTemplate

QA_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "你是 DocFusion 的文档问答助手。请严格依据提供的上下文回答问题；"
            "如果上下文中没有足够信息，请明确说明不知道，不要编造。",
        ),
        (
            "human",
            "问题：{question}\n\n参考上下文：\n{context}",
        ),
    ]
)