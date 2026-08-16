# ServiceSync — Product Direction & Work Log

> **Last updated:** 2026-08-16
> **Owner:** Ifeanyi
> This is a *living* document. Update the **Status** and **Update Log** sections
> every time work is done. Keep the vision stable; keep the plan honest.

---

## 1. Vision (decided 2026-08-16)

**ServiceSync is evolving from "a marketplace connecting customers and contractors"
into AI-powered operating + marketplace infrastructure for service businesses.**

The customer-facing marketplace already exists. What we now emphasise is the
**contractor operating layer** — the system that helps a service business *get
customers, quote jobs, manage the work, get paid, and later buy the materials
they need*. This is a stronger, more defensible product and aligns with the
Build with Gemini XPRIZE (SMB services, entrepreneurship/job creation, financial
access, professional services).

### The full lifecycle we are building toward

```
Customer enquiry
  → AI understands the request
  → Contractor receives a lead
  → AI helps the contractor create a quote
  → Customer receives a proposal
  → Customer accepts
  → Deposit / payment
  → Job created
  → Technician assigned
  → Technician updates progress
  → Job completed
  → Final payment
  → Review
  → Repeat service (maintenance)
      → (later) required materials → supplier recommendations → procurement → delivery
```

### Three sides

- **Customer side:** find service → describe problem → AI-assisted matching →
  get quote → book → pay → track → review.
- **Contractor side (the new focus):** leads → AI intake → quote builder →
  proposal → CRM → jobs → technicians → materials → payments → analytics.
- **Supplier side (later):** products → pricing → availability → contractor
  orders → fulfilment.

### Growth funnel (free tools)

Public, ad-supported free calculators (CCTV calculator, solar calculator,
quotation generator, service-price estimator, project/BOM calculator) bring in
search traffic. A user who finishes a calculation is offered *"find a
professional to do this for you"* → drops into the ServiceSync marketplace →
contractor → transaction. Ads live on the free-tool/content side only; the core
app stays clean.

### Guardrail (explicit)

Do **not** add 20 features at once. The existing core (messaging persistence,
live-room/RTC, escrow edge cases) is not fully production-ready — make it solid
before piling on procurement, AI quoting, technician agents, etc. The XPRIZE
rewards a real business with real users and revenue, so the most valuable thing
to ship next is something that produces a **real transaction**.

### First vertical

Start with **one vertical — CCTV / access-control contractors** — and ship the
**AI enquiry → quote → booking → payment** workflow first, then expand to solar,
electrical, HVAC, networking, etc.

---

## 2. Status

| Area | State | Notes |
|------|-------|-------|
| Repo recovered on new drive | ✅ done | `C:\Users\IFEANYI\Documents\ServiceSycn` (folder name is misspelled "ServiceSycn") |
| Security audit + hardening | ✅ done | See §3.1 |
| LLM provider abstraction | ✅ done + audited | `app/services/llm.py`; no Gemini lock-in; Phase 3 confirms every AI path routes through `get_provider()` |
| ServiceSync Voice (CALL-E) | ✅ built + wired + packaged | dispatch + poll + webhook + status page; phones the *matched* CCTV installers and feeds structured offers back into booking; hackathon doc + README at `docs/CALL_E_HACKATHON.md`; live call needs real `CALL_E_API_KEY` + public webhook URL |
| Docs / `.env.example` | ✅ done | this file + `.env.example` |
| Phase 0 — Core solidification | ✅ done | escrow double-receipt guard ✅, security regression tests ✅, websocket history re-sync ✅; see §4 Phase 0 |
| AI enquiry→quote→booking→payment (CCTV vertical) | ✅ done | model + AI intake + AI quote + matching + endpoints + tests; booking→escrow→payout reuses existing flow; see §4 Phase 1 |
| Free-tools funnel | ✅ done | 5 public calculators (CCTV, solar, quote, project/BOM, price range) + ad-supported funnel to marketplace; supplier data model + procurement/delivery API + contractor **Materials board** UI (recommended BOM → order → mark delivered) |
| Phase 6 — funnel→transaction | 🔧 in progress | `GET /tools/request-pro` turns a free-tool estimate into a real Job lead for signed-in customers (funnel→marketplace bridge); live Paystack + live CALL-E callbacks + a pilot real transaction remain; see §4 Phase 6 |
| CALL-E hackathon packaging | ✅ done | `docs/CALL_E_HACKATHON.md` + root `README.md`; module map + offline demo + webhook simulation; Devpost entry still needs your account |

