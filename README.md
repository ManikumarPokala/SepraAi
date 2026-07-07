# SepraAI v2.7 — Hardened Map-Reduce AI Media Platform

SepraAI v2.7 is an asynchronous, high-throughput Map-Reduce AI media generation platform built on top of FastAPI, PostgreSQL (pgvector), Redis (ARQ), LangGraph, and specialized worker pools. This version implements all 13 distributed system and cloud security patches mandated by the Red Team audit.

---

## 🛡️ v2.7 Hardening Directives Matrix

| Patch Category | Rule Name | Description | Mitigated Vulnerability |
| :--- | :--- | :--- | :--- |
| **Database & Concurrency** | The Transaction Rule | Wraps asset cache insertion and chunk updates in a single SQL transaction block. | Dual-render race conditions & storage leakage (#1, #12) |
| | The Rollup Rule | Workers write to child chunk status tables. A serialized manager rolls up states to parent jobs. | Lock contention & DLQ exhaustion floods (#2) |
| | The Immutability Rule | PostgreSQL `BEFORE UPDATE` trigger on GCM table prevents mid-render style alterations. | TOCTOU parameter drift attacks (#13) |
| **Execution & Queues** | The Heartbeat Rule | Background job heartbeat runners extend visibility locks every 15s. | Zombie worker timeout restarts (#4) |
| | The Seccomp Rule | Blocks network syscalls (`socket`, `connect`) inside container schedulers. | SSRF and AST code execution escapes (#3) |
| | The Schema Rule | Strict Pydantic parsing with `extra="forbid"` blocks rogue keys and traversals. | Unsafe deserialization exploits (#8) |
| | The KEDA Rule | Scales warm vLLM GPU healing worker pools to `0` when queue is idle. | Idle VRAM compute burn costs (#10) |
| **Media & AI** | The CBR Rule | Enforces CBR WAV transcoding and validates decoded samples vs metadata headers within 1ms. | Timeline visual/audio drift anomalies (#5, #6) |
| | Agent Consensus | LangGraph Consensus Node resolves conflicting Professor & Art Director loop deadlocks. | Infinite feedback loop lockups (#11) |
| | Attempt Escalation | Elevates LLM generation temperature, injects negative context history, and overrides layouts. | Repeated styling script fail loops (#7) |

---

## 📁 Repository Layout

```
sepraai-backend/
├── api/
│   ├── main.py                   # Central FastAPI gateway
│   ├── routes.py                 # Core endpoints and RBAC approvals
│   ├── dependencies.py           # DB session context yields
│   ├── backpressure.py           # 429 gateway rate-limiting
│   └── input_sanitizer.py        # Input verification gates
├── core/
│   ├── config.py                 # App environment parameters
│   ├── database.py               # SQL engines & migrations
│   ├── models.py                 # SQLAlchemy schemas & ORM event handlers
│   ├── schemas.py                # Strict Pydantic parsing specifications
│   └── concurrency.py            # Optimistic locks & atomic commits
├── orchestration/
│   ├── semantic_splitter.py      # WhisperX snaps & silence boundaries
│   ├── time_scaler.py            # Audio sync and sample drift verification
│   └── arq_broker.py             # Heartbeats & job brokers
├── agents/
│   ├── graph.py                  # LangGraph multi-agent flow
│   ├── consensus_node.py         # Consensus feedback audit rules
│   ├── healing_agent.py          # Attempt parameters escalation
│   └── ...                       # Grounding, Professor, and Studio editors
├── workers/
│   ├── sandbox_runtime.py        # AST linter and subprocess execute blocks
│   ├── run_worker_manim.py       # Manim render task worker
│   ├── run_worker_remotion.py    # Remotion render task worker
│   ├── run_worker_gpu.py         # WhisperX & NVENC alignment task worker
│   ├── run_worker_healing.py     # Self-healing warm pool task worker
│   └── ...                       # CLI adapters & metadata muxers
├── infrastructure/
│   ├── docker/                   # Five specialized Dockerfiles
│   ├── docker-compose.yml        # Multi-AZ compose stack
│   ├── prometheus/               # Prometheus configuration
│   ├── keda-healing-scaler.yaml  # Auto-scaling configurations
│   └── seccomp-render-profile.json # Syscall filter profile
└── tests/
    └── ...                       # Security, Splitter, and CBR drift tests
```

---

## 🚀 Getting Started

### 1. Boot backing infrastructure
Run the bootstrap script to spawn Docker database/redis dependencies and initialize DB schemas:
```bash
./start_local.sh
```

### 2. Start the API Gateway
Expose the FastAPI gateway:
```bash
export PYTHONPATH=./sepraai-backend
uvicorn api.main:app --reload --port 8000
```

### 3. Start task worker queues
Launch task workers:
```bash
export PYTHONPATH=./sepraai-backend
arq orchestration.arq_broker.WorkerSettings
```

### 4. Trigger test generation request
Submit the sample payload file using curl:
```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d @sample_request.json
```

---

## 🧪 Running Verification Tests
Execute the self-contained offline test runner to verify sandbox boundaries, idempotency, split snaps, and CBR drift validations:
```bash
python3 run_offline_tests.py
```
*Result: 18 tests passed, 0 failures (100% success).*
# SepraAi
