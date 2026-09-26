import pytest
from fastapi.testclient import TestClient
from bot import app, contexts, conversations, START_TIME
from engine import suppressed_keys, suppressed_conversations

client = TestClient(app)

def setup_function():
    contexts.clear()
    conversations.clear()
    suppressed_keys.clear()
    suppressed_conversations.clear()

def test_healthz():
    contexts[("category", "dentists")] = {"version": 1, "payload": {}}
    contexts[("merchant", "m_001")] = {"version": 1, "payload": {}}
    contexts[("customer", "c_001")] = {"version": 1, "payload": {}}
    
    response = client.get("/v1/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "uptime_seconds" in data
    assert data["contexts_loaded"] == {"category": 1, "merchant": 1, "customer": 1, "trigger": 0}

def test_metadata():
    response = client.get("/v1/metadata")
    assert response.status_code == 200

def test_push_context_success_and_stale():
    payload = {
        "scope": "category",
        "context_id": "dentists",
        "version": 1,
        "delivered_at": "2026-04-26T09:45:00Z",
        "payload": {"slug": "dentists"}
    }
    response = client.post("/v1/context", json=payload)
    assert response.status_code == 200
    
    response2 = client.post("/v1/context", json=payload)
    assert response2.status_code == 200
    
    payload["version"] = 0
    response3 = client.post("/v1/context", json=payload)
    assert response3.status_code == 409

def test_invalid_scope():
    payload = {
        "scope": "invalid",
        "context_id": "test",
        "version": 1,
        "delivered_at": "2026-04-26T09:45:00Z",
        "payload": {}
    }
    response = client.post("/v1/context", json=payload)
    assert response.status_code == 400

def test_tick_with_contexts():
    # Setup contexts
    contexts[("category", "dentists")] = {"version": 1, "payload": {"slug": "dentists"}}
    contexts[("merchant", "m_001")] = {"version": 1, "payload": {"merchant_id": "m_001", "category_slug": "dentists", "identity": {"name": "Dr. Meera"}}}
    contexts[("trigger", "trg_001")] = {"version": 1, "payload": {"merchant_id": "m_001", "kind": "research_digest", "scope": "merchant", "urgency": 2, "suppression_key": "test_suppress"}}
    
    payload = {
        "now": "2026-04-26T10:35:00Z",
        "available_triggers": ["trg_001"]
    }
    response = client.post("/v1/tick", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert len(data["actions"]) == 1
    action = data["actions"][0]
    assert action["send_as"] == "vera"
    assert action["cta"] == "open_ended"
    
def test_all_five_categories():
    categories = ["dentists", "salons", "restaurants", "gyms", "pharmacies"]
    triggers = []
    
    for i, cat in enumerate(categories):
        contexts[("category", cat)] = {"version": 1, "payload": {"slug": cat, "voice": {"vocab_taboo": ["taboo"]}}}
        contexts[("merchant", f"m_{i}")] = {"version": 1, "payload": {"merchant_id": f"m_{i}", "category_slug": cat, "identity": {"name": f"Shop {i}"}}}
        contexts[("trigger", f"trg_{i}")] = {"version": 1, "payload": {"merchant_id": f"m_{i}", "kind": "curious_ask_due", "scope": "merchant", "urgency": 2, "suppression_key": f"supp_{i}"}}
        triggers.append(f"trg_{i}")
        
    payload = {
        "now": "2026-04-26T10:35:00Z",
        "available_triggers": triggers
    }
    response = client.post("/v1/tick", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert len(data["actions"]) == 5
    # Verify suppression rules apply on the next tick
    response2 = client.post("/v1/tick", json=payload)
    assert len(response2.json()["actions"]) == 0

def test_expired_offer():
    contexts[("category", "dentists")] = {"version": 1, "payload": {"slug": "dentists"}}
    contexts[("merchant", "m_001")] = {"version": 1, "payload": {"merchant_id": "m_001", "category_slug": "dentists", "identity": {"name": "Dr. Meera"}}}
    contexts[("trigger", "trg_expired")] = {"version": 1, "payload": {"merchant_id": "m_001", "kind": "research_digest", "scope": "merchant", "expires_at": "2020-01-01T00:00:00Z"}}
    
    payload = {
        "now": "2026-04-26T10:35:00Z",
        "available_triggers": ["trg_expired"]
    }
    response = client.post("/v1/tick", json=payload)
    assert response.status_code == 200
    assert len(response.json()["actions"]) == 0

def test_reply_auto_reply():
    payload = {
        "conversation_id": "conv_002",
        "merchant_id": "m_001",
        "from_role": "merchant",
        "message": "Thank you for contacting us.",
        "received_at": "2026-04-26T10:45:00Z",
        "turn_number": 2
    }
    response = client.post("/v1/reply", json=payload)
    assert response.status_code == 200
    assert response.json()["action"] == "wait"

def test_reply_hostile():
    payload = {
        "conversation_id": "conv_003",
        "merchant_id": "m_001",
        "from_role": "merchant",
        "message": "Not interested",
        "received_at": "2026-04-26T10:45:00Z",
        "turn_number": 2
    }
    response = client.post("/v1/reply", json=payload)
    assert response.status_code == 200
    assert response.json()["action"] == "end"
    
def test_reply_intent():
    payload = {
        "conversation_id": "conv_004",
        "merchant_id": "m_001",
        "from_role": "merchant",
        "message": "Yes let's do it",
        "received_at": "2026-04-26T10:45:00Z",
        "turn_number": 2
    }
    response = client.post("/v1/reply", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "send"
    assert data["cta"] == "binary_confirm_cancel"
def test_merchant_scoped_suppression():
    contexts[("category", "dentists")] = {"version": 1, "payload": {"slug": "dentists"}}
    contexts[("merchant", "m_001")] = {"version": 1, "payload": {"merchant_id": "m_001", "category_slug": "dentists", "identity": {"name": "Dr. A"}}}
    contexts[("merchant", "m_002")] = {"version": 1, "payload": {"merchant_id": "m_002", "category_slug": "dentists", "identity": {"name": "Dr. B"}}}
    
    contexts[("trigger", "trg_1")] = {"version": 1, "payload": {"merchant_id": "m_001", "kind": "research_digest", "scope": "merchant", "urgency": 2, "suppression_key": "global_key"}}
    contexts[("trigger", "trg_2")] = {"version": 1, "payload": {"merchant_id": "m_002", "kind": "research_digest", "scope": "merchant", "urgency": 2, "suppression_key": "global_key"}}
    
    payload1 = {"now": "2026-04-26T10:35:00Z", "available_triggers": ["trg_1"]}
    resp1 = client.post("/v1/tick", json=payload1)
    assert len(resp1.json()["actions"]) == 1
    
    payload2 = {"now": "2026-04-26T10:36:00Z", "available_triggers": ["trg_2"]}
    resp2 = client.post("/v1/tick", json=payload2)
    assert len(resp2.json()["actions"]) == 1
    
    resp3 = client.post("/v1/tick", json=payload1)
    assert len(resp3.json()["actions"]) == 0
def test_missing_contexts():
    contexts[("trigger", "trg_missing")] = {"version": 1, "payload": {"merchant_id": "m_003", "kind": "research_digest", "scope": "merchant"}}
    payload = {"now": "2026-04-26T10:35:00Z", "available_triggers": ["trg_missing"]}
    resp = client.post("/v1/tick", json=payload)
    assert resp.status_code == 200
    assert len(resp.json()["actions"]) == 0

def test_competing_triggers():
    contexts[("category", "dentists")] = {"version": 1, "payload": {"slug": "dentists"}}
    contexts[("merchant", "m_001")] = {"version": 1, "payload": {"merchant_id": "m_001", "category_slug": "dentists", "identity": {"name": "Dr. A"}}}
    
    contexts[("trigger", "trg_low")] = {"version": 1, "payload": {"merchant_id": "m_001", "kind": "curious_ask_due", "scope": "merchant", "urgency": 1, "suppression_key": "k1"}}
    contexts[("trigger", "trg_high")] = {"version": 1, "payload": {"merchant_id": "m_001", "kind": "regulation_change", "scope": "merchant", "urgency": 5, "suppression_key": "k2"}}
    
    payload = {"now": "2026-04-26T10:35:00Z", "available_triggers": ["trg_low", "trg_high"]}
    resp = client.post("/v1/tick", json=payload)
    actions = resp.json()["actions"]
    assert len(actions) == 1
    assert actions[0]["trigger_id"] == "trg_high"

def test_vocabulary_taboos():
    contexts[("category", "dentists")] = {"version": 1, "payload": {"slug": "dentists", "voice": {"vocab_taboo": ["guaranteed", "100% safe"]}}}
    contexts[("merchant", "m_001")] = {"version": 1, "payload": {"merchant_id": "m_001", "category_slug": "dentists", "identity": {"name": "Dr. A"}}}
    # We will trigger a fake kind that we know won't have taboos natively, but we can verify the taboo filter works.
    # Actually, in composer.py we don't inject "guaranteed" in the template. 
    # Let's bypass composer for a second by calling validate_message directly.
    from composer import validate_message
    msg = {"body": "This is guaranteed to be 100% safe!", "cta": "none", "send_as": "vera", "rationale": ""}
    res = validate_message(msg, contexts[("category", "dentists")]["payload"])
    assert "guaranteed" not in res["body"].lower()
    assert "[REDACTED]" in res["body"]

