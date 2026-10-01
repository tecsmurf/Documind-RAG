"""IDOR / BOLA: user B must never reach user A's documents, chunks, conversations or messages."""
from sqlalchemy import select

from app.database.connection import async_session
from app.models import Chunk
from app.services.retrieval_service import search_chunks
from tests.helpers import fake_vector, parse_sse, register, upload


async def setup_two_users(client):
    a = await register(client, "alice@example.com")
    b = await register(client, "bob@example.com")
    _, doc_a = await upload(client, a, "alice-secret.txt", b"Alice's launch code is PELICAN-42 and only Alice may know it.")
    _, doc_b = await upload(client, b, "bob.txt", b"Bob writes about gardening tomatoes in summer.")
    conv_a = (await client.post("/api/chat/conversations", headers=a, json={})).json()
    r = await client.post(f"/api/chat/conversations/{conv_a['id']}/stream", headers=a, json={"question": "What is the launch code?"})
    assert r.status_code == 200
    async with async_session() as db:
        chunk_a = (await db.execute(select(Chunk.id).where(Chunk.document_id == doc_a["id"]))).scalars().first()
    return a, b, doc_a, doc_b, conv_a, chunk_a


async def test_cross_user_document_and_chunk_access(client):
    a, b, doc_a, doc_b, conv_a, chunk_a = await setup_two_users(client)
    assert (await client.get(f"/api/documents/{doc_a['id']}", headers=b)).status_code == 404
    assert (await client.get(f"/api/documents/{doc_a['id']}/chunks/{chunk_a}", headers=b)).status_code == 404
    # B's own document id combined with A's chunk id must not work either
    assert (await client.get(f"/api/documents/{doc_b['id']}/chunks/{chunk_a}", headers=b)).status_code == 404
    assert (await client.delete(f"/api/documents/{doc_a['id']}", headers=b)).status_code == 404
    assert [d["id"] for d in (await client.get("/api/documents", headers=b)).json()] == [doc_b["id"]]
    # still there for A
    assert (await client.get(f"/api/documents/{doc_a['id']}", headers=a)).status_code == 200
    assert (await client.get(f"/api/documents/{doc_a['id']}/chunks/{chunk_a}", headers=a)).status_code == 200
    # nonexistent and foreign ids look identical
    missing = await client.get("/api/documents/999999", headers=b)
    foreign = await client.get(f"/api/documents/{doc_a['id']}", headers=b)
    assert missing.json()["detail"] == foreign.json()["detail"]


async def test_cross_user_conversation_access(client):
    a, b, doc_a, doc_b, conv_a, _ = await setup_two_users(client)
    cid = conv_a["id"]
    assert (await client.get(f"/api/chat/conversations/{cid}/messages", headers=b)).status_code == 404
    assert (await client.post(f"/api/chat/conversations/{cid}/ask", headers=b, json={"question": "hi"})).status_code == 404
    assert (await client.post(f"/api/chat/conversations/{cid}/stream", headers=b, json={"question": "hi"})).status_code == 404
    assert (await client.delete(f"/api/chat/conversations/{cid}", headers=b)).status_code == 404
    assert (await client.get("/api/chat/conversations", headers=b)).json() == []
    msgs = (await client.get(f"/api/chat/conversations/{cid}/messages", headers=a)).json()
    assert len(msgs) == 2  # A's history untouched


async def test_retrieval_never_returns_other_users_chunks(client, fake_gemini):
    a, b, doc_a, doc_b, conv_a, _ = await setup_two_users(client)
    conv_b = (await client.post("/api/chat/conversations", headers=b, json={})).json()
    calls_before = len(fake_gemini.generate_calls)
    # Bob asks about Alice's secret, explicitly naming Alice's document id.
    r = await client.post(
        f"/api/chat/conversations/{conv_b['id']}/stream", headers=b,
        json={"question": "What is Alice's launch code PELICAN?", "document_ids": [doc_a["id"]]},
    )
    events = parse_sse(r.text)
    citations = next(e for e in events if e["type"] == "citations")["data"]
    assert citations == []
    assert len(fake_gemini.generate_calls) == calls_before  # nothing of Alice's reached the model

    # Direct service check with the exact query vector of Alice's text.
    async with async_session() as db:
        rows = await search_chunks(db, fake_vector("Alice launch code PELICAN-42"), user_id=2, top_k=20)
        assert {r["document_id"] for r in rows} == {doc_b["id"]}
        rows = await search_chunks(db, fake_vector("Alice launch code PELICAN-42"), user_id=2, document_ids=[doc_a["id"]])
        assert rows == []
        rows = await search_chunks(db, fake_vector("Alice launch code PELICAN-42"), user_id=1)
        assert rows[0]["document_id"] == doc_a["id"]


async def test_citations_in_history_belong_to_owner(client):
    a, b, doc_a, _, conv_a, _ = await setup_two_users(client)
    msgs = (await client.get(f"/api/chat/conversations/{conv_a['id']}/messages", headers=a)).json()
    cites = msgs[1]["citations"]
    assert cites and all(c["document_id"] == doc_a["id"] for c in cites)
