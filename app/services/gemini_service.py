from google import genai
from google.genai import types
import json
import time
from typing import Dict, Any, Tuple
from app.core.config import settings

# Initialize the new Gemini SDK client
_client = genai.Client(api_key=settings.GEMINI_API_KEY) if settings.GEMINI_API_KEY else None

_MODEL = settings.GEMINI_MODEL


async def extract_triage_info(conversation_history: list) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Analyzes customer chat to extract profession_required, urgency, and global location.
    Returns (triage_data, metadata_for_audit)
    """
    if _client is None:
        return _fallback_triage(), {"raw_response": "No API key", "prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0}

    prompt = f"""
    You are an AI triage bot for a home service marketplace.
    Analyze the following conversation history between the user and yourself.
    Extract the following structured JSON information:
    - "profession_required": e.g. "plumber", "electrician", "cleaner". Null if unknown.
    - "urgency": "low", "medium", "high", or "emergency". Null if unknown.
    - "is_emergency": boolean. True when the user describes urgent risk, flooding, fire, no power, lockout, gas leak, or same-day need.
    - "country": ISO country name or code if stated. Null if unknown.
    - "state_or_province": state, province, territory, or region if stated. Null if unknown.
    - "city": city or town if stated. Null if unknown.
    - "area": district, neighborhood, suburb, borough, or local area if stated. Null if unknown.
    - "postal_code": postal code, ZIP code, PIN code, or similar if stated. Null if unknown.
    - "latitude": number if explicitly provided, otherwise null.
    - "longitude": number if explicitly provided, otherwise null.
    - "ready_for_match": boolean. True only if profession_required is populated and at least one usable location field is populated.
    - "bot_reply": A string. If ready_for_match is false, write the next question to ask the user to gather the missing info. If true, write a custom recommendation for the best matched professionals based on the user's needs.

    ServiceSync is global. Do not assume the United States. Do not require a 5-digit ZIP code.
    Accept locations such as Lagos, Nigeria; Ikeja, Lagos; London, UK; Toronto, Ontario; Sydney NSW; New Delhi, India; or any city/country pair.
    If only city and country are provided, that is enough for coarse matching.
    If only country is provided, ask for city or area before matching.
    If the user provides a ZIP code, keep it in "postal_code" and also include it in "zip_code" for backward compatibility.

    You have access to the contractor's `trade_qualifications` JSON block. 
    When generating client triage matched comparisons, dynamically parse this object to find trust anchors. 
    - If plumbing and `gas_certified` is true, emphasize their capability to handle gas lines safely.
    - If HVAC and `epa_cert_num` is present, subtly highlight their certified environmental/refrigerant compliance.
    Incorporate these qualifications into your conversational recommendations to reinforce why they are the optimal match.

    Output strictly valid JSON with no markdown.

    Conversation History:
    {json.dumps(conversation_history, indent=2)}
    """

    start_time = time.time()
    response = await _client.aio.models.generate_content(
        model=_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    latency_ms = int((time.time() - start_time) * 1000)

    raw_text = response.text or ""
    try:
        extracted = json.loads(raw_text.replace("```json", "").replace("```", "").strip())
    except Exception:
        extracted = _fallback_triage()

    usage = response.usage_metadata
    metadata = {
        "raw_response": raw_text,
        "prompt_tokens": getattr(usage, "prompt_token_count", 0) if usage else 0,
        "completion_tokens": getattr(usage, "candidates_token_count", 0) if usage else 0,
        "latency_ms": latency_ms,
    }

    return extracted, metadata


async def generate_contractor_reply(customer_message: str, contractor_context: dict) -> str:
    """
    Prompts Gemini to respond to a customer message as an omnichannel bot
    representing a specific contractor, using their configured AI tone.
    """
    if _client is None:
        return "Thank you for your message. We'll get back to you shortly."

    tone = contractor_context.get("ai_tone_preference", "professional")
    rules = json.dumps(contractor_context, indent=2)

    prompt = f"""
    You are an AI assistant managing communications for a home service professional.
    You must adopt a {tone} tone in all responses.

    Contractor Rules & Context:
    {rules}

    Customer Message:
    {customer_message}

    Respond appropriately to the customer on behalf of the contractor,
    adhering strictly to their rules and pricing.
    """

    response = await _client.aio.models.generate_content(
        model=_MODEL,
        contents=prompt,
    )
    return response.text or "Thank you for reaching out. We'll respond shortly."


def _fallback_triage() -> Dict[str, Any]:
    return {
        "profession_required": None,
        "urgency": None,
        "is_emergency": False,
        "zip_code": None,
        "country": None,
        "state_or_province": None,
        "city": None,
        "area": None,
        "postal_code": None,
        "latitude": None,
        "longitude": None,
        "ready_for_match": False,
        "bot_reply": "I'm having trouble understanding. Could you describe your problem, urgency level, and your city or area?",
    }
