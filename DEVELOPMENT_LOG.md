# ServiceSync — Development Log

---

## UI/UX ROADMAP & SESSION HANDOFF (2026-07-16)

> **Read this first** when resuming UI work in a new chat/session.
> Context: full site audit → phased fixes. User asked for chat-room layout (no
> footer, messages-only scroll), media viewer fixes, then Phase 2 + split inbox.
> Always log progress in this file when continuing.

### Status snapshot

| Phase | Name | Status | Outcome |
|-------|------|--------|---------|
| **0** | Site audit (observations) | Done | Audit delivered in chat (not a code PR). |
| **1** | Chat room shell + media + bubbles/emoji | **Done** | Full-height chat, no footer, lightbox media, better composer. |
| **2** | Notifications + footer + desktop split inbox | **Done** | Real bell, legal pages, messages/chat split UI. |
| **3** | Chat depth (attachments DB, presence, receipts) | **Done** | Filename in DB, true presence, real receipts, typing WS, jump/date/nav badge. |
| **4** | Trust & marketing polish | **Done** | Trade icons, honest trust bar, FAQ accordion, quieter gradients, no dead social #. |
| **5** | Product UX extras | **Next** | In-thread search, safety tools, job context card, dark mode. |

### First thing in a new session

1. Skim this handoff + latest session entry.
2. Run migration if not applied yet:
   ```bash
   alembic upgrade head
   ```
   Includes `m7n8o9p0q1r2` (last_read) and `n8o9p0q1r2s3` (attachment_name).
