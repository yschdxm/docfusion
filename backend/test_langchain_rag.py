import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app.services.langchain.chains import answer_with_langchain_rag


async def main() -> None:
    result = await answer_with_langchain_rag("这个系统支持哪些核心功能？")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())