---

## 3. Work Log (what was actually built)

### 3.1 Security hardening (audit → fixes)
Performed a full audit of data layer, backend, web frontend, infra/tests. Fixed:

- `app/api/dependencies.py` — `get_current_user_optional` now rejects
  non-`access` tokens and banned (`is_active=False`) users (kills refresh-token
  as access + 2FA bypass).
- `app/api/v1/endpoints/auth.py` — signup coerces `role:"admin"`→`customer`;
  removed plaintext 2FA-code logging.
- `app/api/v1/endpoints/webhooks.py` — Paystack/Meta/Telegram now 503 when
  secret unset; fixed `None==None` verify-token bypass. (CALL-E webhook added
  here too — see §3.3.)
- `app/templates/base.html` — toast message rendered via `textContent`
  (kills `?error=` reflected/DOM XSS).
- `app/web/auth_pages.py` — escape `token`/`error` in reset + 2FA pages.
- `app/services/escrow_service.py` — Stripe funding binds captured
  `amount`/`currency` to `quoted_amount`.
- `app/api/v1/endpoints/jobs.py` — reroute reuses existing `Conversation` +
  reassigns `Escrow.contractor_id`; `confirm` refuses unless escrow
  held/disputed; `ReviewCreate.rating` bounded 1–5.
- `scripts/seed_db.py` — seeds only when `settings.DEMO_MODE` is true.
- `render.yaml` — added `healthCheckPath`, `DEMO_MODE`, safer seed command.
- `app/main.py` — `RateLimitMiddleware` extended with `PROTECTED_PREFIXES`
  (escrow/ai/jobs/admin) and Redis-aware via `REDIS_URL`.

### 3.2 LLM provider abstraction (no Gemini lock-in)
- `app/services/llm.py` — `BaseLLMProvider`, `GeminiProvider`, `GroqProvider`,
  `OllamaProvider`, `get_provider()`, `available_providers()`.
- `app/core/config.py` — `AI_PROVIDER`, `GROQ_*`, `OLLAMA_*`.
- `app/services/gemini_service.py` — all 4 functions rewired to
  `get_provider().complete(...)`. Default `AI_PROVIDER=gemini` keeps current
  behaviour; switch to `groq`/`ollama` with zero code changes.

### 3.3 ServiceSync Voice — CALL-E AI phone dispatcher
Researched the real CALL-E Developer API (base `https://api.heycall-e.com`,
`POST /v1/calls`, `GET /v1/calls/{id}`, `POST /calle/webhook`, Bearer auth,
`Idempotency-Key`, no webhook signature) and built:

- `app/services/calle_client.py` — `create_call(task, phone, *, region, locale,
  result_schema, idempotency_key, webhook_url)`, `get_call(call_id)`,
  `CallENotConfigured`. Raises `CallENotConfigured` (no key) so demo mode is safe.
- `app/services/voice_dispatch.py` — `ServiceCallResult`, `SERVICECALL_RESULT_SCHEMA`
  (JSON Schema sent to CALL-E), `ProviderOffer`, `dispatch_calls`, `resolve_offer`,
  `apply_webhook_event`, `rank_offers`, `best_offer`, in-memory `DISPATCH_STATE`.
  Parses CALL-E `structured_result` first, falls back to LLM transcript extraction.
- `app/api/v1/endpoints/voice.py` — `POST /api/v1/voice/dispatch` (customer-only)
  + `GET /api/v1/voice/dispatch/{job_id}` (poll/rank).
- `app/api/v1/endpoints/webhooks.py` — `POST /api/v1/webhooks/calle` terminal
  webhook, deduped via `CALL-E-Event-Id` (rate-limiter exempt like other webhooks).
- `app/web/pages.py` + `app/templates/voice_dispatch.html` +
  `app/templates/voice_offer_card.html` — status page at `/voice/{job_id}` with
  Start-calls / Refresh + live offer cards; plus a "Call providers" button on the
  customer dashboard (shown only when `CALL_E_API_KEY` is set).
- `app/core/config.py` — added `CALL_E_WEBHOOK_BASE_URL`.
- Verified: modules import, FastAPI boots, endpoints + webhook register, templates
  compile. No live call has been exercised (no real `CALL_E_API_KEY`).

---

## 4. Roadmap (the confirmed build order)

