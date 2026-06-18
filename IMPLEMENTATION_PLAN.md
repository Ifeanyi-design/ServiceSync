# ServiceSync — XPRIZE Implementation Plan

## Executive Direction

ServiceSync should be positioned as:

> An AI-powered contractor marketplace that uses natural language search, verified professionals, global location matching, and escrow payments to make hiring home service providers safer and faster.

The plan is strong, but the MVP must be focused. The winning angle is **Trust + Escrow + AI Concierge**, not every possible feature at once.

## Strategic Decisions

| Decision | Direction |
|---|---|
| Global availability | Build global-first. Replace US-only ZIP logic with country, state/province, city, area, postal code, latitude, longitude. |
| BizLive | Keep it in the master plan, but defer implementation until Phase 8 unless a lightweight demo is needed for judges. |
| AI scope | Keep AI Concierge and AI Chat Assistant in MVP. Defer AI arbitration, AI scheduling, AI clipping, and AI analytics. |
| Core trust layer | Make escrow, verification tiers, and reputation scores central to the product story. |
| Contractor experience | Treat ServiceSync as ERP-lite for contractors: dispatch board, availability, messaging, lead quality, payout status. |
| User experience | Use a premium two-column contractor profile: left side builds trust, right side converts with escrow CTA. |

## Research-Informed Improvements

Current home-services marketplace patterns show that users and contractors care most about:

1. **Verified trust** — ID, licenses, insurance, background checks, completed jobs.
2. **Payment protection** — escrow, milestone release, dispute mediation, no unfinished-work risk.
3. **Fast matching** — availability, service radius, emergency response, response-time badges.
4. **Transparent pricing** — AI estimate ranges, material/labor breakdown, historical pricing.
5. **Contractor ROI** — fewer bad leads, faster replies, automated follow-up, no per-lead gouging.
6. **Hyperlocal density** — launch city-by-city before claiming full global liquidity.

These themes should be reflected in the XPRIZE pitch and roadmap.

---

## Phase 1 — Foundation

### Goal
Create the core platform foundation and global-first data model.

### Scope
- Global location model:
  - `country`
  - `state_or_province`
  - `city`
  - `area`
  - `postal_code`
  - `latitude`
  - `longitude`
- Remove US-only ZIP assumptions.
- User roles:
  - customer
  - contractor
  - admin
- Auth:
  - login
  - signup
  - protected routes
  - cookie/session handling
- Basic profiles:
  - contractor name
  - profession
  - service radius
  - base pricing
  - working hours
  - AI tone preference
- Basic job model:
  - customer
  - assigned contractor
  - description
  - status
  - created_at

### Current Code Context
Existing files already contain the first version of this foundation:

- `app/models/all_models.py`
- `app/api/v1/endpoints/auth.py`
- `app/api/v1/endpoints/jobs.py`
- `app/api/v1/endpoints/chat.py`
- `app/web/pages.py`
- `app/web/auth_pages.py`

### Acceptance Criteria
- A user in Lagos, Nigeria can enter a location without being rejected.
- Contractor search does not require a 5-digit US ZIP code.
- A customer can create or match to a job.
- A contractor can appear in search results.
- A customer can book a contractor and create a conversation.

### Key Files To Update
- `app/models/all_models.py`
- `app/schemas/user.py`
- `app/schemas/job.py`
- `app/services/matching_engine.py`
- `app/services/gemini_service.py`
- `app/api/v1/endpoints/jobs.py`

---

## Phase 2 — Marketplace

### Goal
Turn the platform into a functioning local service marketplace.

### Scope
- Contractor listing and public profile pages.
- Customer job search.
- AI-assisted manual search.
- Matching engine:
  - profession
  - city/area
  - radius
  - availability
  - daily capacity
  - reputation score
- Contractor dashboard:
  - active jobs
  - matched leads
  - messages
  - availability
  - payout summary
- Customer dashboard:
  - open jobs
  - booked jobs
  - chat links
  - escrow status

### Profile UX Direction
Use a two-column asymmetric profile layout:

#### Left Column — Trust Builder
- Contractor name and owner.
- Verified badges.
- Rating and review count.
- About section.
- Qualifications.
- Reviews.
- BizLive/portfolio placeholder for later.

