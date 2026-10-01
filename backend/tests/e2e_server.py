"""
Run the real app with Gemini replaced by the deterministic test fake, for
browser end-to-end tests without a GOOGLE_API_KEY. Never used in production.

    DATABASE_URL=... python -m tests.e2e_server   (port from E2E_PORT, default 8000)
"""
import asyncio
import os

import uvicorn

os.environ.setdefault("GOOGLE_API_KEY", "e2e-fake-key")

from app.services import gemini  # noqa: E402
from tests.helpers import fake_vector  # noqa: E402


async def embed_texts(texts, task_type):
    return [fake_vector(t) for t in texts]


async def stream_generate(system_instruction, contents):
    question = contents[-1].parts[0].text.rsplit("<user_question>", 1)[-1].split("</user_question>")[0].strip()
    answer = (
        f"**Fake answer (E2E mode)** to: _{question}_\n\n"
        "- The most relevant passage is cited here [1].\n"
        "- [a link](https://example.com) and [a bad link](javascript:alert(1))\n\n"
        "<img src=x onerror=alert(1)> ![tracker](https://example.com/pixel.png)"
    )
    for i in range(0, len(answer), 12):
        await asyncio.sleep(0.03)
        yield answer[i : i + 12]


gemini.embed_texts = embed_texts
gemini.stream_generate = stream_generate

if __name__ == "__main__":
    from app.main import app

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("E2E_PORT", "8000")), log_level="info")
