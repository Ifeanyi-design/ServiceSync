"""Build real in-app notifications from jobs + messages.

No separate notification table — items are derived from live data so the bell
never shows a permanent fake red dot. Unread message counts use Conversation
last_read cursors (set when a user opens chat).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.all_models import User, Job, Conversation, DirectMessage, Escrow


def _last_read_for(conv: Conversation, user_id: int) -> Optional[datetime]:
    if user_id == conv.customer_id:
        return getattr(conv, "last_read_at_customer", None)
    if user_id == conv.contractor_id:
        return getattr(conv, "last_read_at_contractor", None)
    return None


def _preview(text: Optional[str], limit: int = 80) -> str:
    if not text:
        return "Sent an attachment"
    t = text.strip()
    if t.startswith("[AI DRAFT"):
        return "AI draft ready to review"
    return t if len(t) <= limit else t[: limit - 1] + "…"


async def mark_conversation_read(
    db: AsyncSession,
    conv: Conversation,
    user_id: int,
) -> None:
    """Advance the user's read cursor to now (called when opening chat)."""
    now = datetime.utcnow()
    try:
        if user_id == conv.customer_id:
            conv.last_read_at_customer = now
        elif user_id == conv.contractor_id:
            conv.last_read_at_contractor = now
        else:
            return
        db.add(conv)
        await db.commit()
    except Exception:
        # Columns may be missing until `alembic upgrade head` — don't break chat.
        await db.rollback()


async def count_unread_messages(
    messages: List[DirectMessage],
    user_id: int,
    last_read: Optional[datetime],
) -> int:
    n = 0
    for m in messages:
        if m.sender_id == user_id:
            continue
        if last_read is None or (m.timestamp and m.timestamp > last_read):
            n += 1
    return n


async def build_conversation_list(
    db: AsyncSession,
    current_user: User,
) -> List[Dict[str, Any]]:
    """Enriched conversation rows for /messages and chat sidebar."""
    if current_user.role == "customer":
        query = (
            select(Conversation)
            .options(
                selectinload(Conversation.customer),
                selectinload(Conversation.contractor),
                selectinload(Conversation.messages),
            )
            .where(Conversation.customer_id == current_user.id)
        )
    elif current_user.role == "contractor":
        query = (
            select(Conversation)
            .options(
                selectinload(Conversation.customer),
                selectinload(Conversation.contractor),
                selectinload(Conversation.messages),
            )
            .where(Conversation.contractor_id == current_user.id)
        )
    else:
        return []

    result = await db.exec(query.order_by(Conversation.created_at.desc()))
    conversations_raw = result.all()
    conversations: List[Dict[str, Any]] = []

    for conv in conversations_raw:
        partner = conv.contractor if current_user.id == conv.customer_id else conv.customer
        if partner is None:
            partner_id = conv.contractor_id if current_user.id == conv.customer_id else conv.customer_id
            partner = await db.get(User, partner_id)

        job = await db.get(Job, conv.job_id)
        msgs = sorted(conv.messages or [], key=lambda m: m.timestamp or datetime.min)
        latest_msg = msgs[-1] if msgs else None
        last_read = _last_read_for(conv, current_user.id)
        unread = 0
        for m in msgs:
            if m.sender_id == current_user.id:
                continue
            if last_read is None or (m.timestamp and m.timestamp > last_read):
                unread += 1

        preview = _preview(latest_msg.content if latest_msg else None)
        if latest_msg and latest_msg.attachment_url and not (latest_msg.content or "").strip():
            kind = (latest_msg.attachment_type or "file").title()
            preview = f"📎 {kind}"

        is_mine = latest_msg and latest_msg.sender_id == current_user.id
        if is_mine and preview:
            preview = f"You: {preview}"

        conversations.append({
            "id": conv.id,
            "job_id": conv.job_id,
            "partner": partner,
            "job_status": job.status if job else None,
            "latest_message": preview,
            "latest_message_time": (
                latest_msg.timestamp.strftime("%b %d, %H:%M")
                if latest_msg and latest_msg.timestamp
                else conv.created_at.strftime("%b %d")
            ),
            "latest_timestamp": latest_msg.timestamp if latest_msg else conv.created_at,
            "created_at": conv.created_at,
            "unread_count": unread,
        })

    # Most recent activity first
    conversations.sort(
        key=lambda c: c.get("latest_timestamp") or c.get("created_at") or datetime.min,
        reverse=True,
    )
    return conversations


