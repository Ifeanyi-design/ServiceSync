# ServiceSync — Development Log

## Active Direction

- Product: AI-powered contractor marketplace.
- Core pitch: natural language search + verified professionals + escrow payments.
- Global-first: remove US-only ZIP assumptions.
- BizLive: keep in master plan, defer from MVP.
- MVP focus: AI Concierge, profiles, booking, escrow, messaging, verification basics.

---

## Completed Work

| Date | Feature | Status | Notes | Issues |
|---|---|---|---|---|
| 2026-06-17 | FastAPI application foundation | Completed | App starts with `uvicorn app.main:app --reload`. | Initial dependency/import blockers resolved. |
| 2026-06-17 | User and contractor model | Completed | `User` includes role, profession, service radius, pricing, working hours, AI tone, trade qualifications. | Global location fields added in Phase 1. |
| 2026-06-17 | Job model | Completed | `Job` supports customer, assigned contractor, description, status, urgency, emergency flag, and global location. | Escrow still pending. |
| 2026-06-17 | Conversation and DirectMessage models | Completed | Booking creates a conversation channel. | Needs richer message metadata and AI draft status. |
| 2026-06-17 | Gemini triage service | Completed | Uses `gemini-2.5-flash` through centralized config and extracts global location. | None |
| 2026-06-17 | AI model centralization | Completed | `GEMINI_MODEL` lives in `app/core/config.py`. | None |
| 2026-06-17 | Auth pages | Completed | Login/signup flows exist. | Contractor registration now captures global location. |
| 2026-06-17 | Contractor ID handoff | Completed | Auth redirects preserve contractor signup context. | None |
| 2026-06-17 | Booking flow | Completed | Customer can book selected contractor. | Escrow is mocked only. |
| 2026-06-17 | Auto-book bridge | Completed | `GET /api/v1/jobs/auto-book?contractor_id=...` creates job and redirects to chat. | Should validate escrow/payment before chat in production. |
| 2026-06-17 | Conversation creation | Completed | `Conversation.id == Job.id`, so `/chat/{job_id}` works. | None |
| 2026-06-17 | WebSocket chat | Completed | Chat endpoint exists. | Needed cookie auth fix. |
| 2026-06-17 | WebSocket cookie auth | Completed | Server-side auth avoids frontend token fragility. | None |
| 2026-06-17 | Contractor dashboard | Completed | Shows contractor jobs. | Previously failed due lazy loading; fixed with eager loading. |
| 2026-06-17 | Customer dashboard | Completed | Shows customer jobs and job location. | Needs relationship eager loading for contractor fields. |
| 2026-06-17 | Lazy loading fix | Completed | Added `selectinload` for dashboard relationships. | `MissingGreenlet` resolved. |
| 2026-06-17 | Contractor relationship | Completed | Added `Job.assigned_contractor` and `User.assigned_jobs`. | None |
| 2026-06-17 | Matching engine | Completed | Basic matching by profession, daily limit, and global location. | Geocoding/manual fallback still future work. |
| 2026-06-17 | AI audit model | Completed | `AIOperationsAuditLog` exists. | Needs broader coverage for triage, dispute, and chat drafts. |
| 2026-06-17 | Webhook endpoint | Completed | Basic webhook endpoint exists. | Needs secure signing and provider-specific handlers. |
| 2026-06-17 | Phase 1 global location migration | Completed | Added `country`, `state_or_province`, `city`, `area`, `postal_code`, `latitude`, `longitude` to user/job and applied Alembic migration `8f3d1c9a2b7e`. | None |
| 2026-06-17 | Contractor registration form | Completed | Replaced ZIP-only field with country, state/province, city, area, postal code. | None |
| 2026-06-17 | Global location UI text | Completed | Home/demo copy now uses city/area/postal code instead of ZIP-only wording. | None |

---

## In Progress

