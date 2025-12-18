import os
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import FastAPI, Depends, HTTPException, status, Header
from boto3.dynamodb.conditions import Key
import json
from decimal import Decimal

from .db import get_polls_table, create_polls_table_if_not_exists
from .auth import decode_token
from .schemas import PollCreate, PollOut, VoteIn, VoteResult
from registry_service.client import register_service, deregister_service


app = FastAPI(title="Polls Service")


@app.on_event("startup")
async def on_startup():
    # Create DynamoDB table if it doesn't exist
    create_polls_table_if_not_exists()
    # Register with service registry
    port = os.getenv("PORT", "5700")
    base_url = f"http://localhost:{port}"
    await register_service("polls", base_url)


@app.on_event("shutdown")
async def on_shutdown():
    # Deregister from service registry
    await deregister_service()


def get_current_username(authorization: Annotated[str | None, Header()] = None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    payload = decode_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return str(payload["sub"])


def _poll_pk(poll_id: str) -> str:
    return f"P#{poll_id}"


def _vote_sk(username: str) -> str:
    return f"V#{username}"


def _poll_item_to_out(item: dict) -> PollOut:
    options = item.get("options", [])
    counts = [
        int(item.get("count0", 0)),
        int(item.get("count1", 0)),
        int(item.get("count2", 0)),
        int(item.get("count3", 0)),
    ][: len(options)]
    return PollOut(
        poll_id=item["poll_id"],
        question=item["question"],
        options=options,
        counts=counts,
        created_by=item["created_by"],
        created_at=datetime.fromisoformat(item["created_at"]),
    )


@app.post("/polls", response_model=PollOut)
def create_poll(data: PollCreate, current_username: str = Depends(get_current_username)):
    table = get_polls_table()
    poll_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    item = {
        "pk": _poll_pk(poll_id),
        "sk": "POLL",
        "poll_id": poll_id,
        "question": data.question,
        "options": data.options,
        "count0": 0,
        "count1": 0,
        "count2": 0,
        "count3": 0,
        "created_by": current_username,
        "created_at": now,
    }
    table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
    return _poll_item_to_out(item)


@app.get("/polls/{poll_id}", response_model=PollOut)
def get_poll(poll_id: str):
    table = get_polls_table()
    resp = table.get_item(Key={"pk": _poll_pk(poll_id), "sk": "POLL"})
    item = resp.get("Item")
    if not item:
        raise HTTPException(status_code=404, detail="Poll not found")
    return _poll_item_to_out(item)


@app.post("/polls/{poll_id}/vote", response_model=VoteResult)
def vote_poll(poll_id: str, vote: VoteIn, current_username: str = Depends(get_current_username)):
    table = get_polls_table()
    # Fetch poll to validate choice range
    poll_resp = table.get_item(Key={"pk": _poll_pk(poll_id), "sk": "POLL"})
    poll_item = poll_resp.get("Item")
    if not poll_item:
        raise HTTPException(status_code=404, detail="Poll not found")
    options = poll_item.get("options", [])
    if vote.choice_index < 0 or vote.choice_index >= len(options):
        raise HTTPException(status_code=400, detail="choice_index out of range")

    # Transaction: create vote if not exists AND increment the relevant counter
    inc_attr = f"count{vote.choice_index}"
    # Debug log to inspect stored types for the counter we are about to increment
    inc_value = poll_item.get(inc_attr)

    try:
        table.meta.client.transact_write_items(
            TransactItems=[
                {
                    "Put": {
                        "TableName": table.name,
                        "Item": {
                            "pk": _poll_pk(poll_id),
                            "sk": _vote_sk(current_username),
                            "poll_id": poll_id,
                            "username": current_username,
                            "choice_index": Decimal(vote.choice_index),
                        },
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                },
                {
                    "Update": {
                        "TableName": table.name,
                        "Key": {"pk": _poll_pk(poll_id), "sk": "POLL"},
                        "ConditionExpression": "attribute_exists(pk)",
                        "UpdateExpression": f"ADD {inc_attr} :one",
                        "ExpressionAttributeValues": {":one": Decimal(1)},
                    }
                },
            ]
        )
    except table.meta.client.exceptions.TransactionCanceledException:
        # Either poll missing or user already voted
        # Determine if duplicate vote:
        vote_check = table.get_item(Key={"pk": _poll_pk(poll_id), "sk": _vote_sk(current_username)})
        if vote_check.get("Item"):
            raise HTTPException(status_code=409, detail="User already voted")
        raise HTTPException(status_code=404, detail="Poll not found")

    # Return updated poll
    updated = table.get_item(Key={"pk": _poll_pk(poll_id), "sk": "POLL"}).get("Item")
    return VoteResult(status="ok", poll=_poll_item_to_out(updated))


@app.get("/polls/{poll_id}/results", response_model=PollOut)
def poll_results(poll_id: str):
    return get_poll(poll_id)