async def build_notifications(
    db: AsyncSession,
    current_user: User,
    *,
    limit: int = 20,
) -> Dict[str, Any]:
    """Return actionable notifications + unread badge count."""
    items: List[Dict[str, Any]] = []

    # --- Unread messages (one entry per conversation with unread) ---
    convs = await build_conversation_list(db, current_user)
    for c in convs:
        if c["unread_count"] <= 0:
            continue
        partner = c.get("partner")
        name = partner.full_name if partner else "Someone"
        n = c["unread_count"]
        items.append({
            "id": f"msg:{c['id']}",
            "kind": "message",
            "title": f"Message from {name}",
            "body": c["latest_message"] or f"{n} new message{'s' if n != 1 else ''}",
            "href": f"/chat/{c['id']}",
            "time": c["latest_message_time"],
            "unread": True,
        })

    # --- Job actions that need the current user ---
    if current_user.role == "customer":
        jobs_q = select(Job).where(Job.customer_id == current_user.id)
    elif current_user.role == "contractor":
        jobs_q = select(Job).where(Job.assigned_contractor_id == current_user.id)
    else:
        jobs_q = None

    if jobs_q is not None:
        jobs_result = await db.exec(jobs_q.order_by(Job.created_at.desc()).limit(40))
        jobs = jobs_result.all()
        for job in jobs:
            # Find chat link if any
            conv_result = await db.exec(select(Conversation).where(Conversation.job_id == job.id))
            conv = conv_result.first()
            chat_href = f"/chat/{conv.id}" if conv else (
                f"/dashboard/customer" if current_user.role == "customer" else "/dashboard/contractor"
            )

            if current_user.role == "customer":
                if job.status == "completed_pending":
                    items.append({
                        "id": f"job:{job.id}:completed_pending",
                        "kind": "job",
                        "title": "Confirm completed work",
                        "body": f"Job #{job.id} is waiting for your approval to release payment.",
                        "href": chat_href,
                        "time": (job.completed_at or job.created_at).strftime("%b %d, %H:%M")
                        if (job.completed_at or job.created_at) else "",
                        "unread": True,
                    })
                elif job.status == "booked":
                    e_result = await db.exec(select(Escrow).where(Escrow.job_id == job.id))
                    escrow = e_result.first()
                    if not escrow or escrow.status not in ("held", "released", "in_progress"):
                        items.append({
                            "id": f"job:{job.id}:pay",
                            "kind": "payment",
                            "title": "Secure escrow payment",
                            "body": f"Job #{job.id} is booked — pay to hold funds in escrow.",
                            "href": f"/jobs/{job.id}/pay",
                            "time": job.created_at.strftime("%b %d, %H:%M") if job.created_at else "",
                            "unread": True,
                        })
            elif current_user.role == "contractor":
                if job.status == "booked":
                    items.append({
                        "id": f"job:{job.id}:start",
                        "kind": "job",
                        "title": "Job ready to start",
                        "body": f"Job #{job.id} is booked — open chat and start when you're on site.",
                        "href": chat_href,
                        "time": job.created_at.strftime("%b %d, %H:%M") if job.created_at else "",
                        "unread": True,
                    })
                elif job.status == "completed_pending":
                    items.append({
                        "id": f"job:{job.id}:awaiting",
                        "kind": "job",
                        "title": "Awaiting customer confirmation",
                        "body": f"Job #{job.id} marked complete — payment releases after customer confirms.",
                        "href": chat_href,
                        "time": (job.completed_at or job.created_at).strftime("%b %d, %H:%M")
                        if (job.completed_at or job.created_at) else "",
                        "unread": True,
                    })

            # Disputed escrow (both parties)
            e_result = await db.exec(select(Escrow).where(Escrow.job_id == job.id))
            escrow = e_result.first()
            if escrow and escrow.status == "disputed":
                items.append({
                    "id": f"escrow:{escrow.id}:disputed",
                    "kind": "dispute",
                    "title": "Escrow dispute open",
                    "body": f"Job #{job.id} has an open dispute. Review details and respond.",
                    "href": f"/jobs/{job.id}/escrow" if False else chat_href,
                    "time": job.created_at.strftime("%b %d, %H:%M") if job.created_at else "",
                    "unread": True,
                })

    # Deduplicate by id, keep order: messages first already, then jobs
    seen = set()
    unique: List[Dict[str, Any]] = []
    for it in items:
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        unique.append(it)

    unique = unique[:limit]
    unread_count = sum(1 for it in unique if it.get("unread"))
    # Sum of unread *messages* across conversations (for nav Messages badge)
    messages_unread_count = sum(c.get("unread_count", 0) or 0 for c in convs)
    return {
        "items": unique,
        "unread_count": unread_count,
        "messages_unread_count": messages_unread_count,
    }
