# ServiceSync — Product Requirements Document

## 1. Vision

ServiceSync is a global, AI-native home services marketplace that helps customers describe problems in plain language, find verified contractors, communicate safely, and pay through escrow protection.

The product exists to solve a trust problem:

- Customers do not know which contractors are reliable.
- Contractors do not know whether customers will show up or pay.
- Both sides lose time in inefficient discovery, negotiation, and dispute handling.

ServiceSync combines:

1. Natural language AI concierge.
2. Verified contractor profiles.
3. Escrow-protected payments.
4. Messaging and contractor automation.
5. Later-stage BizLive video portfolios.

## 2. Product Positioning

### XPRIZE Pitch

> ServiceSync is an AI-powered contractor marketplace that uses natural language search, verified professionals, global location matching, and escrow payments to make hiring home service providers safer and faster.

### One-Sentence Value Proposition

ServiceSync makes hiring a contractor feel as safe, fast, and transparent as booking a premium marketplace service.

### Core Differentiators

| Differentiator | Why It Matters |
|---|---|
| AI Concierge | Customers can describe problems naturally instead of searching through rigid categories. |
| Global Location Model | Service is not locked to US ZIP codes. |
| Escrow Protection | Money is protected until work is completed or a dispute is resolved. |
| Verification Tiers | Customers can quickly understand contractor trust level. |
| Contractor ERP-Lite | Contractors get dispatch, messaging, availability, and payout control. |
| BizLive | Contractors can turn work into proof-of-skill video content later. |

## 3. Target Users

### Customer

#### Needs
- Find the right professional quickly.
- Understand urgency.
- Compare trust signals.
- Avoid scams or unfinished work.
- Pay safely.
- Resolve disputes fairly.

#### Jobs To Be Done
- “I need help now.”
- “I want someone trustworthy near me.”
- “I want to know what this job might cost.”
- “I want my money protected.”
- “I want proof that the contractor is qualified.”

### Contractor

#### Needs
- Receive qualified leads.
- Avoid wasting time on fake bookings.
- Control availability.
- Respond faster.
- Get paid reliably.
- Build a premium public profile.
- Show proof of work.

#### Jobs To Be Done
- “Show me jobs I can actually take.”
- “Help me respond to customers faster.”
- “Protect me from no-show customers.”
- “Help me prove I am trustworthy.”
- “Help me get more bookings without paying for bad leads.”

### Admin

#### Needs
- Approve verification documents.
- Review disputes.
- Manage users.
- Configure platform rules.
- Monitor marketplace health.

### XPRIZE Judge / Reviewer

#### Needs
- Understand the product in under one minute.
- See a working end-to-end flow.
- Understand why AI matters.
- Understand why escrow matters.
- See that the product can scale globally.

## 4. MVP Scope

### Must Have

| Feature | Description |
|---|---|
| Global location model | Country, state/province, city, area, postal code, optional lat/long. |
| AI Concierge | Extracts service category, urgency, location, and readiness. |
| Contractor profiles | Name, profession, pricing, qualifications, badges, reviews, reputation score. |
| Search and matching | Match by trade, location, radius, availability, and capacity. |
| Booking | Customer can select contractor and create booking. |
| Escrow status | Mock or real escrow state visible to both parties. |
| Messaging | Customer and contractor can communicate after booking. |
| Contractor dashboard | Active jobs, inquiries, availability, payout status. |
| Customer dashboard | Open jobs, booked jobs, chat links, escrow status. |
| Verification tiers | Bronze, Silver, Gold, Verified Pro. |
| Emergency flag | AI detects urgent cases and boosts priority. |
| Availability | Contractor can mark Available, Busy, Away, or Vacation. |
| Dispute simulation | Escrow can freeze and AI can recommend a refund split. |

### Should Have

| Feature | Description |
|---|---|
| AI job estimator | Upload photo and receive expected price range. |
| Rich reputation score | Completion %, on-time %, response time, dispute rate. |
| AI reply drafts | Contractor can approve or edit AI-generated responses. |
| Webhook alerts | Email, WhatsApp, or SMS lead notifications. |
| Reviews with photos | Verified reviews attached to completed jobs. |
| Admin verification queue | Admin approves documents and badges. |

### Could Have