> **Current phase: 5 (Free-tools funnel + supplier side) — started.** Update this line as phases complete.
> Each phase block ends with **Next:** so it is always clear what follows.

### Phase 0 — Solidify the core *(done)*
Make the existing ServiceSync reliable before layering anything new.
- ✅ Persistent messaging / live-room (RTC): history re-syncs from the DB on
  websocket (re)connect (`chat.py`), and the client dedupes by message id so a
  page reload + socket resync never double-renders. (Page-load history was
  already server-rendered in `chat_page`.)
- ✅ Escrow double-receipt / TOCTOU guard: `escrow_service._issue_receipt`
  dedupes by `payment_reference`, and funding early-returns when already `held`.
  *Residual race:* two truly concurrent, uncommitted deliveries could still both
  insert — mitigate in prod with a UNIQUE constraint on `Receipt.payment_reference`
  (+ try/except IntegrityError). Tracked, not blocking Phase 1.
- ✅ Regression tests for the security fixes (signup role coercion, token-type
  rejection, banned-user rejection, Paystack webhook auth) — `tests/regression_security.py`;
  escrow idempotency — `tests/regression_escrow.py`. All 14 tests pass.
- **Next:** Phase 1 (CCTV vertical) — the core must be trustworthy first.

### Phase 1 — CCTV vertical, end-to-end *(in progress)*
- ✅ Data model: `Job.category` + `Job.brief`, `User.specialties` (vertical tags).
- ✅ AI intake: `app/services/intake_service.py` → `intake_job` returns a
  structured `JobBrief` (CCTV: site type, camera count, features, wiring, budget,
  urgency). Provider-agnostic via `get_provider()`; offline fallback (low
  confidence, flag for review) when no LLM is configured.
- ✅ AI quote builder: `app/services/quote_service.py` → `draft_quote` turns the
  brief + contractor rates into a line-item `JobQuote`. Same offline-safe pattern.
- ✅ CCTV endpoints: `app/api/v1/endpoints/cctv.py` — `POST /api/v1/cctv/intake`
  (creates `Job` status `open`, category `cctv`, brief set; returns brief +
  matched CCTV contractors) and `POST /api/v1/cctv/{job_id}/draft-quote`.
  Vertical-aware matching: filters contractors by `profession`/`specialties`
  (cctv/camera/security) and ranks by availability + reputation.
- ✅ UI: `/cctv/intake` page (`cctv_intake.html`) — customer describes the job,
  sees the structured brief + matched installers, and Books (→ existing
  `/api/v1/jobs/{job_id}/book`, then redirects to `/jobs/{job_id}/pay` for the
  escrow deposit). "video" icon added to `_icons.html`; CCTV added to the
  contractor-registration trade list. Dashboard banner links to the intake page.
- ✅ Tests: `tests/test_phase1_cctv.py` (unit intake/quote with a fake provider +
  offline fallback, and end-to-end intake → job + matched contractor + quote).
  Full suite now 19 passing.
- ⏳ Remaining: live validation of a real transaction (book → escrow deposit →
  completion → payout via the existing flow); add more verticals (solar, …).
- **Next:** Phase 2 — fold ServiceSync Voice (CALL-E) into this CCTV flow.

### Phase 2 — Add ServiceSync Voice (CALL-E) into the CCTV workflow *(done)*
- ✅ `Job.matched_contractor_ids` persisted at CCTV intake so CALL-E phones the
  exact matched installers (not a global pool). `POST /api/v1/voice/dispatch`
  now prefers explicit `contractor_ids`, then `job.matched_contractor_ids`
  (CCTV match list), then the global available pool as a fallback.
- ✅ CALL-E task is CCTV-aware: `voice_dispatch._brief_context` turns the
  structured CCTV brief (cameras, coverage, features, wiring, budget, urgency)
  into a call-ready summary so CALL-E asks the right questions.
- ✅ Structured offers feed back into matching/quoting: the `/voice/{job_id}`
  status page shows each installer's availability, price, ETA, scope, and a
  **Book this offer** button (→ existing `/api/v1/jobs/{id}/book` → escrow pay).
  Offers are enriched with the contractor's real name/profession.
- ✅ CCTV intake page (`cctv_intake.html`) gained a "Call matched installers by
  phone" button that triggers the dispatch and opens the live status page.
