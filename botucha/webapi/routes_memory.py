"""Facts, slang, people and relations — through Memory, with the same checks as the chat commands."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..guard import MAX_FACT_CHARS, MAX_SLANG_CHARS, looks_like_instruction, mentions_bot

router = APIRouter()
MAX_REL_CHARS = 60
MAX_NAME_CHARS = 60


class FactIn(BaseModel):
    kind: Literal["fact", "slang"]
    text: str
    about: int | None = None


class FactEdit(BaseModel):
    text: str


class PersonIn(BaseModel):
    name: str = Field(max_length=MAX_NAME_CHARS)
    aliases: list[str] = []


class AliasesIn(BaseModel):
    aliases: list[str]


class RelationIn(BaseModel):
    a: int
    rel: str
    b: int


def _mem(request: Request):
    return request.app.state.deps.memory


def _clean(kind: str, text: str, bot_name_regex: str) -> str:
    text = " ".join(text.split())
    if not text:
        raise HTTPException(422, "text is empty")
    if kind == "slang":
        word, sep, meaning = text.partition("=")
        if not sep or not word.strip() or not meaning.strip():
            raise HTTPException(422, "slang must look like: word = meaning")
        text = f"{word.strip().lower()} = {meaning.strip()}"
    limit = MAX_SLANG_CHARS if kind == "slang" else MAX_FACT_CHARS
    if len(text) > limit:
        raise HTTPException(422, f"too long, max {limit} characters")
    if looks_like_instruction(text):
        raise HTTPException(422, "looks like an instruction to the bot, not a fact")
    if mentions_bot(text, bot_name_regex):
        raise HTTPException(422, "memory is about the group: a line about the bot himself would read as a rule")
    return text


async def _embedded(coro):
    try:
        return await coro
    except (ConnectionError, OSError, TimeoutError) as e:
        raise HTTPException(503, "embeddings unavailable") from e
    except Exception as e:  # ollama client raises its own error types
        if type(e).__module__.startswith(("ollama", "httpx", "httpcore")):
            raise HTTPException(503, "embeddings unavailable") from e
        raise


def _fact_json(mem, f) -> dict:
    return {"id": f.id, "kind": f.kind, "text": f.text, "about": f.about, "source": f.source,
            "created": f.created, "updated": f.updated, "chat_id": f.chat_id,
            "people": [p.id for p in mem.people_of_fact(f.id)]}


@router.get("/api/facts")
async def facts(request: Request, kind: Literal["fact", "slang"] | None = None, q: str | None = None,
                person_id: int | None = None, source: Literal["auto", "member", "web"] | None = None) -> list[dict]:
    mem = _mem(request)
    rows = mem.person_facts(person_id) if person_id is not None else mem.all_facts()
    if kind:
        rows = [f for f in rows if f.kind == kind]
    if source == "member":
        rows = [f for f in rows if f.source.startswith("cmd:")]
    elif source:
        rows = [f for f in rows if f.source == source]
    if q:
        rows = [f for f in rows if q.casefold() in f.text.casefold()]
    return [_fact_json(mem, f) for f in rows]


@router.post("/api/facts")
async def add_fact(request: Request, body: FactIn) -> dict:
    mem = _mem(request)
    fid = await _embedded(mem.add_fact(body.kind, _clean(body.kind, body.text, request.app.state.deps.cfg.telegram.bot_name_regex),
                                       body.about, "web"))
    return _fact_json(mem, next(f for f in mem.all_facts() if f.id == fid))


@router.put("/api/facts/{fact_id}")
async def edit_fact(request: Request, fact_id: int, body: FactEdit) -> dict:
    mem = _mem(request)
    cur = next((f for f in mem.all_facts() if f.id == fact_id), None)
    if cur is None:
        raise HTTPException(404, "no such fact")
    await _embedded(mem.update_fact(fact_id, _clean(cur.kind, body.text, request.app.state.deps.cfg.telegram.bot_name_regex)))
    return _fact_json(mem, next(f for f in mem.all_facts() if f.id == fact_id))


@router.delete("/api/facts/{fact_id}")
async def delete_fact(request: Request, fact_id: int) -> dict:
    if not _mem(request).delete_fact(fact_id):
        raise HTTPException(404, "no such fact")
    return {"ok": True}


@router.get("/api/people")
async def people(request: Request) -> dict:
    mem = _mem(request)
    return {
        "people": [{"id": p.id, "name": p.name, "aliases": p.aliases, "user_id": p.user_id,
                    "fact_count": len(mem.person_facts(p.id))} for p in mem.people()],
        "relations": [{"id": r.id, "a": r.a.id, "rel": r.rel, "b": r.b.id} for r in mem.relations()],
        "comentions": [{"a": a, "b": b, "n": n} for a, b, n in mem.comentions()],
    }


@router.post("/api/people")
async def add_person(request: Request, body: PersonIn) -> dict:
    name = " ".join(body.name.split())
    if not name:
        raise HTTPException(422, "name is empty")
    if any(len(a) > 40 for a in body.aliases):
        raise HTTPException(422, "a word form is too long, max 40 characters")
    pid = _mem(request).add_person(name, body.aliases)
    return {"id": pid}


@router.put("/api/people/{person_id}")
async def set_aliases(request: Request, person_id: int, body: AliasesIn) -> dict:
    if any(len(a) > 40 for a in body.aliases):
        raise HTTPException(422, "a word form is too long, max 40 characters")
    if not _mem(request).set_aliases(person_id, body.aliases):
        raise HTTPException(404, "no such person")
    return {"ok": True}


@router.post("/api/relations")
async def add_relation(request: Request, body: RelationIn) -> dict:
    mem = _mem(request)
    a, b, rel = mem.get_person(body.a), mem.get_person(body.b), " ".join(body.rel.split())
    if a is None or b is None:
        raise HTTPException(422, "unknown person")
    if a.id == b.id:
        raise HTTPException(422, "a relation needs two different people")
    if not rel or len(rel) > MAX_REL_CHARS:
        raise HTTPException(422, f"relation must be 1–{MAX_REL_CHARS} characters")
    if looks_like_instruction(rel):
        raise HTTPException(422, "looks like an instruction to the bot")
    rid = mem.add_relation_ids(a.id, rel, b.id, "web")  # by id: a name can resolve to someone else
    if rid is None:
        raise HTTPException(422, "cannot link these people")
    return {"id": rid}


@router.delete("/api/relations/{relation_id}")
async def delete_relation(request: Request, relation_id: int) -> dict:
    if not _mem(request).delete_relation(relation_id):
        raise HTTPException(404, "no such relation")
    return {"ok": True}