#### Right Column — Conversion Engine
- Sticky pricing card.
- Primary CTA: `Book Now (Escrow Secured)`.
- Secondary CTA: `Message Contractor`.
- AI metadata:
  - `Usually responds in under 1 minute (AI-assisted)`.
  - `Verified Pro`.
  - `Escrow protected`.

### Acceptance Criteria
- Customer can search by trade and location.
- Customer can view contractor profile.
- Contractor can see assigned jobs.
- Customer can send inquiry or book.
- AI can recommend contractors with trust anchors.

---

## Phase 3 — Escrow

### Goal
Make the financial trust layer explicit, safe, and demo-ready.

### Scope
Create three core models:

#### Job
Tracks service lifecycle.

Suggested statuses:
- `pending_payment`
- `scheduled`
- `in_progress`
- `completed`
- `cancelled`
- `disputed`

#### Escrow
Tracks money state and exact splits.

Suggested statuses:
- `held`
- `released`
- `refunded`
- `penalty_split`

Financial fields:
- `total_amount`
- `platform_fee`
- `contractor_payout`
- `customer_refund`
- `payment_gateway_id`
- `payout_reference_id`
- `currency`

#### Dispute
Tracks refund/refund split cases.

Suggested statuses:
- `pending_ai`
- `reviewing`
- `resolved`

Fields:
- `reason`
- `ai_arbitration_summary`
- `ai_recommended_refund_pct`
- `resolved_at`

### Business Rules
- Use `Decimal`, not `float`, for all money values.
- Customers fund escrow before job starts.
- Contractor no-show:
  - full refund to customer.
- Late bad-faith customer cancellation:
  - refund remainder to customer.
  - pay contractor compensation.
  - keep platform handling fee.
- Completed job:
  - release contractor payout.
  - record platform fee.
- Disputed job:
  - freeze escrow.
  - AI generates recommendation.
  - admin can approve or override.

### Acceptance Criteria
- Escrow record is created on booking/payment.
- Completion releases funds correctly.
- Contractor cancellation refunds customer.
- Late customer cancellation splits funds.
- Dispute freezes escrow and stores AI recommendation.
- Platform fee and contractor payout are exact to two decimals.

### Key Files To Add/Update
- Add `app/models/escrow.py` or expand `all_models.py`.
- Add `app/services/escrow_service.py`.
- Add `app/services/payout_gateway.py`.
- Add API endpoints under `app/api/v1/endpoints/escrow.py`.

---

## Phase 4 — AI Concierge

### Goal
Harden the AI layer so it is useful, global, auditable, and focused.

### Current Issue
`app/services/gemini_service.py` currently extracts:

- `profession_required`
- `urgency`
- `zip_code`

This is the reason the AI rejected Lagos, Nigeria.

### Required AI Prompt Changes
The triage prompt must extract:

- `country`
- `state_or_province`
- `city`
- `area`
- `postal_code`
- `profession_required`
- `urgency`
- `is_emergency`
- `ready_for_match`
- `bot_reply`

### MVP AI Features
- Natural language triage.
- Missing-information follow-up.
- Contractor trust-anchor explanations.
- Emergency detection.
- AI estimate range placeholder.

### Defer Until Later
- Full AI arbitration.
- Full AI scheduling.
- AI video clipping.
- AI analytics.
- Autonomous dispatcher.

### Acceptance Criteria
- AI no longer requires US ZIP codes.
- AI can handle Nigerian, UK, Canadian, Australian, and Indian locations.
- AI returns structured JSON only.
- AI triage audit logs are stored.
- AI cannot invent verified credentials.

---

## Phase 5 — Messaging

### Goal
Make communication useful for both customers and contractors.

### Scope
- Conversation model.
- DirectMessage model.
- WebSocket chat.
- Cookie/session-based WebSocket auth.
- AI reply draft for contractors.
- Autonomy slider:
  - Level 1: manual only.
  - Level 2: AI drafts, human approves.
  - Level 3: AI replies within rules.
- Cross-platform lead alerts:
  - email
  - WhatsApp
  - SMS

### Current Code Context
Existing chat foundation:

- `app/models/all_models.py`
- `app/api/v1/endpoints/chat.py`
- `app/templates/chat.html`