- ✅ Tests: `tests/test_phase2_voice_cctv.py` (brief→call context; dispatch
  targets matched IDs and falls back to the available pool). Full suite 23 passing.
- **Next:** Phase 3 — confirm the AI backend is fully provider-swappable.

### Phase 3 — AI backend provider-swappable *(done)*
- ✅ Audited every AI call path. All routes go through `get_provider().complete(...)`
  (in `gemini_service.py`, `intake_service.py`, `quote_service.py`,
  `voice_dispatch.py`). Provider SDKs (`google.genai`, `groq`) are imported
  **only** inside `app/services/llm.py`; no call site imports a provider SDK.
- ✅ Switching is one env var: `AI_PROVIDER=gemini|groq|ollama`
  (`app/core/config.py`). `get_provider()` is cached per process; change the
  value and restart. No prompt/code changes required.
- ✅ Tests: `tests/test_phase3_provider_swappable.py` — runtime check that
  `AI_PROVIDER` selects the backend, `gemini_service` routes through
  `get_provider()`, plus static guards that provider SDKs stay inside the
  abstraction and that every AI call site imports `get_provider`. Full suite 28 passing.
- **Switching providers (how-to):** set `AI_PROVIDER` in `.env`
  (`gemini` default needs `GEMINI_API_KEY`; `groq` needs `GROQ_API_KEY`;
  `ollama` needs a running Ollama host). Every AI feature (triage, CCTV intake,
  quote builder, voice transcript extraction, contractor replies) follows
  automatically. All paths degrade gracefully (offline fallback) when no key.
- **Next:** Phase 4 — package the CALL-E portion as the hackathon contribution.

### Phase 4 — Package CALL-E as the CALL-E hackathon contribution *(done)*
- ✅ `docs/CALL_E_HACKATHON.md` — Devpost-ready write-up: problem, agentic flow,
  CALL-E API usage, architecture/module map (the isolated CALL-E surface),
  CCTV demo scenario, run + **offline/demo mode** instructions, a sample
  terminal-webhook `curl` to simulate a completed call, tests, and prize fit.
- ✅ Root `README.md` — points reviewers to the submission doc, quick-start,
  layout, and offline mode.
- ✅ CALL-E surface is self-contained: `calle_client.py` (httpx-only dependency)
  + `voice_dispatch.py` + `voice.py` + `webhooks.py` (calle) + UI templates; no
  vendor SDK leaks into the rest of the app.
- **Next:** Phase 5 (later) — supplier side + free-tools funnel. (The actual
  Devpost submission still needs your account — the artifacts are ready.)

### Phase 5 — Free-tools funnel + supplier side *(in progress)*
Funnel entry points + the start of the supplier side:
- ✅ Public, ad-supported **CCTV / security camera calculator**
  (`app/services/cctv_calculator.py`) — deterministic estimate of camera count
  (indoor/outdoor split), suggested features, storage, and a rough material
  budget by budget tier. No LLM/network — fast + always available (SEO + funnel).
- ✅ Public, ad-supported **solar system calculator**
  (`app/services/solar_calculator.py`) — system size, panel count, battery, and
  rough budget from electricity usage. Funnels to `/contractors?profession=solar`.
- ✅ API: `POST /api/v1/tools/cctv-calculator` + `POST /api/v1/tools/solar-calculator`
  (`app/api/v1/endpoints/tools.py`), registered under `/tools`.
- ✅ Public pages (no login): `/tools` index + `/tools/cctv-calculator` +
  `/tools/solar-calculator` with CTAs into the marketplace. "Free Tools" added to
  the public navbar + mobile menu. Ads live only on the free-tool side.
- ✅ **Third funnel tool — Service Quote Estimator**
  (`app/services/quote_calculator.py`) — deterministic labour + materials +
  callout + tax quote for 7 trades; `POST /api/v1/tools/quote-calculator` +
  `/tools/quote-calculator` page, CTA → `/contractors?profession=<trade>`.
- ✅ **Supplier side (begun)** — `app/models/all_models.py`: `Supplier`, `Product`,
  `JobMaterial` (bill of materials) + `MaterialOrder`. `app/services/supplier_service.py`:
  `recommend_materials_for_job` (derives a BOM from a job brief — CCTV/solar/
  generic), `search_products`, `match_products_for_bom`, `create_bom_for_job`,
  `place_material_order`, `fulfill_order`. API: `GET /api/v1/suppliers/products`
  (public catalogue), `POST /api/v1/suppliers/recommend` (customer-only; job
  brief → materials → matched supplier products), `POST
  /api/v1/suppliers/jobs/{job_id}/order` (place a material order → `ordered`),
  `POST /api/v1/suppliers/orders/{order_id}/fulfill` (contractor/admin →
  `delivered`).
