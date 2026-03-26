# 🌌 Hybrid RAG — Product Roadmap

A multi-phase plan to evolve the Hybrid RAG chatbot into a production-ready, enterprise-grade AI platform.

---

## Phase 1 — Architecture & Governance ✅ *(Month 1)*

> Foundation: authentication, access control, and audit logging.

| Item | Detail |
|:---|:---|
| **RBAC** | Three roles: `superadmin` (full system), `admin` (data/params), `user` (chat only) |
| **Auth** | JWT-based login; tokens stored in `localStorage`; 24-hour expiry |
| **User Store** | `data/users.json` — no extra database needed |
| **Audit Engine** | Append-only `data/audit_log.json` tracks every admin action (who, what, before/after) |
| **Default Account** | `admin / admin` (superadmin) auto-seeded on first boot |

**New files:** `app/auth.py`, `app/api/auth_routes.py`, `app/services/user_service.py`, `app/services/audit_service.py`

---

## Phase 2 — RAG Core & Data Ingestion *(Month 2)*

> Make retrieval parameters tunable at runtime without restarting the app.

| Item | Detail |
|:---|:---|
| **Runtime Config** | UI sliders for `k` (chunk retrieval count), `q` (query expansion), and Similarity Threshold |
| **Config API** | `PATCH /api/config/rag` stores values; RAG pipeline reads them live |
| **Data Pipeline** | Already supports PDF, Excel, and Web crawl — wire to the new config |

---

## Phase 3 — Admin Control Plane *(Month 3)*

> Give Admins tools to customise the AI and test safely before going live.

| Item | Detail |
|:---|:---|
| **AI Persona Suite** | UI for customising system prompts and agent "personalities" per role |
| **Pre-Deploy Sandbox** | "Draft Mode" — Admins test `k/q/threshold` changes privately before publishing |
| **Chat History Storage** | Persist all conversations to a permanent database (not just in-session JSON) |

---

## Phase 4 — Observability & Feedback *(Month 4)*

> See what's happening and let users signal quality.

| Item | Detail |
|:---|:---|
| **Token Dashboard** | Real-time tracker for token usage, API cost, and volume per user/role |
| **Admin Chat Logs** | Global view for Admins to monitor all past and live user conversations |
| **👍 / 👎 Feedback** | Binary feedback button on every bot reply; stored with the `k/q` version used |

---

## Phase 5 — Refinement & Accuracy Sprints *(Month 5–6)*

> Use data from Phase 4 to systematically improve accuracy.

| Item | Detail |
|:---|:---|
| **Accuracy Baseline** | Mine Chat Logs to identify common failure points |
| **Hyperparameter Tuning** | Use Admin Panel sliders to tune Threshold + Persona toward accuracy targets (e.g. 85% → 95%) |
| **UX Polish** | Refine the chat interface; ensure source citations are clear and accessible |

---

## Phase 6 — Security & Production Launch *(Month 7)*

> Harden, stress-test, and ship.

| Item | Detail |
|:---|:---|
| **Stress Testing** | Concurrency tests simulating high user load |
| **Security Hardening** | Tamper-proof audit logs; encrypt user data at rest |
| **Production Launch** | Promote Admin Sandbox settings to the live environment |

---

## Key Requirements Checklist

| Requirement | Implementation |
|:---|:---|
| Audit Log | Tracks every setting change (e.g. *"admin changed k from 4 to 6"*) |
| AI Settings | UI sliders for `k`, `q`, and Similarity Threshold |
| Token Dashboard | Real-time cost monitoring by user and model |
| Feedback | Binary 👍/👎 stored with the specific `k/q` version used |
| Admin Pre-deploy | "Draft Mode" for AI settings — won't affect live bot until published |

---

## Running Locally

```bash
# Build & start (first time or after dependency changes)
sudo docker compose build rag-app
sudo docker compose up -d

# View logs
sudo docker compose logs -f rag-app
```

Default login: **admin / admin** (change immediately after first boot)
