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
| 2026-06-17 | User model verification & reputation fields | Completed | Added `verification_level` (Bronze, Silver, Gold, Verified Pro), `reputation_score`, and `availability_status` (Available, Busy, Away, Vacation) to `User` model. | None |
| 2026-06-17 | Review model | Completed | Added `Review` model to store feedback for completed jobs. | None |
| 2026-06-17 | User schemas updated | Completed | Updated `UserCreate`, `UserResponse`, `UserProfileUpdate`, and `ContractorProfileUpdate` schemas to include verification, reputation, and availability fields. | None |
| 2026-06-17 | Contractor registration form updated | Updated form to collect global location fields (country, state/province, city, area, postal code) and added validation that country and city are required. | None |
| 2026-06-17 | Location helper added | Added `format_location` helper in `app/web/pages.py` to build a readable location string from the location fields (preferring area/city/state/country, falling back to postal/zip code). | None |
| 2026-06-17 | Contractor dashboard location display | Updated contractor dashboard to show customer location using the `format_location` helper. | None |
| 2026-06-17 | Customer dashboard location display (started) | Began updating customer dashboard to show job location via the same helper (still in progress). | None |
| 2026-06-25 | Phase 2 bug fixes | Fixed critical bugs: all_models.py relationship typo, auth_pages.py undefined variables, chat.py zip_code mismatch, DirectMessage.conversation type. | None |
| 2026-06-25 | Missing migrations created | Created migration for Review table, verification_level, reputation_score, availability_status fields. | None |
| 2026-06-25 | Contractor listing page | Added /contractors endpoint with profession/city/country filters and contractor_listing.html template. | None |
| 2026-06-25 | Contractor public profile | Added /contractors/{id} endpoint with two-column layout, reviews, stats, and booking CTAs. | None |
| 2026-06-25 | Matching engine enhancements | Added availability_status filtering (Away/Vacation rejected), verification_level and reputation_score ranking with trust_score sorting. | None |
| 2026-06-25 | Customer dashboard fixes | Fixed job.contractor → job.assigned_contractor references, escrow status and chat links already present. | None |
| 2026-06-25 | Global seed data | Updated seed_db.py with contractors in Lagos Nigeria, London UK, New Delhi India and customers in US and Nigeria. | None |

---

## In Progress