- ✅ **Fourth + fifth funnel tools** — Project & Materials (BOM) calculator
  (`app/services/bom_calculator.py`, `POST /api/v1/tools/bom-calculator`,
  `/tools/bom-calculator`) and Market Service Price Estimator
  (`app/services/price_estimator.py`, `POST /api/v1/tools/price-estimator`,
  `/tools/price-estimator`). The `/tools` index now lists all 5 calculators.
- ✅ **Contractor Materials board** — `GET /materials` page + `templates/materials.html`
  (recommended BOM + order/deliver buttons); supplier `place_material_order` /
  `fulfill_order` endpoints now commit. Tests: `test_phase5_materials_ui.py`,
  `test_phase5_more_estimators.py`.
- ✅ **Prod migration** — `scripts/migrate.py` (idempotent, dialect-agnostic) +
  `docs/RELEASE.md` release-cut checklist.
- ✅ Tests: `test_phase5_funnel.py`, `test_phase5_solar_supplier.py`,
  `test_phase5_tools_procurement.py`, `test_phase5_materials_ui.py`,
  `test_phase5_more_estimators.py`. Full suite 54 passing.
- **Phase 5 = DONE** (funnel + supplier core complete).

### Phase 6 — Funnel → real transaction *(in progress)*
Turn funnel traffic into actual marketplace jobs (the revenue path):
- ✅ **Estimate → Job lead bridge** — `GET /tools/request-pro`
  (`app/web/pages.py`) creates a real `Job` (status `open`, category = trade,
  brief `source=free_tool`) for signed-in customers and redirects them into the
  marketplace (`/contractors?profession=<trade>`). The four estimator CTAs now
  route through it, so a calculator result becomes a quotable job. Guests are sent
  to sign-up first. Test: `test_phase6_funnel_lead.py`.
- ✅ **Lead routing + contractor lead board** — `app/services/lead_service.py`
  (`match_contractors_for_job`, `open_leads_for_contractor`,
  `notify_matched_contractors_for_lead`) matches open jobs to contractors by trade
  and emails matched contractors; `request_pro` now notifies matches. Contractors
  get a **new_lead** notification item and a `GET /leads` board
  (`templates/leads.html`) with *Message customer* (creates a `Conversation` via
  `POST /api/v1/jobs/{job_id}/interest`) → *Open chat*. `book_job` made
  idempotent re the conversation. Tests: `test_phase6_lead_routing.py`.
- ✅ **Offline pilot transaction** — `scripts/pilot_transaction.py` (`run_pilot()`)
  exercises the full loop lead → interest → book → escrow fund (mock) → complete →
  payout release (mock) with zero external services. Test: `test_phase6_pilot.py`.
- ✅ **CI + deploy scaffolding** — `.github/workflows/ci.yml` runs the offline
  sqlite pytest suite on push/PR; `Procfile` (`web: uvicorn app.main:app`) for the
  hosted platform. `docs/RELEASE.md` §7 CALL-E go-live + §8 push-to-deploy/
  auto-update.
- ⏳ Remaining for a *real* transaction: validate the booking → escrow fund →
  payout path with a **live Paystack key**; enable **live CALL-E** callbacks
  (`CALL_E_API_KEY` + public `CALL_E_WEBHOOK_BASE_URL`); run one pilot with real
  money. `UserCreate` now carries `profession`/`specialties` (previously dropped by
  the API signup — would have silently broken contractor lead matching). Full suite
  **58 passing**.
- **Next:** close the live-payment + live-voice gaps and produce a pilot
  transaction; then this becomes the XPRIZE/hackathon "real business, real users,
  real revenue" proof.

---

## 5. Open questions / risks
- Real CALL-E response shape for `result_schema` / `structured_result` is inferred
  from the spec — confirm against a CALL-E test call before relying on it.
- Calling-region support for Nigeria is uncertain — voice dispatch is designed
  global (region hint only, never hardcoded).
- Need a public `CALL_E_WEBHOOK_BASE_URL` (hosted URL) to receive live callbacks;
  otherwise rely on the poll endpoint.