| Date | Feature | Status | Notes | Issues |
|---|---|---|---|---|
| 2026-06-17 | XPRIZE strategy review | Completed | Narrowed pitch to AI marketplace + verified professionals + escrow. | None |
| 2026-06-17 | Global-first planning | Completed | Product docs now require country/state/city/area/postal code. | None |
| 2026-06-17 | BizLive prioritization | Completed | BizLive deferred from MVP and moved to final phase. | Needs lightweight placeholder only if demo requires it. |
| 2026-06-17 | Escrow architecture planning | Completed | Job, Escrow, Dispute state machine designed. | Implementation pending. |
| 2026-06-17 | Contractor profile UX planning | Completed | Two-column trust/conversion layout documented. | React/Tailwind implementation deferred. |
| 2026-06-17 | Phase 1 foundation | In Progress | Global location model, migration, AI prompt, matching, and forms are updated. | Need manual end-to-end browser/API test next. |

---

## Pending Work

| Date | Feature | Status | Notes | Issues |
|---|---|---|---|---|
| 2026-06-17 | Contractor availability | Pending | Add `Available`, `Busy`, `Away`, `Vacation`. | Prevents wasted bookings. |
| 2026-06-17 | Verification tiers | Pending | Bronze, Silver, Gold, Verified Pro. | Needs admin review flow. |
| 2026-06-17 | Reputation score | Pending | Completion %, on-time %, response time, dispute rate. | Needs post-job updates. |
| 2026-06-17 | Escrow models | Pending | Add `Escrow` and `Dispute`. | Use Decimal for money. |
| 2026-06-17 | Escrow service | Pending | Completion, cancellation, refund, penalty split. | Must prevent double payout. |
| 2026-06-17 | Payout gateway interface | Pending | Abstract Stripe/Grey/Paxum/local provider. | Start with mock provider. |
| 2026-06-17 | AI dispute recommendation | Pending | Gemini reads chat/photos and recommends refund split. | Advisory only; admin override required. |
| 2026-06-17 | AI job estimator | Pending | Image upload to expected price range. | Phase 2/3 feature. |
| 2026-06-17 | Premium tier | Pending | Free vs Premium subscription model. | Needs billing model. |
| 2026-06-17 | BizLive | Pending | Livestream, AI clips, profile video gallery. | Deferred until marketplace core works. |

---

## Research Notes

| Date | Source Theme | Notes |
|---|---|---|
| 2026-06-17 | Escrow-first home services marketplaces | Current competitors emphasize payment protection, verified contractors, and dispute resolution. ServiceSync should lead with escrow trust. |
| 2026-06-17 | Contractor verification tiers | Strong products show trust as a ladder: ID verified, licensed, insured, background checked, high-reputation. |
| 2026-06-17 | AI home-services matching | AI is most useful for problem description, quote range, availability filtering, and automated follow-up. |
| 2026-06-17 | Contractor pain points | Contractors dislike bad leads and lead-marketplace fees. ServiceSync should emphasize qualified leads and automation. |
| 2026-06-17 | Hyperlocal marketplace scaling | Global availability is a data model goal, but launch liquidity should be city-by-city. |
| 2026-06-17 | Transparent pricing | AI estimates and material/labor breakdowns reduce customer anxiety and contractor disputes. |

---

## Key Code References

| Area | File |
|---|---|
| Models | `app/models/all_models.py` |
| Gemini service | `app/services/gemini_service.py` |
| Matching engine | `app/services/matching_engine.py` |
| Job endpoints | `app/api/v1/endpoints/jobs.py` |
| Chat endpoint | `app/api/v1/endpoints/chat.py` |
| Auth pages | `app/web/auth_pages.py` |
| Web pages | `app/web/pages.py` |
| Config | `app/core/config.py` |
| Migration | `alembic/versions/8f3d1c9a2b7e_add_global_location_fields.py` |

---

## Next Implementation Sequence

1. Run manual browser/API test of contractor registration with Nigeria location.
2. Test `/api/v1/chat/triage` with “Water is pooling under my sink in Ikeja, Lagos, Nigeria.”
3. Seed or create a Lagos contractor and verify matching.
4. Add contractor availability model and dashboard controls.
5. Add verification tier fields and admin review flow.
6. Add escrow and dispute models.
7. Add escrow service with Decimal-based completion/cancellation logic.
8. Add mock payout gateway.
9. Add AI dispute recommendation endpoint.
10. Add reputation score calculation.
11. Add contractor profile UI improvements.
12. Add AI job estimator.
13. Add premium tier rules.
14. Add BizLive only after MVP marketplace and escrow are stable.