### Acceptance Criteria
- Customer and contractor can chat after booking.
- WebSocket auth does not depend on frontend token injection.
- Contractor can pause AI.
- Contractor can approve AI drafts.
- Messages are available for dispute review.

---

## Phase 6 — Verification

### Goal
Create a trust ladder users can understand instantly.

### Verification Tiers
| Tier | Requirements |
|---|---|
| Bronze | Email, phone, basic ID check. |
| Silver | Government ID + profile completeness. |
| Gold | Trade license + insurance. |
| Verified Pro | License, insurance, background check, completed jobs, strong reputation score. |

### Reputation Score
Move beyond stars.

Suggested components:
- Average rating.
- Completion rate.
- On-time rate.
- Average response time.
- Dispute rate.
- Verified review count.
- Repeat customer rate.

Example:

```text
4.9 Rating
98% Completion
95% On-Time
2hr Average Response
128 Verified Reviews
```

### Acceptance Criteria
- Contractor profile shows verification tier.
- Admin can approve or reject verification documents.
- Reputation score updates after job completion.
- Search ranking can boost Verified Pros.
- Verification tier is visible in AI recommendations.

---

## Phase 7 — Premium Features

### Goal
Create monetization without hurting marketplace trust.

### Free Tier
- Permanent free access.
- Higher per-job commission.
- Basic profile.
- Non-intrusive ads on public contractor profile pages.

### Premium Tier
- 0% commission or reduced commission.
- Boosted search ranking.
- BizLive tools when launched.
- Dynamic pricing alerts.
- Advanced analytics.
- Priority verification review.
- AI Copilot automation.

### 14-Day Trial
New contractors get a trial period to experience premium ROI.

### Acceptance Criteria
- User subscription tier exists.
- Premium affects search ranking.
- Commission rules are configurable.
- Trial expiry is tracked.
- Ad-supported free tier does not break UX.

---

## Phase 8 — BizLive

### Goal
Add live-commerce video only after marketplace trust and booking are proven.

### Recommendation
Do not block MVP on BizLive. Keep it as the premium differentiator.

### Scope
- Livestream session model.
- Contractor live dashboard.
- Video player on contractor profile.
- AI-generated 30-second clips.
- Before/after clip gallery.
- Export/share to TikTok, Instagram Reels, YouTube Shorts.
- Booking link embedded in clips.

### Acceptance Criteria
- Contractor can start a live portfolio session.
- Customer can watch latest stream on profile.
- AI can generate clip candidates.
- Clip gallery is visible on profile.
- Video content links back to booking CTA.

---

## XPRIZE Demo Flow

Recommended demo sequence:

1. Customer opens ServiceSync from Lagos.
2. Customer says: “Water is pooling under my kitchen sink in Ikeja, Lagos.”
3. AI extracts:
   - trade: plumber
   - urgency: medium or emergency
   - city: Lagos
   - area: Ikeja
   - country: Nigeria
4. AI shows matched contractors with trust anchors.
5. Customer opens a contractor profile.
6. Profile shows:
   - rating
   - verification tier
   - reputation score
   - pricing
   - escrow CTA
   - message CTA
7. Customer books with escrow.
8. Chat opens.
9. Contractor dashboard shows the booked job.
10. Admin dispute/escrow flow is demonstrated with mock payout.

---

## Current Code Gaps

| Gap | File/Component | Priority |
|---|---|---|
| US-only ZIP extraction | `app/services/gemini_service.py` | Critical |
| ZIP-only distance matching | `app/services/matching_engine.py` | Critical |
| Missing global location fields | `app/models/all_models.py` | Critical |
| Escrow state machine | Not implemented | Critical |
| Verification tiers | Not implemented | High |
| Availability calendar | Not implemented | High |
| Emergency flag | Not implemented | High |
| AI job estimator | Not implemented | Medium |
| Reputation score | Not implemented | Medium |
| BizLive | Deferred | Low for MVP |

---

## Definition of Done for MVP

ServiceSync MVP is ready when:

- A customer can describe a problem naturally.
- AI extracts global location and service category.
- Customer can see relevant verified contractors.
- Contractor profile clearly communicates trust.
- Customer can book with escrow protection.
- Contractor can see booked jobs.
- Customer and contractor can chat.
- Escrow status is visible.
- Dispute flow can be simulated.
- Product story is focused enough for XPRIZE judges.