| Date | Feature | Status | Notes | Issues |
|---|---|---|---|---|
| 2026-06-17 | XPRIZE strategy review | Completed | Narrowed pitch to AI marketplace + verified professionals + escrow. | None |
| 2026-06-17 | Global-first planning | Completed | Product docs now require country/state/city/area/postal code. | None |
| 2026-06-17 | BizLive prioritization | Completed | BizLive deferred from MVP and moved to final phase. | Needs lightweight placeholder only if demo requires it. |
| 2026-06-17 | Escrow architecture planning | Completed | Job, Escrow, Dispute state machine designed. | Implementation pending. |
| 2026-06-17 | Contractor profile UX planning | Completed | Two-column trust/conversion layout documented. | React/Tailwind implementation deferred. |
| 2026-06-25 | Phase 2: Marketplace & Trust | Completed | Implemented contractor listing, public profiles, matching engine enhancements (availability, verification, reputation ranking), dashboard improvements, and seed data with global locations. | None |
| 2026-06-25 | Dashboard Trust Signals | Completed | Added verification badges, reputation stars, availability status, profile links, "Browse Contractors" button to both customer and contractor dashboards. | None |
| 2026-06-25 | Messages System | Completed | Created GET /messages (conversation list with partner info, job status, latest message) and GET /messages/start/{contractor_id} (creates job + conversation, redirects to chat). Added Messages nav link to all roles. Fixed contractor profile listing "Book"/"Message" buttons → /messages/start/{id}. Fixed chat breadcrumb to link /messages. Added "My Messages" CTA for contractors viewing own profile. | None |
| 2026-06-25 | Phase 3: Escrow & Payments | Completed | Created Escrow model (Decimal via sa_column=Column(Numeric(12,2))), Dispute model, escrow_service.py (create/release/refund/penalty_split/open_dispute/resolve_dispute), payout_gateway.py (mock process_payout/refund_payment), 7 escrow API endpoints. Updated jobs.py to auto-create escrow on booking. Migration b2c3d4e5f6a7 applied. Customer/contractor dashboards show real escrow status with amounts. Fixed Escrow model Decimal fields (was invalid max_digits/decimal_places in Field()). | None |
| 2026-06-25 | Phase 4: AI Features (Part 1) | Completed | Added AI dispute recommendation (Gemini analyzes chat history + photos, recommends refund split 0-100%) and AI job estimator (Gemini estimates price range, labor/materials breakdown). Created /api/v1/ai/dispute/analyze and /api/v1/ai/estimate endpoints. Added gemini_service.py functions: analyze_dispute, estimate_job_price with fallback analysis. | None |
| 2026-06-25 | Phase 5: Messaging | Completed | Added ai_autonomy_level field (1=manual, 2=AI drafts, 3=auto-reply) to User model with migration. Updated integrations page with 3-level autonomy selector. WebSocket chat now handles all 3 levels: Level 1 sends cross-platform alerts, Level 2 generates AI drafts with approve/dismiss UI, Level 3 auto-replies as contractor. Created alert_service.py with dispatch_alert, alert_new_booking, alert_new_message, alert_dispute_opened, alert_escrow_released. Wired alerts to booking, message, escrow release, and dispute events. Added approve-draft API endpoint. Chat template shows AI draft messages with amber styling and approve/dismiss buttons. Fixed UserRole enum to include admin. | None |
| 2026-07-11 | Audit bug fix (Phase 4) | Completed | Fixed AI dispute analyzer ordering by non-existent `DirectMessage.created_at` → `DirectMessage.timestamp` in ai_features.py. This endpoint was previously broken at runtime. | None |
| 2026-07-11 | Phase 6: Verification & Reputation | Completed | Reputation auto-calculation implemented (reputation_service.py) from real signals: avg rating, completion rate, dispute rate, repeat-customer rate → composite 0-100 score. Recalc hooks on escrow release, admin release, and new review. Customer review flow added (POST /jobs/{id}/review + inline rating form on customer dashboard). Verification admin workflow added: VerificationRequest model + migration e6f7a8b9c0d1, contractor submit form on dashboard, admin approve/reject queue tab. AI triage now surfaces top match verification tier + reputation as trust anchors. | Migrations must be applied: `alembic upgrade head`. |
| 2026-07-11 | Phase 7: Premium Features | Completed | Free vs Premium subscription model. User model gained subscription_tier/status + trial/sub dates (migration f7a8b9c0d1e2). subscription_service.py: effective tier, 14-day trial, tier-based commission (free 15% / premium 5%), upgrade/cancel, self-healing expiry. Escrow commission now tier-based (escrow_service.calculate_fees(rate=...)). Matching engine boosts premium contractors (search ranking). New contractors auto-granted 14-day premium trial (web + API signup). Billing page (/billing) + analytics page (/analytics, premium-only) with upsell. Premium badges on listing/profile/search/contractors; ads on free-tier public profiles; trial banner on contractor dashboard. Admin sees Premium metric + per-user subscription column + priority verification review for premium. | Run `alembic upgrade head`. |
| 2026-07-14 | Phase 10: Chat media, avatars & payment hardening | Completed | (1) Chat attachments end-to-end: `/api/v1/chat/upload` endpoint (image/video/file, 10MB cap, allow-listed extensions) + WebSocket JSON envelope `{content, attachment_url, attachment_type}` persisted on `DirectMessage`. Frontend `chat.html` now uploads on file select, shows a removable preview, sends the attachment over WS, and renders images/video/file bubbles for both live and historic messages. (2) Profile photo upload: `POST /settings/avatar` (5MB cap, image types) writes to `static/uploads` and sets `User.avatar_url`; settings page gained a photo uploader + error toast; avatars already surface in chat header/bubbles. (3) Payment hardening: added `POST /api/v1/webhooks/stripe` with Stripe signature verification (`construct_event`) and idempotent processing via the `StripeEvent` table (duplicate event ids acknowledged without reprocessing); requires `STRIPE_WEBHOOK_SECRET`. (4) Reviewed admin dashboard + emoji usage across templates — emojis are intentional design (category/demo/status icons); no destructive sweep performed. | App boots clean (`python -c "import app.main"`). No new migrations needed — `avatar_url` (k5l6m7n8o9p0), `attachment_url/type`, and `StripeEvent` tables already migrated. |
| 2026-07-12 | Phase 9: Real Transaction Flow & Job Lifecycle | Completed | Closed the biggest UX gap: money now actually moves through the UI. (1) Customer Pay screen `/jobs/{id}/pay` with mock card capture → escrow `unfunded`→`held` (amount = agreed quote, not hardcoded). (2) Two-sided job lifecycle: contractor Start / Mark Complete, customer Confirm & Release; statuses `booked→in_progress→completed_pending→completed`; JobAction audit log. (3) Contractor Wallet `/wallet`: pending (clearing) vs available balances, clearing window (free 5d / premium 2d), Withdraw action, transaction history. Released payouts credit the wallet as pending and clear over time. (4) Chat modernised: in-chat job quick-actions (pay/start/confirm) so the whole flow stays in one screen; softer message bubbles. (5) Light UI pass. (6) Stripe-ready payment layer: `payment_gateway.py` captures card at funding and pays out at release/withdrawal via Stripe Connect when `STRIPE_SECRET_KEY` + contractor `stripe_account_id` are set; otherwise runs in safe mock mode (demo works with zero config). BizLive (Phase 8) deferred — not core to the transaction loop. | Migration `g1h2i3j4k5l6`: escrow quoted_amount/card meta, job started/completed timestamps, JobAction + ContractorWallet + WalletTransaction tables. Migration `h2i3j4k5l6m7`: user.stripe_account_id. |

