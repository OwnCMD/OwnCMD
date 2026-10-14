# Architecture and contributor map

| Area | Files | Responsibility |
|---|---|---|
| Web/API | `app/main.py` | Sessions, CSRF/origin policy, conversations, files, usage and streaming |
| Community identity | `app/community.py` | Bootstrap, invitation lifecycle, provider settings routes |
| Instance policy | `app/accounts.py`, `app/admin_routes.py`, `app/code_network.py` | Owner/member roles, model choices, resource/network policy, audit |
| Secrets | `app/integrations.py` | Encrypted live configuration; optional environment fallback |
| Usage | `app/billing.py`, `app/conversation_usage.py` | Provider usage, pending estimates, idempotent settlement; historical module name retained |
| Execution | `app/worker.py`, `app/chat.py`, `app/providers.py`, `app/tools.py` | Task orchestration and provider/tool interfaces |
| Isolation | `app/broker.py`, `sandbox/`, `firewall.sh` | Authenticated Docker control, gVisor, restricted network and workspaces |
| Persistence | `app/core.py`, `app/database.py`, `app/workspace_storage.py` | Encrypted state, PostgreSQL and checkpoints |
| User features | `app/documents.py`, `app/skills.py`, `app/notebook.py`, `app/scheduling.py` | Documents, skills, durable task notes and scheduling |
| Frontend | `frontend/components/` | Shared app/workspace UI plus CommunitySettings, Auth and Usage |
| Installation | `install.sh`, `scripts/configure_*.py`, `asterctl` | System packages, site/database setup, service lifecycle |

The API and worker read credentials at request time from the same encrypted database setting. UI updates therefore take effect without restarting either process. Environment fallback is for initial provisioning; saved instance values, including explicit empty removal, win.

Accounting keeps `hold_nano`, `cost_nano` and `charge_nano` column names for compatibility with provider reconciliation and existing report code. `charge_nano` equals provider cost with multiplier one. Holds are estimates, not money reserved from a wallet. No credit transaction table is created.

The Community distribution removes SaaS payments, SMTP, public signup verification, email recovery, commercial support ticketing and the SaaS knowledge-base CMS. Core document handling, skills, memory, schedules, browser and coding workspaces remain. The smaller owner settings UI replaces the SaaS administration dashboard.