- Folder on disk is misspelled `ServiceSycn` (repo is `ServiceSync`) — consider
  renaming to avoid confusion in CI/docs.
- New model columns (`Job.category`, `Job.brief`, `User.specialties`,
  `Job.matched_contractor_ids`) and new tables (`Supplier`, `Product`,
  `JobMaterial`, `MaterialOrder`) need a **prod DB migration** — SQLModel `create_all`
  only affects fresh schemas. Use `python scripts/migrate.py` (idempotent,
  dialect-agnostic) or see `docs/RELEASE.md` before deploying Phases 1/5.

---

## 6. Update Log (newest first)
- **2026-08-16 (Phase 6 progress)** — Lead routing + contractor lead board:
  `app/services/lead_service.py` matches open jobs to contractors by trade and
  emails matched contractors; `request_pro` now notifies them. Added `GET /leads`
  (`templates/leads.html`), `POST /api/v1/jobs/{job_id}/interest` (creates a
  `Conversation` → *Open chat*), and a contractor `new_lead` notification. Added
  offline `scripts/pilot_transaction.py` (`run_pilot`) + CI (`.github/workflows/ci.yml`)
  and `Procfile`; `docs/RELEASE.md` §7 CALL-E go-live + §8 push-to-deploy. **Bug
  fix:** `UserCreate` did not include `profession`/`specialties`, so API signup
  silently dropped the contractor trade and broke lead matching — fixed in
  `app/schemas/user.py`. Also fixed a test-global rate-limiter leak (reset
  `RateLimitMiddleware._hits` per test in `tests/conftest.py`). Full suite
  **58 passing**.
- **2026-08-16 (Phase 6 progress)** — Started the funnel→transaction bridge:
  `GET /tools/request-pro` turns a free-tool estimate into a real `Job` lead for
  signed-in customers (status `open`, `brief.source=free_tool`) and redirects into
  the marketplace; the four estimator CTAs now route through it. Guests are sent to
  sign-up. Added `tests/test_phase6_funnel_lead.py`.
- **2026-08-16 (Phase 5 progress)** — Added two more funnel estimators: Project &
  Materials (BOM) calculator (`app/services/bom_calculator.py`,
  `POST /api/v1/tools/bom-calculator`, `/tools/bom-calculator`) and Market Service
  Price Estimator (`app/services/price_estimator.py`, `POST /api/v1/tools/price-estimator`,
  `/tools/price-estimator`); `/tools` index now lists 5 calculators. Added
  `tests/test_phase5_more_estimators.py`. Phase 5 declared done; added
  `scripts/migrate.py` (idempotent prod migration) + `docs/RELEASE.md` release-cut
  checklist. Full suite **54 passing**.
- **2026-08-16 (Phase 5 progress)** — Closed the supplier loop with a contractor/
  admin **Materials board** (`GET /materials` page + `templates/materials.html`,
  linked from the contractor dashboard + nav). It shows each assigned job's
  recommended BOM and procurement status, with *Order materials* and *Mark
  delivered* buttons that drive the existing procurement endpoints. Added
  `box` icon. **Bug fix:** the procurement endpoints only flushed, never committed
  — orders/fulfilments were never persisted; added `await db.commit()` to both
  (`order_materials`, `fulfill_material_order`). Added `tests/test_phase5_materials_ui.py`
  and a DB-persistence regression guard in `test_phase5_tools_procurement.py`; full
  suite **47 passing**.
- **2026-08-16 (Phase 5 progress)** — Added a third funnel tool (Service Quote
  Estimator: `app/services/quote_calculator.py`, `POST /api/v1/tools/quote-calculator`,
  `/tools/quote-calculator` page) and built the supplier procurement/delivery
  workflow: `MaterialOrder` model + `place_material_order`/`fulfill_order` in
  `supplier_service.py`, and endpoints `POST /api/v1/suppliers/jobs/{job_id}/order`
  + `POST /api/v1/suppliers/orders/{order_id}/fulfill`. Tools index now lists all
  three calculators. Added `tests/test_phase5_tools_procurement.py`; full suite
  44 passing.