3. Smoke-check: `/`, `/chat/{id}` (header + composer in viewport), bell open/**close**, FAQ accordion.
4. Pick **Phase 5** (recommended) unless user prioritizes something else.

### Key files (UI/chat)

| Area | Path |
|------|------|
| Layout shell / nav / footer / notif bell | `app/templates/base.html` |
| Chat room + media lightbox | `app/templates/chat.html` |
| Messages list (split empty pane) | `app/templates/messages.html` |
| Shared inbox list partial | `app/templates/_conversation_list.html` |
| About / Privacy / Terms | `app/templates/legal_page.html` |
| Landing marketing | `app/templates/index.html` |
| Notifications service | `app/services/notification_service.py` |
| Upload helper | `app/services/upload_service.py` |
| Chat WS + upload API | `app/api/v1/endpoints/chat.py` |
| Notif API | `app/api/v1/endpoints/users.py` → `GET /me/notifications` |
| Web routes (messages, chat, legal) | `app/web/pages.py` |
| Models | `app/models/all_models.py` (`Conversation`, `DirectMessage`) |

### Layout blocks (do not regress)

`base.html` supports:
- `{% block body_class %}`
- `{% block main_class %}`
- `{% block footer %}` — empty on chat/messages to hide marketing footer
- Chat uses `body.chat-mode` + `main.chat-main` (locked `100dvh`, only `#message-thread` scrolls)
- Messages uses `body.messages-mode` + `main.messages-main` similarly

---

### Phase 1 — DONE (detail)

**Goal:** Feel like a real chat app, not a page with a chat widget + footer.

- No footer on chat; viewport locked; only message list scrolls.
- Media: image/video full-view lightbox; PDF iframe preview; docs download panel (no empty tab).
- File cards with type badges; UUID filenames → human labels (“PDF Document”).
- Upload API returns `name`, `ext`, `content_type`, `size`.
- Bubbles + always-visible times; multi-line composer (Enter send, Shift+Enter newline); emoji tray polish.

**Files:** `base.html`, `chat.html`, `chat.py` (upload response).

---

### Phase 2 — DONE (detail)

**Goal:** Honest notifications + credible footer + desktop messaging layout.

- Real notifications from unread messages + job actions (pay/start/confirm/dispute).
- Bell badge only when `unread_count > 0`; panel via `GET /api/v1/users/me/notifications`.
- Read cursors on Conversation; set on chat open (`mark_conversation_read`).
- Footer → real `/about`, `/privacy`, `/terms` (+ cookie section); no Blog/Careers `#`.
- Desktop: `/messages` list + empty pane; `/chat/{id}` list sidebar + thread.
- Shared `_conversation_list.html`; unread badges; “You:” preview prefix.

**Files:** see Phase 2 session entry below.

---

### Phase 3 — DONE (chat depth)

**Goal:** Messaging quality comparable to WhatsApp/iMessage for a marketplace.

| # | Task | Status |
|---|------|--------|
| 3.1 | Persist original attachment filename in DB | **Done** |
| 3.2 | True partner presence | **Done** |
| 3.3 | Real read receipts | **Done** |
| 3.4 | Typing indicators over WS | **Done** |
| 3.5 | “Jump to latest” button | **Done** |
| 3.6 | Date separators | **Done** |
| 3.7 | Nav Messages unread badge | **Done** |

See session entry **2026-07-16 (3)** below for files and details.

---

### Phase 4 — DONE (trust & marketing polish)

**Goal:** Landing and brand feel finished and honest.

| # | Task | Status |
|---|------|--------|
| 4.1 | Fix trade icons (`paint`, `pest`) | **Done** |
| 4.2 | Soften social-proof / stats | **Done** (honest product claims) |
| 4.3 | Tone down gradient density | **Done** |
| 4.4 | FAQ accordion | **Done** |
| 4.5 | Social footer links | **Done** (removed dead `#`; About / Join as Pro) |
| 4.6 | Trust avatars on stories (illustrative, labeled) | **Done** (light touch) |

Also this session: **chat viewport layout fix** + **notification panel close fix**.

See session entry **2026-07-16 (4)** below.

---

### Phase 5 — Product UX extras — NEXT

**Goal:** Power-user and safety features for marketplace chat/jobs.

| # | Task | Why |
|---|------|-----|
| 5.1 | In-thread message search | Find old quotes/addresses |
| 5.2 | Expandable job context card in chat header (address, schedule, amount) | Reduce leaving chat for job details |
| 5.3 | Report / block / safety tools | Marketplace risk |
| 5.4 | Image lightbox polish (zoom, swipe next if multiple) | Media UX |
| 5.5 | Dark mode (especially contractor night use) | Comfort |
| 5.6 | Post-job review prompt after completion | Growth/trust |
| 5.7 | Archive / mute / filter conversations | Inbox hygiene |
| 5.8 | Deduplicate giant `{% macro icon %}` across templates into one partial | Maintainability |

---

### Known issues / constraints (do not re-discover)

1. **Migrations required:** `alembic upgrade head` — includes `m7n8o9p0q1r2` (last_read) and `n8o9p0q1r2s3` (`attachment_name`). Without columns, unread/attachment names may soft-fail; chat should still open.
2. **Presence is per-process** unless Redis hub is configured (`REDIS_URL`). Multi-worker without Redis may show Offline incorrectly across instances.
3. **Tailwind via CDN** — fine for MVP; production build pipeline is optional later.
4. **Neon cold start** — Alembic may timeout; increase timeout or warm connection.
5. **Demo mode** still works with zero cloud config (local uploads, mock payments).
6. **Auth for notif API** uses session cookie (`credentials: 'same-origin'` in `base.html` fetch).

### How to continue (prompt templates for next session)

- *“Continue ServiceSync UI from DEVELOPMENT_LOG Phase 5.”*
- *“Add in-thread message search (5.1) and job context card (5.2).”*

When finishing a phase: mark the table row **Done**, append a dated session entry at the top of the log (same style as Phase 1/2), and update this handoff table.

---

## 2026-07-16 (4) — Phase 4 + chat layout + notif panel

### Progress log

1. **Chat layout (viewport bugs)**
   - Symptom: chat header sometimes under sticky navbar; composer/input off-screen.
   - Fix: `body.chat-mode` / `messages-mode` use true flex column (`100dvh`, `min-height: 0`),
     nav is `position: relative` (not sticky overlap), main/`chat-page-wrapper`/`chat-container`
     use `flex: 1 1 0%` + `overflow: hidden`, thread column `.chat-thread-col`, input bar
     `flex: 0 0 auto` + safe-area padding.
   - Same pattern applied to `messages.html`.

2. **Notification panel not closing**
   - Root cause: `#notif-panel { display: flex }` beat Tailwind `.hidden` (ID specificity).
   - Fix: `#notif-panel:not(.hidden) { display: flex }` + `#notif-panel.hidden { display: none !important }`.
   - `closeNotifPanel()`, Escape key, outside-click, toggle open/close.

3. **Phase 4 landing polish**
   - 4.1: SVG paths for `paint` + `pest` icons; trade grid uses icon macro for all.
   - 4.2: Replaced mock “&lt; 10s / 5+ trades” stats with honest product claims.
   - 4.3: Hero/CTA solid slate + softer single blobs; less multi-stop gradients on CTAs/steps.
   - 4.4: FAQ accordion (single-open, chevron).
   - 4.5: Removed footer Twitter/LinkedIn `href="#"`; About + Join as Pro links.
   - 4.6: Story cards with gradient avatar initials; labeled “illustrative story”.

### Files touched
- `app/templates/chat.html`
- `app/templates/messages.html`
- `app/templates/base.html`
- `app/templates/index.html`
- `DEVELOPMENT_LOG.md`

### Smoke-check
- Open `/chat/{id}`: header fully below nav; composer always visible; only thread scrolls.
- Bell: open → click outside / Escape / click bell again → closes.
- `/`: paint/pest icons, FAQ expands, no `#` social icons.

---

## 2026-07-16 (3) — Phase 3: Chat depth

### Progress log
1. **Attachment original filename (3.1)**
   - `DirectMessage.attachment_name` + migration `n8o9p0q1r2s3`.
   - WS handler saves and broadcasts `attachment_name`; historic file cards hydrate from DB.

2. **True partner presence (3.2)**
   - `ConnectionManager.online_user_ids` / `is_user_online`.
   - On connect: snapshot + broadcast `{type:"presence"}`; offline on last socket leave.
   - UI: green Online only if peer is in the conversation; otherwise Offline.

3. **Real read receipts (3.3)**
   - Opening WS marks conversation read + broadcasts `{type:"read"}`.
   - Historic own messages use partner `last_read_at_*` for ✓✓ vs cyan read.
   - Receiving a message while in-thread sends read; sender upgrades all own bubbles.

4. **Typing over WS (3.4)**
   - Composer sends `{type:"typing"}` (throttled); peer shows `#typing-indicator`.

5. **Jump to latest (3.5)** — FAB when scrolled up on `#message-thread`.

6. **Date separators (3.6)** — Today / Yesterday / date for historic + live.

7. **Nav Messages badge (3.7)**
   - Notifications API returns `messages_unread_count`.
   - `base.html` badges the Messages nav link (refreshed with bell poll).

8. **WS protocol** — control messages (`typing`/`read`/`presence`/`ping`) are not persisted; chat messages broadcast as structured JSON with `id` + `message_ack` to sender.

### Files touched
- `app/models/all_models.py`
- `alembic/versions/n8o9p0q1r2s3_add_attachment_name.py`
- `app/api/v1/endpoints/chat.py`
- `app/services/notification_service.py`
- `app/web/pages.py`
- `app/templates/chat.html`
- `app/templates/base.html`
- `DEVELOPMENT_LOG.md`

### Deploy note
Run migration: `alembic upgrade head` (adds `directmessage.attachment_name`).

---

## 2026-07-16 (2) — Phase 2: Notifications, footer, split inbox

### Progress log
1. **Real notifications (no fake red dot)**
   - `app/services/notification_service.py` — builds items from unread messages + job actions (pay, start, confirm, disputes).
   - Conversation `last_read_at_customer` / `last_read_at_contractor` + migration `m7n8o9p0q1r2`.
   - Opening chat marks the thread read via `mark_conversation_read`.
   - API: `GET /api/v1/users/me/notifications`.
   - `base.html` bell: dropdown panel, badge only when `unread_count > 0`, 60s refresh, honest empty state.

2. **Footer cleanup + legal pages**
   - Routes: `/about`, `/privacy`, `/terms` → `legal_page.html`.
   - Footer links wired (About, Privacy, Terms, cookies anchor, Join as Pro). Removed dead Blog/Careers `#` links.

3. **Desktop split inbox**
   - Shared partial `_conversation_list.html` (search, unread badges, avatars, job chips).
   - `/messages`: full-height list + empty “Select a conversation” pane on `lg+`.
   - `/chat/{id}`: desktop left inbox sidebar + active chat (mobile stays full chat).
   - Unread counts from last-read cursors; “You:” prefix on own last message.

### Files touched
- `app/models/all_models.py`
- `alembic/versions/m7n8o9p0q1r2_add_conversation_last_read.py`
- `app/services/notification_service.py`
- `app/api/v1/endpoints/users.py`
- `app/web/pages.py`
- `app/templates/base.html`
- `app/templates/messages.html`
- `app/templates/chat.html`
- `app/templates/_conversation_list.html`
- `app/templates/legal_page.html`
- `DEVELOPMENT_LOG.md`

### Deploy note
Run migration: `alembic upgrade head` (adds conversation last_read columns).

### Closed by this phase (were open after Phase 1)
- Desktop split inbox
- Real notifications / fake red dot

---

## 2026-07-16 — Phase 1: Chat room shell + media viewer polish

### Progress log
1. **Audit complete** — chat still used global marketing footer + page scroll; media for PDF/docs was a bare “File” link that opened poorly (empty / useless tab, UUID filenames like `66d8….pdf`).
2. **Base layout hooks** (`app/templates/base.html`)
   - `{% block body_class %}`, `{% block main_class %}`, `{% block footer %}` so pages can opt out of footer and lock viewport.
3. **Chat room shell** (`app/templates/chat.html`)
   - `{% block footer %}{% endblock %}` — **no footer on chat**.
   - `body.chat-mode`: `100dvh`, `overflow: hidden`.
   - Flex column: header + job bar + **only `#message-thread` scrolls** + fixed composer.
   - Breadcrumb replaced by in-header back button (more vertical space).
4. **Media viewing fix**
   - Tap image → full-screen lightbox.
   - Tap video → lightbox player with controls + autoplay (inline shows play badge, not awkward inline controls).
   - PDF → lightbox **iframe** preview (native browser PDF viewer) + Download / Open.
   - DOC/DOCX/etc. → clear “can’t preview — download” panel (no empty broken page).
   - File **cards** with type badge (PDF/DOC/TXT) and human labels; UUID storage names map to e.g. “PDF Document” instead of raw hash/`pdf.pdf`.
5. **Upload API** (`app/api/v1/endpoints/chat.py`) — response now includes `name`, `ext`, `content_type`, `size` for better client labels.
6. **Bubbles + emoji**
   - Tighter bubbles, always-visible timestamps inside bubble.
   - Multi-line composer (`textarea`, Enter send / Shift+Enter newline, auto-grow).
   - Emoji tray: denser grid, more glyphs, hover scale, close button, Escape closes.

### Files touched
- `app/templates/base.html`
- `app/templates/chat.html`
- `app/api/v1/endpoints/chat.py`
- `DEVELOPMENT_LOG.md` (this entry)

### Note
Items listed as “still open” after Phase 1 (split inbox, notifications) were completed in Phase 2. Remaining work is in the **UI/UX ROADMAP** handoff at the top of this file.

---

## 2026-07-14 — Payments hardening, disputes, uploads, scaling, tests

### New
- **Centralized upload helper** `app/services/upload_service.py`: env-gated storage
  (Cloudinary → S3 → local `/static/uploads`). Chat (`/api/v1/chat/upload`) and
  avatar (`/settings/avatar`) uploads now route through it. Config fields added
  to `app/core/config.py` (`CLOUDINARY_*`, `AWS_S3_*`). Local fallback keeps the
  demo working with zero config; cloud URLs survive server restarts.
- **WebSocket scaling** `app/services/broadcast_hub.py`: Redis pub/sub fan-out
  when `REDIS_URL` is set, in-memory fallback otherwise. `ConnectionManager`
  (`app/api/v1/endpoints/chat.py`) routes `broadcast_to_conversation` through it;
  hub started/shutdown via FastAPI lifespan in `app/main.py`.
- **Real Stripe checkout** (live, gated): `POST /jobs/{job_id}/create-intent`
  returns a PaymentIntent `client_secret`; `pay_job.html` mounts Stripe Elements
  only when publishable+secret keys are present, falling back to the mock card
  form. `web_fund_escrow` + `fund_escrow` accept `payment_intent_id` and skip the
  mock capture when a real intent is supplied.
- **`/health`** endpoint for hosting readiness probes (e.g. Render).
- **pytest smoke suite** `tests/` (9 passing): app import, health, route
  registration, upload helper (local fallback + reject bad type), Redis memory
  fallback, and escrow state-machine rules. `pytest.ini` added; `requirements.txt`
  updated (`pytest`, `pytest-asyncio`, `cloudinary`, `boto3`, `redis`).

### Bug fixes / hardening
- `fund_escrow` is now **idempotent** — a second funding submission no longer
  overwrites the captured amount or re-issues a receipt (prevents double-charge).
- **Disputed escrows can no longer be force-released at 100% to the contractor**;
  `release_escrow` raises if status is `disputed` — funds must go through dispute
  resolution (which applies the correct split/refund).
- `penalty_split_escrow` now allowed from `disputed` state too.
- **Dispute AI now auto-runs on file** (`file_dispute` web + `/api/v1/escrow/{id}/dispute`
  API): gathers chat history and persists the recommendation to
  `Dispute.ai_arbitration_summary` / `ai_recommended_refund_pct`, status → `reviewing`.
  Both customer **and contractor** can now open disputes.
- `resolve_dispute` now updates `Job.status` to match the outcome (full refund →
  `cancelled`, contractor wins → `completed`) so dashboards stay consistent.
- `admin_refund_escrow` now flashes the error instead of silently swallowing it.

### Admin review (no structural gaps found)
- Admin can verify users, approve/reject verification requests, toggle
  availability, resolve disputes (with refund %), and force-release/refund escrows.
  Note: per-escrow release is intended; only **disputed** escrows are now blocked
  from force-release. No batch-payout screen exists (payouts happen per-escrow on
  release) — acceptable for current scale.

### Next session / open items
- Add `pip install` of `cloudinary`/`boto3`/`redis`/`pytest` in deploy build step
  (already in `requirements.txt`).
- Optional: surface the persisted AI dispute recommendation inline on the admin
  dispute-resolve form; add per-escrow release is fine but consider a batch payout.
- Optional: reconcile `Escrow.status` from the Stripe webhook for live mode (the
  webhook already sets `held`/`refunded` by `payment_gateway_id`).
- Neon cold-start still makes `alembic` CLI exceed 120s; run with a larger timeout
  or rely on app boot. No schema migration was needed for this session's changes.

---

## 2026-07-14 (2) — Dispute AI inline, Stripe webhook reconcile, icons, mobile, docs

### New / changed
- **Admin dispute UI** (`app/templates/admin_dashboard.html`): the AI arbitration
  recommendation now renders as structured fields (fault party, reasoning,
  confidence) by parsing the stored JSON, and the resolve form **prefills the
  refund %** from `ai_recommended_refund_pct` (falls back to 50).
- **Stripe webhook reconciliation** (`app/api/v1/endpoints/webhooks.py`):
  `payment_intent.succeeded` → `held` (idempotent, recovers lost client callbacks);
  `payment_intent.payment_failed` noted; `charge.refunded`/`refund.updated` →
  `refunded` (skips disputed/penalty_split so dispute splits stay authoritative).
  Escrow is matched by `payment_gateway_id` (set when a real PaymentIntent funds it).
- **Icons**: replaced decorative emoji with real inline-SVG icons across all page
  templates (added a reusable `{% macro icon(...) %}`). The chat emoji *picker*
  (user-sendable emojis) is intentionally kept.
- **Mobile responsiveness**: conservative pass on customer/contractor dashboards,
  chat header, search + contractor listing cards — `min-w-0`/`truncate` on flex
  text, responsive heading sizes, so long names/amounts wrap instead of overflowing
  at ~375px. `base.html` already had the viewport meta + SVG navbar icons.
- **Docs**: `SETUP.md` added — every env var, where to get it, why, plus Stripe
  go-live steps, external-services table, pytest + manual E2E test instructions,
  and a Render deploy checklist.

### Notes
- Demo mode still needs **zero** external config (mock payments, local uploads,
  Gemini fallback, in-process WebSocket).
- Going live = set `STRIPE_SECRET_KEY` + `STRIPE_PUBLISHABLE_KEY` (pay screen
  auto-switches to Stripe Elements); add `STRIPE_WEBHOOK_SECRET` for event sync.
- For durable uploads on hosted deploys, set Cloudinary or S3 (Render free tier
  wipes `app/static/uploads` on restart). Add `REDIS_URL` only when scaling >1 instance.

---

## Active Direction

- Product: AI-powered contractor marketplace.
- Core pitch: natural language search + verified professionals + escrow payments.
- Global-first: remove US-only ZIP assumptions.
- BizLive: keep in master plan, defer from MVP.
- MVP focus: AI Concierge, profiles, booking, escrow, messaging, verification basics.
- **UI track (2026-07-16):** Phases **1–4 complete**. **Next = Phase 5** (product UX extras). Chat viewport + notif close fixed in session (4).

---

## Completed Work

| Date | Feature | Status | Notes | Issues |
|---|---|---|---|---|
| 2026-07-16 | UI Phase 1: chat room + media lightbox | Completed | No footer, full-height, messages-only scroll; PDF/image/video viewer; bubbles/emoji. | Attachment original name not in DB (Phase 3.1). |
| 2026-07-16 | UI Phase 2: notifications + footer + split inbox | Completed | Real bell API; legal pages; desktop messages/chat sidebar; last_read migration. | Run `alembic upgrade head` for last_read columns. |
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