| Feature | Description |
|---|---|
| Contractor bidding | Contractors submit quotes for open jobs. |
| Milestone payments | Larger jobs split into phases. |
| Dynamic pricing alerts | Demand-based pricing suggestions. |
| Team routing | Dispatch multiple workers from one contractor business. |
| AI analytics | Demand forecasting and conversion insights. |

### Won’t Have in MVP

| Feature | Reason |
|---|---|
| Full BizLive streaming | Too much scope for MVP. |
| AI auto-clipping | Defer to premium phase. |
| Full AI arbitration | Start with AI recommendation, admin override. |
| Full international payment compliance | Start with escrow simulation and provider stubs. |
| Complex multi-city operations | Start with one or two launch markets. |

## 5. Global-First Requirements

### Current Problem

The AI currently says it only serves the United States and requires a 5-digit ZIP code.

### Required Change

Replace ZIP-only logic with global location fields:

```text
country
state_or_province
city
area
postal_code
latitude
longitude
```

### Location Rules

| Market | Behavior |
|---|---|
| Nigeria | Accept Lagos, Ikeja, Lekki, etc. without ZIP requirement. |
| UK | Accept postcode format but do not require US ZIP. |
| Canada | Accept postal code format with spaces. |
| Australia | Accept flexible postal formats. |
| India | Accept PIN code or city/area only. |
| US | Support 5-digit ZIP as a special case, not the only case. |

### Matching Rules

- If lat/long exists, use distance calculation.
- If lat/long is missing, fall back to city + area + service radius.
- If postal code is missing, still allow coarse matching by city/country.
- Never reject a user solely because they lack a US ZIP code.

## 6. AI Requirements

### AI Concierge

#### Inputs
- Conversation history.
- Optional image.
- User location.
- Contractor profile data.

#### Outputs
- `profession_required`
- `urgency`
- `country`
- `state_or_province`
- `city`
- `area`
- `postal_code`
- `is_emergency`
- `ready_for_match`
- `bot_reply`
- `matched_contractor_ids`

#### Guardrails
- Must return structured JSON only.
- Must not invent contractor licenses.
- Must ask for missing location if required.
- Must distinguish emergency from non-emergency.
- Must not claim global coverage if contractor supply is unavailable.

### AI Chat Assistant

#### Inputs
- Customer message.
- Contractor profile.
- Contractor rules.
- AI autonomy level.
- Pricing rules.

#### Outputs
- Draft reply.
- Optional booking suggestion.
- Optional escalation to human.

#### Guardrails
- Contractor can approve, edit, or reject AI replies.
- AI must follow contractor pricing and tone.
- AI must not promise unavailable services.
- AI must not override escrow rules.

### AI Dispute Recommendation

#### Inputs
- Chat history.
- Job description.
- Uploaded photos.
- Escrow amount.
- Cancellation reason.
- Contractor/customer claims.

#### Outputs
- Summary.
- Recommended refund percentage.
- Evidence bullets.
- Confidence level.
- Admin review flag.

#### Guardrails
- AI recommendation is advisory.
- Admin can override.
- Escrow remains frozen until resolved.
- Decision log must be auditable.

## 7. Escrow Requirements

### Payment Flow

1. Customer books contractor.
2. Payment is captured or simulated.
3. Escrow record is created with status `held`.
4. Job status becomes `scheduled`.
5. Contractor completes job.
6. Customer confirms or dispute starts.
7. Escrow releases, refunds, or splits.

### Escrow States

| State | Meaning |
|---|---|
| `held` | Funds locked. |
| `released` | Funds paid to contractor and platform. |
| `refunded` | Funds returned to customer. |
| `penalty_split` | Funds split between customer refund, contractor compensation, and platform fee. |
| `disputed` | Funds frozen pending review. |

### Money Rules

- Use `Decimal`, not `float`.
- Store currency explicitly.
- Round to two decimals.
- Log all transitions.
- Never allow double release.
- Never allow payout before escrow is held.

### Cancellation Rules

| Scenario | Outcome |
|---|---|
| Contractor no-show | Full refund to customer. |
| Customer cancels early | Full refund to customer. |
| Customer cancels late | Partial refund + contractor compensation + platform fee. |
| Mutual cancellation | Configurable split. |
| Disputed cancellation | Escrow frozen until review. |

## 8. Contractor Profile Requirements

### Public Profile Sections

1. Header
   - Name
   - Owner
   - Location
   - Rating
   - Verification tier

2. Trust Badges
   - ID verified
   - License verified
   - Insurance verified
   - Background checked
   - Verified Pro

