from google import genai
from google.genai import types
import json
import time
import logging
from typing import Dict, Any, Tuple, List, Optional
from app.core.config import settings

logger = logging.getLogger(__name__)

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
    try:
        response = await _client.aio.models.generate_content(
            model=_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
    except Exception as exc:
        logger.warning("Gemini triage call failed, using fallback: %s", exc)
        return _fallback_triage(), {
            "raw_response": f"Gemini error: {exc}",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "latency_ms": int((time.time() - start_time) * 1000),
            "status": "fallback",
        }
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

    try:
        response = await _client.aio.models.generate_content(
            model=_MODEL,
            contents=prompt,
        )
    except Exception as exc:
        logger.warning("Gemini contractor-reply call failed, using fallback: %s", exc)
        return "Thank you for your message. We'll get back to you shortly."
    return response.text or "Thank you for reaching out. We'll respond shortly."


async def analyze_dispute(
    chat_history: List[Dict[str, str]],
    dispute_reason: str,
    job_description: str,
    total_amount: str,
    photo_descriptions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Analyzes a dispute using Gemini to recommend a refund split.
    Returns structured JSON with recommended refund percentage and reasoning.
    """
    if _client is None:
        return _fallback_dispute_analysis()

    photo_context = ""
    if photo_descriptions:
        photo_context = f"\nPhoto evidence descriptions: {json.dumps(photo_descriptions, indent=2)}"

    prompt = f"""
    You are an AI dispute resolution analyst for a home service marketplace called ServiceSync.
    Analyze the following dispute and recommend a fair refund split between customer and contractor.

    Job Description: {job_description}
    Total Amount in Escrow: {total_amount}
    Dispute Reason: {dispute_reason}
    {photo_context}

    Chat History:
    {json.dumps(chat_history, indent=2)}

    Evaluate:
    1. Who is at fault? (customer, contractor, both, or unclear)
    2. Was the work partially completed? If so, estimate completion percentage.
    3. Were there quality issues? Severity?
    4. Were there communication failures?
    5. Is there evidence of no-show, delays, or contract breach?

    Output strictly valid JSON with the following structure:
    {{
        "recommended_refund_pct": <number 0-100>,
        "fault_party": "customer" | "contractor" | "both" | "unclear",
        "completion_estimate_pct": <number 0-100>,
        "quality_issues": <string describing quality problems if any>,
        "reasoning": <string explaining the recommendation in 2-3 sentences>,
        "confidence": "high" | "medium" | "low"
    }}

    Guidelines:
    - If contractor didn't show up or barely started: 90-100% refund
    - If work was poor quality and needs redo: 70-90% refund
    - If work was partially done but incomplete: 40-70% refund
    - If work was mostly done with minor issues: 10-40% refund
    - If work was completed satisfactorily: 0-10% refund
    - If customer is at fault (unreasonable demands, changed scope): 0-20% refund
    - Consider both parties' communication and professionalism

    Output strictly valid JSON with no markdown.
    """

    start_time = time.time()
    try:
        response = await _client.aio.models.generate_content(
            model=_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
    except Exception as exc:
        logger.warning("Gemini dispute-analysis call failed, using fallback: %s", exc)
        return {
            "analysis": _fallback_dispute_analysis(),
            "metadata": {
                "raw_response": f"Gemini error: {exc}",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "latency_ms": int((time.time() - start_time) * 1000),
                "status": "fallback",
            },
        }
    latency_ms = int((time.time() - start_time) * 1000)

    raw_text = response.text or ""
    try:
        extracted = json.loads(raw_text.replace("```json", "").replace("```", "").strip())
    except Exception:
        extracted = _fallback_dispute_analysis()

    usage = response.usage_metadata
    metadata = {
        "raw_response": raw_text,
        "prompt_tokens": getattr(usage, "prompt_token_count", 0) if usage else 0,
        "completion_tokens": getattr(usage, "candidates_token_count", 0) if usage else 0,
        "latency_ms": latency_ms,
    }

    return {"analysis": extracted, "metadata": metadata}


async def estimate_job_price(
    description: str,
    profession: str,
    location: Optional[Dict[str, str]] = None,
    photo_descriptions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Estimates a price range for a job based on description, profession, and location.
    Returns structured JSON with estimated price range and breakdown.
    """
    if _client is None:
        return _fallback_price_estimate()

    location_str = ""
    if location:
        parts = [location.get("city"), location.get("state_or_province"), location.get("country")]
        location_str = f"\nLocation: {', '.join(p for p in parts if p)}"

    photo_context = ""
    if photo_descriptions:
        photo_context = f"\nPhoto descriptions: {json.dumps(photo_descriptions, indent=2)}"

    prompt = f"""
    You are an AI pricing estimator for a home service marketplace called ServiceSync.
    Estimate a fair price range for the following job.

    Profession: {profession}
    Job Description: {description}
    {location_str}
    {photo_context}

    Consider:
    1. Typical labor rates for this profession in this region
    2. Materials and supplies likely needed
    3. Complexity and time estimates
    4. Market rates for similar jobs

    Output strictly valid JSON with the following structure:
    {{
        "estimated_min": <number>,
        "estimated_max": <number>,
        "estimated_midpoint": <number>,
        "currency": "USD",
        "breakdown": {{
            "labor_min": <number>,
            "labor_max": <number>,
            "materials_min": <number>,
            "materials_max": <number>
        }},
        "time_estimate_hours": <number>,
        "confidence": "high" | "medium" | "low",
        "notes": <string with any caveats or additional context>
    }}

    Output strictly valid JSON with no markdown.
    """

    start_time = time.time()
    try:
        response = await _client.aio.models.generate_content(
            model=_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
    except Exception as exc:
        logger.warning("Gemini price-estimate call failed, using fallback: %s", exc)
        return {
            "estimate": _fallback_price_estimate(),
            "metadata": {
                "raw_response": f"Gemini error: {exc}",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "latency_ms": int((time.time() - start_time) * 1000),
                "status": "fallback",
            },
        }
    latency_ms = int((time.time() - start_time) * 1000)

    raw_text = response.text or ""
    try:
        extracted = json.loads(raw_text.replace("```json", "").replace("```", "").strip())
    except Exception:
        extracted = _fallback_price_estimate()

    usage = response.usage_metadata
    metadata = {
        "raw_response": raw_text,
        "prompt_tokens": getattr(usage, "prompt_token_count", 0) if usage else 0,
        "completion_tokens": getattr(usage, "candidates_token_count", 0) if usage else 0,
        "latency_ms": latency_ms,
    }

    return {"estimate": extracted, "metadata": metadata}


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


def _fallback_dispute_analysis() -> Dict[str, Any]:
    return {
        "recommended_refund_pct": 50,
        "fault_party": "unclear",
        "completion_estimate_pct": 50,
        "quality_issues": "Unable to analyze — AI service unavailable",
        "reasoning": "AI analysis unavailable. Manual review recommended.",
        "confidence": "low",
    }


def _fallback_price_estimate() -> Dict[str, Any]:
    return {
        "estimated_min": 50,
        "estimated_max": 200,
        "estimated_midpoint": 125,
        "currency": "USD",
        "breakdown": {
            "labor_min": 40,
            "labor_max": 150,
            "materials_min": 10,
            "materials_max": 50,
        },
        "time_estimate_hours": 2,
        "confidence": "low",
        "notes": "AI estimation unavailable. Using default range.",
    }