- **2026-08-16 (Phase 5 progress)** — Added a second funnel tool (solar system
  calculator: `app/services/solar_calculator.py`, `POST /api/v1/tools/solar-calculator`,
  `/tools/solar-calculator` page, CTA → `/contractors?profession=solar`) and
  began the supplier side: `Supplier`/`Product`/`JobMaterial` models,
  `app/services/supplier_service.py` (brief → BOM recommendation + catalogue
  match), and `GET /api/v1/suppliers/products` + `POST /api/v1/suppliers/recommend`
  endpoints. Tools index now lists both calculators. Added
  `tests/test_phase5_solar_supplier.py`; full suite 40 passing. Noted the new
  tables need a prod migration.
- **2026-08-16 (Phase 5 progress)** — Started the free-tools funnel. Added a
  public, ad-supported CCTV/security camera calculator
  (`app/services/cctv_calculator.py`, deterministic — no LLM/network), the
  `POST /api/v1/tools/cctv-calculator` endpoint, and public pages `/tools` +
  `/tools/cctv-calculator` with a CTA into `/cctv/intake`. "Free Tools" added to
  the navbar/mobile menu; ad slots only on the free-tool side. Added
  `tests/test_phase5_funnel.py`; full suite 33 passing. Supplier side + more
  calculators remain.
- **2026-08-16 (Phase 4 progress)** — Packaged the CALL-E integration as the
  hackathon contribution. Added `docs/CALL_E_HACKATHON.md` (Devpost-ready:
  problem, agentic flow, CALL-E API usage, isolated module map, CCTV demo,
  offline/demo mode, webhook-simulation curl, tests, prize fit) and a root
  `README.md` pointing reviewers to it. CALL-E surface is self-contained
  (httpx-only client + orchestration + endpoints + UI). ROADMAP Phase 4 marked done.
- **2026-08-16 (Phase 3 progress)** — Audited provider-swappability. Confirmed
  every AI call path routes through `get_provider().complete(...)`; provider SDKs
  live only inside `app/services/llm.py`. Switching is a single `AI_PROVIDER`
  env var (gemini/groq/ollama), no code changes. Added
  `tests/test_phase3_provider_swappable.py` with runtime + static guards; full
  suite 28 passing. Documented the switch in §4 Phase 3.
- **2026-08-16 (Phase 2 progress)** — Folded ServiceSync Voice (CALL-E) into the
  CCTV flow. `Job.matched_contractor_ids` persists the CCTV intake match list;
  `POST /api/v1/voice/dispatch` targets matched IDs (or explicit `contractor_ids`)
  before falling back to the global available pool. CALL-E task is now
  CCTV-aware via `_brief_context`. The `/voice/{job_id}` status page shows
  structured offers with contractor names and a "Book this offer" action; the
  CCTV intake page has a "Call matched installers by phone" button. Added
  `tests/test_phase2_voice_cctv.py`; full suite 23 passing.
- **2026-08-16 (Phase 1 progress)** — CCTV vertical started end-to-end. Added
  `Job.category`/`Job.brief` and `User.specialties` to the model; new
  `app/services/intake_service.py` (AI intake → structured `JobBrief`, offline
  fallback) and `app/services/quote_service.py` (AI quote builder). New
  `app/api/v1/endpoints/cctv.py` (`POST /api/v1/cctv/intake`,
  `POST /api/v1/cctv/{job_id}/draft-quote`) with vertical-aware contractor
  matching; registered under `/cctv`. UI: `/cctv/intake` page + template, a
  "video" icon, CCTV in the contractor trade list, and a dashboard banner. Added
  `tests/test_phase1_cctv.py`; full suite 19 passing. Booking reuses the existing
  job-book + escrow-pay flow.
- **2026-08-16 (Phase 0 progress)** — Escrow double-receipt/TOCTOU guard:
  added `_issue_receipt` (dedupe by `payment_reference`) used by `fund_escrow`
  and `mark_escrow_paid_by_reference`. Added offline test setup (`conftest.py`
  sqlite + `pytest.ini`) and regression suites: `regression_security.py`
  (signup coercion, token-type rejection, banned-user rejection, Paystack webhook
  auth) and `regression_escrow.py` (idempotent funding / webhook). All 14 tests
  pass. Websocket now re-syncs chat history from the DB on connect; client
  dedupes by message id. Roadmap restructured to the confirmed 5-step build order.
- **2026-08-16** — Added vision + roadmap (this doc) and `.env.example`. Built
  ServiceSync Voice (CALL-E): client, dispatch service, API endpoints, webhook,
  status page, dashboard link. Hardened security + added LLM provider abstraction
  in prior sessions (see §3).