3. Services
   - Trade categories
   - Emergency availability
   - Service radius
   - Qualifications

4. Pricing
   - Call-out fee
   - Hourly rate
   - Estimated range
   - Escrow explanation

5. Availability
   - Available / Busy / Away / Vacation
   - Working hours
   - Response time

6. Proof of Work
   - Photos
   - Reviews
   - Completed jobs
   - BizLive placeholder

7. CTAs
   - Book Now (Escrow Secured)
   - Message Contractor

### Recommended Layout

Use a two-column layout:

- Left column: trust-building content.
- Right column: sticky booking and messaging CTA.

## 9. Reputation Requirements

### Metrics

| Metric | Source |
|---|---|
| Average rating | Customer reviews |
| Completion rate | Completed jobs / accepted jobs |
| On-time rate | Arrival time vs scheduled time |
| Average response time | First reply timestamp |
| Dispute rate | Disputed jobs / completed jobs |
| Verified review count | Completed-job reviews |
| Repeat customer rate | Returning customers |

### Display Format

```text
4.9 Rating
98% Completion
95% On-Time
2hr Average Response
128 Verified Reviews
```

## 10. BizLive Requirements

### Recommendation

Keep BizLive as a future premium feature.

### Why Defer
- Streaming infrastructure adds complexity.
- AI clipping requires media processing.
- Marketplace liquidity must be proven first.
- XPRIZE judges need core trust flow before advanced media.

### Future Scope
- Livestream session.
- Contractor live dashboard.
- Public profile video player.
- AI 30-second clip generation.
- Before/after clip gallery.
- Export to TikTok, Reels, YouTube Shorts.
- Booking link embedded in clips.

## 11. Monetization

### Free Tier

- Free to join.
- Higher commission per completed job.
- Basic profile.
- Ads on public profile pages.

### Premium Tier

- Reduced or 0% commission.
- Boosted ranking.
- Advanced analytics.
- AI Copilot.
- BizLive tools when launched.
- Priority verification review.
- Dynamic pricing alerts.

### Trial

- 14-day Premium trial for new contractors.

## 12. Success Metrics

| Metric | Target |
|---|---|
| Time to first match | Under 30 seconds |
| AI triage success | 85%+ ready_for_match accuracy |
| Contractor response time | Under 2 hours average |
| Escrow dispute resolution | Under 5 minutes for AI recommendation |
| Job completion rate | 95%+ |
| Verified contractor conversion | Premium/Verified profiles convert higher than unverified |
| Global test coverage | Nigeria, UK, Canada, Australia, India, US |
| User trust score | 4.5/5+ after booking flow |

## 13. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| US-only assumptions | Replace ZIP with global location schema and prompt. |
| AI hallucination | Structured JSON, validation, audit logs, fallback manual flow. |
| Escrow regulation | Start with mock escrow; integrate compliant provider later. |
| Contractor liquidity | Seed launch market with verified demo contractors. |
| BizLive scope creep | Defer to Phase 8. |
| Disintermediation | Escrow, warranties, reviews, and in-app communication incentives. |
| Payment complexity | Abstract gateway interface for Stripe, Grey, Paxum, or local providers. |
| Bad leads for contractors | Availability, capacity, reputation, and AI triage filters. |

## 14. Technical Requirements

### Backend
- FastAPI
- SQLModel
- Async PostgreSQL
- SQLAlchemy async session
- Gemini SDK
- WebSocket chat
- Jinja2 templates
- Decimal-based escrow math

### Frontend
- Jinja2 templates for MVP.
- Optional React/Tailwind contractor profile later.
- Cookie-based auth.
- Responsive design.
- Mobile-first customer flow.

### Data Privacy
- Do not expose API keys.
- Do not log secrets.
- Hash passwords.
- Store verification documents securely.
- Restrict admin access.

### Auditability
- Log AI prompts and responses.
- Log escrow transitions.
- Log admin decisions.
- Log dispute recommendations.

## 15. MVP Acceptance Criteria

The MVP is successful when:

- A customer in Nigeria can use the AI concierge.
- A customer can search and book a contractor.
- A contractor profile communicates trust clearly.
- Escrow status is visible and deterministic.
- Messaging works after booking.
- AI does not require US ZIP codes.
- BizLive is documented but not required for MVP.
- The XPRIZE demo can be completed in under 5 minutes.
