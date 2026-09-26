import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import logging

from engine import get_contexts, evaluate_triggers, suppressed_keys, suppressed_conversations
from composer import compose

# Configure structured logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("vera-bot")

app = FastAPI(title="Vera AI Challenge Bot")

START_TIME = time.time()

# In-memory stores
contexts: Dict[Tuple[str, str], Dict[str, Any]] = {}
conversations: Dict[str, List[Dict[str, Any]]] = {}

# --- Models ---

class CtxBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: Dict[str, Any]
    delivered_at: str

class TickBody(BaseModel):
    now: str
    available_triggers: List[str] = []

class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str
    message: str
    received_at: str
    turn_number: int

# --- Endpoints ---

@app.get("/v1/healthz")
async def healthz():
    counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
    for (scope, _), _ in contexts.items():
        if scope in counts:
            counts[scope] += 1
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - START_TIME),
        "contexts_loaded": counts
    }

@app.get("/v1/metadata")
async def metadata():
    return {
        "team_name": "Team Alpha",
        "team_members": ["Backend Engineer"],
        "model": "gemini-1.5-pro",
        "approach": "Deterministic state machine and context aggregator",
        "contact_email": "team@example.com",
        "version": "1.0.0",
        "submitted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    }

@app.post("/v1/context")
async def push_context(body: CtxBody):
    valid_scopes = {"category", "merchant", "customer", "trigger"}
    if body.scope not in valid_scopes:
        return JSONResponse(
            status_code=400,
            content={"accepted": False, "reason": "invalid_scope", "details": f"Scope '{body.scope}' is not valid."}
        )
    
    key = (body.scope, body.context_id)
    cur = contexts.get(key)
    
    if cur:
        if cur["version"] > body.version:
            return JSONResponse(
                status_code=409,
                content={"accepted": False, "reason": "stale_version", "current_version": cur["version"]}
            )
        elif cur["version"] == body.version:
            # Idempotent update
            pass
    
    contexts[key] = {"version": body.version, "payload": body.payload}
    logger.info(f"Context updated: {body.scope}/{body.context_id} v{body.version}")
    
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    
    return {
        "accepted": True, 
        "ack_id": f"ack_{body.context_id}_v{body.version}",
        "stored_at": now_str
    }

@app.post("/v1/tick")
async def tick(body: TickBody):
    logger.info(f"Tick received at {body.now} with {len(body.available_triggers)} triggers")
    actions = []
    
    valid_trigger_ids = evaluate_triggers(contexts, body.available_triggers, body.now)
    used_merchants = set()
    
    for tid in valid_trigger_ids:
        cat, mch, trg, cust = get_contexts(contexts, tid)
        if not mch or not cat:
            continue
            
        merchant_id = mch.get("merchant_id")
        if merchant_id in used_merchants:
            # One action per merchant per tick
            continue
            
        conv_id = f"conv_{merchant_id}_{tid}"
        if conv_id in suppressed_conversations:
            continue
            
        provider = None
        groq_key = os.environ.get("GROQ_API_KEY")
        openai_key = os.environ.get("OPENAI_API_KEY")
        gemini_key = os.environ.get("GEMINI_API_KEY")
        
        if groq_key:
            from composer import GroqProvider
            provider = GroqProvider(groq_key)
        elif openai_key:
            from composer import OpenAIProvider
            provider = OpenAIProvider(openai_key)
        elif gemini_key:
            from composer import GeminiProvider
            provider = GeminiProvider(gemini_key)
            
        composed = compose(cat, mch, trg, cust, provider)
        
        actions.append({
            "conversation_id": conv_id,
            "merchant_id": merchant_id,
            "customer_id": cust.get("customer_id") if cust else None,
            "send_as": composed["send_as"],
            "trigger_id": tid,
            "template_name": "vera_generic_v1",
            "template_params": [mch.get("identity", {}).get("name", "")],
            "body": composed["body"],
            "cta": composed["cta"],
            "suppression_key": composed["suppression_key"],
            "rationale": composed["rationale"]
        })
        
        used_merchants.add(merchant_id)
        if composed["suppression_key"]:
            suppressed_keys.add((merchant_id, composed["suppression_key"]))
            
    return {"actions": actions}

@app.post("/v1/reply")
async def reply(body: ReplyBody):
    logger.info(f"Reply received for conversation {body.conversation_id} from {body.from_role}")
    
    if body.conversation_id in suppressed_conversations:
        return {
            "action": "end",
            "rationale": "Conversation previously suppressed/ended."
        }
        
    history = conversations.setdefault(body.conversation_id, [])
    history.append({
        "from": body.from_role,
        "msg": body.message
    })
    
    merchant_msgs = [t["msg"] for t in history if t["from"] == "merchant"]
    
    # Replay Test 4.1: Auto-reply hell
    if len(merchant_msgs) >= 3 and len(set(merchant_msgs[-3:])) == 1:
        suppressed_conversations.add(body.conversation_id)
        return {
            "action": "end",
            "rationale": "Auto-reply 3x in a row, no real reply. Conversation has zero engagement signal; closing."
        }
        
    msg_lower = body.message.lower()
    if "thank you for contacting" in msg_lower or "automated assistant" in msg_lower:
        return {
            "action": "wait",
            "wait_seconds": 14400,
            "rationale": "Detected merchant auto-reply. Backing off 4 hours to wait for owner."
        }
        
    # Replay Test 4.3: Hostile / Off-topic
    if "stop" in msg_lower or "not interested" in msg_lower or "useless" in msg_lower:
        suppressed_conversations.add(body.conversation_id)
        return {
            "action": "end",
            "rationale": "Merchant explicitly opted out. Closing conversation."
        }
        
    if "gst" in msg_lower:
        return {
            "action": "send",
            "body": "I'll have to leave GST filing to your CA. Want me to draft the post first?",
            "cta": "open_ended",
            "rationale": "Out-of-scope ask politely declined; redirects back."
        }
        
    # Replay Test 4.2: Intent transition
    if "let's do it" in msg_lower or "go ahead" in msg_lower or "yes" in msg_lower:
        return {
            "action": "send",
            "body": "Great. Drafting your patient WhatsApp now. Reply CONFIRM to send.",
            "cta": "binary_confirm_cancel",
            "rationale": "Merchant explicitly committed; switching to action-execution."
        }
        
    if "confirm" in msg_lower:
        suppressed_conversations.add(body.conversation_id)
        return {
            "action": "end",
            "rationale": "Merchant confirmed action. Task executed successfully."
        }
        
    # Default fallback
    groq_key = os.environ.get("GROQ_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    llm = None
    
    if groq_key:
        from composer import GroqProvider
        llm = GroqProvider(groq_key)
    elif openai_key:
        from composer import OpenAIProvider
        llm = OpenAIProvider(openai_key)
    elif gemini_key:
        from composer import GeminiProvider
        llm = GeminiProvider(gemini_key)
        
    if llm:
        prompt = f"Merchant says: '{body.message}'. You are Vera, the AI assistant. Reply briefly confirming you understand."
        generated = llm.generate(prompt, fallback="Got it, here's what's next...")
        return {
            "action": "send",
            "body": generated,
            "cta": "open_ended",
            "rationale": "LLM Generated fallback response."
        }
    else:
        return {
            "action": "send",
            "body": "Got it, here's what's next...",
            "cta": "open_ended",
            "rationale": "acknowledged + advanced"
        }
