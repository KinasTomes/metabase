"""Shared client for driving the Metabot agent endpoint from a harness.

Both the numeric acceptance suite and the hard-question suite talk to the same
streaming endpoint and pull the same things out of it, so the stream parsing
lives here rather than in each script.
"""

import base64
import json
import sys
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import provision_metabase as P  # noqa: E402  (needs sys.path set first)

authenticate = P.authenticate
call = P.call
BASE_URL = P.BASE_URL
ProvisionError = P.ProvisionError


def ask(question, timeout=420):
    """Send one question; return what the stream said.

    Two wire formats are handled. Current builds emit SSE frames of typed parts
    (`data: {"type": "text-delta", ...}`); older ones emit prefixed lines
    (`0:"text"`, `9:{tool}`). Keeping both means the harnesses grade either.
    """
    body = {
        "message": question,
        "context": {},
        # These belong at the top level of the body, not inside `context` --
        # the endpoint rejects the request without them.
        "history": [],
        "state": {},
        "conversation_id": str(uuid.uuid4()),
    }
    req = urllib.request.Request(
        BASE_URL + "/api/metabot/agent-streaming",
        data=json.dumps(body).encode(),
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Metabase-Session", P._session_token)

    text, tools, navs, errors = "", [], [], []
    queries, preferred = {}, None

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode(errors="replace").rstrip()
            if not line:
                continue

            if line.startswith("data: "):
                try:
                    ev = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                kind = ev.get("type")
                if kind == "text-delta":
                    text += ev.get("delta", "")
                elif kind == "tool-input-available":
                    tools.append(ev.get("toolName"))
                elif kind == "data-state":
                    # Where the built query lives, in MBQL lib (pMBQL) shape.
                    queries.update((ev.get("data") or {}).get("queries") or {})
                elif kind == "data-generated_entity":
                    preferred = ((ev.get("data") or {}).get("query") or {}).get("id")
                elif kind == "error":
                    errors.append(json.dumps(ev))
                continue

            tag, _, payload = line.partition(":")
            try:
                value = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if tag == "0":
                text += value
            elif tag == "9":
                tools.append(value.get("toolName"))
            elif tag == "2" and isinstance(value, dict) and value.get("type") == "navigate_to":
                navs.append(value.get("value"))
            elif tag == "3":
                errors.append(value if isinstance(value, str) else json.dumps(value))

    query = None
    if queries:
        query = queries.get(preferred) or list(queries.values())[-1]
    elif navs:
        query = decode_legacy_query(navs[-1])

    return {"text": text, "tools": tools, "errors": errors, "query": query}


def decode_legacy_query(nav_url):
    """Older builds carried the built question as base64 in a navigate_to link."""
    if not nav_url or "#" not in nav_url:
        return None
    try:
        decoded = json.loads(base64.b64decode(nav_url.split("#", 1)[1] + "=="))
    except Exception:
        return None
    return decoded.get("dataset_query")


def run_query(query):
    """Execute a query Metabot built. /api/dataset takes pMBQL as-is."""
    result = call("POST", "/dataset", query)
    return result.get("data", {}).get("rows", [])