---

## Pending Work

| Date | Feature | Status | Notes | Issues |
|---|---|---|---|---|
| 2026-06-17 | BizLive | Pending | Livestream, AI clips, profile video gallery (Phase 8 — not started). | Deferred until marketplace core works. |

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
| Escrow service | `app/services/escrow_service.py` |
| Reputation service | `app/services/reputation_service.py` |
| Payout gateway | `app/services/payout_gateway.py` |
| Payment gateway (Stripe) | `app/services/payment_gateway.py` |
| Webhooks (Meta/Telegram/Stripe) | `app/api/v1/endpoints/webhooks.py` |
| Chat upload + WS attachments | `app/api/v1/endpoints/chat.py` |
| Avatar upload | `app/web/pages.py` (`/settings/avatar`) |
| Job endpoints | `app/api/v1/endpoints/jobs.py` |
| Escrow endpoints | `app/api/v1/endpoints/escrow.py` |
| AI features | `app/api/v1/endpoints/ai_features.py` |
| Alert service | `app/services/alert_service.py` |
| Chat endpoint | `app/api/v1/endpoints/chat.py` |
| Auth pages | `app/web/auth_pages.py` |
| Web pages | `app/web/pages.py` |
| Config | `app/core/config.py` |
| Migration | `alembic/versions/8f3d1c9a2b7e_add_global_location_fields.py` |
| Migration | `alembic/versions/a1b2c3d4e5f6_add_review_and_verification_fields.py` |
| Migration | `alembic/versions/b2c3d4e5f6a7_add_escrow_and_dispute_tables.py` |
| Migration | `alembic/versions/e6f7a8b9c0d1_add_verification_request_table.py` |
| Migration | `alembic/versions/f7a8b9c0d1e2_add_subscription_fields_to_user.py` |
| Subscription service | `app/services/subscription_service.py` |
| Contractor listing | `app/templates/contractor_listing.html` |
| Contractor profile | `app/templates/contractor_profile.html` |
| Messages list | `app/templates/messages.html` |
| Chat | `app/templates/chat.html` |
| Integrations | `app/templates/integrations.html` |
| Seed script | `scripts/seed_db.py` |

---

## Next Implementation Sequence

1. ~~Implement contractor availability logic~~ ✅ Done
2. ~~Implement verification tier model and admin approval workflow~~ ✅ Fields exist, admin workflow pending
3. ~~Implement reputation score calculation~~ ✅ Fields exist, calculation after job completion pending
4. ~~Enhance matcher to consider verification level and availability~~ ✅ Done
5. ~~Update dashboards to show verification badges, reputation scores, availability status~~ ✅ Done
6. ~~Update customer job search to display verification tier and reputation score~~ ✅ Done
7. ~~Add contractor listing and public profile pages~~ ✅ Done
8. ~~Implement escrow and dispute models with Decimal-based money handling~~ ✅ Done
9. ~~Implement escrow service for completion, cancellation, refund, and penalty split logic~~ ✅ Done
10. ~~Add mock payout gateway for testing~~ ✅ Done
11. ~~Implement AI dispute recommendation endpoint (Gemini reads chat/photos and suggests refund split)~~ ✅ Done
12. ~~Implement AI job estimator (image upload to expected price range)~~ ✅ Done
13. ~~Implement reputation score auto-calculation after job completion + review flow~~ ✅ Done (Phase 6)
14. ~~Implement verification admin approve/reject workflow~~ ✅ Done (Phase 6)
15. ~~Implement premium tier subscription model (Free vs Premium) — Phase 7~~ ✅ Done
16. ~~Implement real transaction flow, two-sided job lifecycle, contractor wallet/withdrawal, chat + UI polish — Phase 9~~ ✅ Done
17. Implement BizLive livestream and video clip features — Phase 8, DEFERRED (not core to transaction loop).
18. Add testing and polishing for MVP.

---

## Current Phase Status

- **Phases 1–7, 9 and 10: COMPLETE.**
- **Phase 8 (BizLive) — DEFERRED** (not required for the core marketplace; revisit only if a demo needs video).
- All migrations applied. Run `alembic upgrade head` before starting the server.

### Next session — suggested starting points
- Wire real Stripe PaymentIntent confirmation on the client `pay_job` screen (server currently creates the intent; add JS card element for live mode).
- Handle specific Stripe event types in the webhook (`payment_intent.succeeded`, `charge.refunded`) to auto-sync escrow status.
- Optional: contractor-side avatar upload from the contractor dashboard (endpoint is generic — reuse `/settings/avatar` or add a contractor settings page).
- Optional: image lightbox / download affordance for chat attachments.

---

### Required actions
Run migrations before starting the server:

```
alembic upgrade head
```

New migrations since baseline:
- `e6f7a8b9c0d1` — verification request table
- `f7a8b9c0d1e2` — subscription fields
- `g1h2i3j4k5l6` — transaction flow (escrow funding, job lifecycle, contractor wallet)