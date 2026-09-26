import re
from typing import Dict, Any, Optional

class LLMProvider:
    def generate(self, prompt: str) -> str:
        raise NotImplementedError

class TemplateProvider(LLMProvider):
    """Fallback provider using deterministic templates when no real LLM is configured."""
    def generate(self, prompt: str) -> str:
        # Simple template behavior based on prompt hints
        return "Generated based on templates."

import json
import urllib.request

class GeminiProvider(LLMProvider):
    """Real LLM integration using Gemini."""
    def __init__(self, api_key: str):
        self.api_key = api_key
        
    def generate(self, prompt: str, fallback: str = "Generated based on templates.") -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.api_key}"
        body = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.4}
        }).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read().decode("utf-8"))
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            print(f"LLM API Error: {e}")
            return fallback

class OpenAIProvider(LLMProvider):
    """Real LLM integration using OpenAI (ChatGPT)."""
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.api_key = api_key
        self.model = model
        
    def generate(self, prompt: str, fallback: str = "Generated based on templates.") -> str:
        url = "https://api.openai.com/v1/chat/completions"
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.4
        }).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        })
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"OpenAI API Error: {e}")
            return fallback

class GroqProvider(LLMProvider):
    """Real LLM integration using Groq (Llama)."""
    def __init__(self, api_key: str, model: str = "qwen/qwen3.8-27b"):
        self.api_key = api_key
        self.model = model
        
    def generate(self, prompt: str, fallback: str = "Generated based on templates.") -> str:
        url = "https://api.groq.com/openai/v1/chat/completions"
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.4,
            "max_tokens": 200
        }).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "Mozilla/5.0"
        })
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"Groq API Error: {e}")
            return fallback

def validate_message(msg: Dict[str, Any], category: Dict[str, Any]) -> Dict[str, Any]:
    """Guardrails layer for output schemas, URLs, and vocabulary taboos."""
    body = msg.get("body", "")
    rationale = msg.get("rationale", "")
    
    # Strip URLs unless explicitly allowed (for now, strip all generically)
    url_pattern = re.compile(r'https?://\S+')
    if url_pattern.search(body):
        body = url_pattern.sub("[URL REDACTED]", body)
        rationale += " [Guardrail: Removed generic URL]."
        
    # Vocabulary taboos
    taboos = category.get("voice", {}).get("vocab_taboo", [])
    for taboo in taboos:
        # Case insensitive replace
        pattern = re.compile(re.escape(taboo), re.IGNORECASE)
        if pattern.search(body):
            body = pattern.sub("[REDACTED]", body)
            rationale += f" [Guardrail: Removed taboo '{taboo}']."
            
    msg["body"] = body
    msg["rationale"] = rationale
    
    # Valid CTA values
    valid_ctas = {"open_ended", "binary_yes_no", "binary_confirm_cancel", "multi_choice_slot", "none"}
    if msg.get("cta") not in valid_ctas:
        msg["cta"] = "open_ended"
        msg["rationale"] += " [Guardrail: Defaulted CTA to open_ended]."
        
    # Valid Send_As values
    valid_send_as = {"vera", "merchant_on_behalf"}
    if msg.get("send_as") not in valid_send_as:
        msg["send_as"] = "vera"
        
    return msg

def compose(
    category: Dict[str, Any],
    merchant: Dict[str, Any],
    trigger: Dict[str, Any],
    customer: Optional[Dict[str, Any]] = None,
    provider: Optional[LLMProvider] = None
) -> Dict[str, Any]:
    """Deterministic message engine composer."""
    if provider is None:
        provider = TemplateProvider()
        
    kind = trigger.get("kind")
    scope = trigger.get("scope")
    suppression_key = trigger.get("suppression_key", "")
    
    merchant_name = merchant.get("identity", {}).get("name", "Merchant")
    owner_name = merchant.get("identity", {}).get("owner_first_name", "Owner")
    
    # Compose logic
    body = f"Hi {owner_name}, this is Vera."
    cta = "open_ended"
    send_as = "vera"
    rationale = f"Composed from category+merchant+trigger ({kind})"
    
    if scope == "customer" and customer:
        send_as = "merchant_on_behalf"
        cust_name = customer.get("identity", {}).get("name", "Customer")
        if kind == "recall_due":
            due_date = trigger.get("payload", {}).get("due_date", "soon")
            body = f"Hi {cust_name}, {merchant_name} here. It's time for your 6-month recall due around {due_date}. We have slots on Wed 6pm or Thu 5pm. Reply 1 for Wed, 2 for Thu."
            cta = "multi_choice_slot"
            rationale = "Customer-scoped recall, sending via merchant's number. Multi-choice slot CTA for booking flows."
        else:
            body = f"Hi {cust_name}, {merchant_name} here."
    elif scope == "merchant":
        if kind == "research_digest":
            top_item = trigger.get("payload", {}).get("top_item_id", "latest update")
            body = f"{owner_name}, a new research digest is out ({top_item}). Want me to pull it + draft a patient-ed WhatsApp you can share?"
            cta = "open_ended"
            rationale = "External research digest with merchant-relevant anchor. Open-ended CTA."
        elif kind == "curious_ask_due":
            body = f"Hi {owner_name}! Quick check — what service has been most asked-for this week at {merchant_name}?"
            cta = "open_ended"
            rationale = "Low-stakes question. Asking-the-merchant lever."
        elif kind == "active_planning_intent":
            topic = trigger.get("payload", {}).get("intent_topic", "package")
            body = f"{owner_name}, here's a starter version for your {topic} — you can edit: [Draft Package]. Want me to draft a 3-line WhatsApp to send to clients?"
            cta = "binary_confirm_cancel"
            rationale = "Direct continuation of merchant's planning intent. Concrete deliverables."
        elif kind == "regulation_change":
            deadline = trigger.get("payload", {}).get("deadline_iso", "soon")
            body = f"{owner_name}, new regulation update for your category. Effective deadline is {deadline}. Want me to summarize the changes?"
            cta = "binary_yes_no"
            rationale = "Important compliance update. Specific deadline."

    if not isinstance(provider, TemplateProvider):
        prompt = f"Write a 1 to 2 sentence proactive text message. Tone: Friendly, professional. Context: {rationale}. Base template idea: '{body}'. Ensure the call-to-action matches the type: {cta}. Don't use any bracketed placeholders."
        body = provider.generate(prompt, fallback=body)

    msg = {
        "body": body,
        "cta": cta,
        "send_as": send_as,
        "suppression_key": suppression_key,
        "rationale": rationale
    }
    
    # Pass through guardrails
    return validate_message(msg, category)
