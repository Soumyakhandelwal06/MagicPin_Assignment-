from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone
import logging

logger = logging.getLogger("vera-engine")

# Global suppression store
suppressed_keys = set()
# Conversation suppression (opt-outs)
suppressed_conversations = set()

def get_contexts(
    contexts_store: Dict[Tuple[str, str], Dict[str, Any]], 
    trigger_id: str
) -> Tuple[Optional[Dict], Optional[Dict], Optional[Dict], Optional[Dict]]:
    trigger_ctx = contexts_store.get(("trigger", trigger_id))
    if not trigger_ctx:
        return None, None, None, None
    trigger = trigger_ctx["payload"]
    
    merchant_id = trigger.get("merchant_id")
    merchant_ctx = contexts_store.get(("merchant", merchant_id))
    merchant = merchant_ctx["payload"] if merchant_ctx else None
    
    category_slug = merchant.get("category_slug") if merchant else None
    if not category_slug and trigger.get("payload", {}).get("category"):
        category_slug = trigger["payload"]["category"]
        
    category_ctx = contexts_store.get(("category", category_slug))
    category = category_ctx["payload"] if category_ctx else None
    
    customer_id = trigger.get("customer_id")
    customer = None
    if customer_id:
        customer_ctx = contexts_store.get(("customer", customer_id))
        customer = customer_ctx["payload"] if customer_ctx else None
        
    return category, merchant, trigger, customer

def evaluate_triggers(
    contexts_store: Dict[Tuple[str, str], Dict[str, Any]], 
    available_triggers: List[str],
    now_str: str
) -> List[str]:
    """Evaluates and sorts available triggers based on urgency, expiration, and suppression."""
    valid_triggers = []
    try:
        now = datetime.fromisoformat(now_str.replace("Z", "+00:00"))
    except ValueError:
        now = datetime.now(timezone.utc)
    
    for tid in available_triggers:
        cat, mch, trg, cust = get_contexts(contexts_store, tid)
        if not (cat and mch and trg):
            logger.warning(f"Trigger {tid} missing dependencies. Skipping.")
            continue
            
        # Check expiry
        expires_at_str = trg.get("expires_at")
        if expires_at_str:
            try:
                expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
                if now > expires_at:
                    logger.info(f"Trigger {tid} is expired. Skipping.")
                    continue
            except ValueError:
                logger.error(f"Invalid date format in {tid}: {expires_at_str}")
                
        # Check suppression
        supp_key = trg.get("suppression_key")
        merchant_id = trg.get("merchant_id")
        if supp_key and merchant_id and (merchant_id, supp_key) in suppressed_keys:
            logger.info(f"Trigger {tid} with key {supp_key} is suppressed for merchant {merchant_id}. Skipping.")
            continue
            
        valid_triggers.append((trg.get("urgency", 1), tid))
        
    # Sort by urgency descending
    valid_triggers.sort(key=lambda x: x[0], reverse=True)
    return [t[1] for t in valid_triggers]
