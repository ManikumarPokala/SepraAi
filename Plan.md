# SepraAI — The Autonomous, Self-Healing Media Infrastructure Platform
### v2.6 — Hardened Edition (fixes: chunk-length bound, beat traceability, execution sandboxing, idempotency, lock-conflict policy, cost granularity, review-gate authz, GCM immutability, gateway backpressure; corrected: object-store idempotency pattern, sandbox is scheduler-level not image-level)

---

## Changelog

**v2.4 → v2.5:**

| # | Gap in v2.4 | Fix in v2.5 |
|---|---|---|
| 1 | Silence-snap had no max chunk length; dense narration could blow past 30s target indefinitely | Hard cap (45s); force-split at local speech-energy minimum if no true silence gap found |
| 2 | `chunks` had no FK back to `atomic_beats` | Added `chunks.atomic_beat_id` |
| 3 | LLM-generated Manim/Remotion code executed with no sandboxing — prompt-injection defense only covered ingestion, not generated code execution | Sandboxed execution + static AST allowlist lint by Art Director Agent pre-dispatch |
| 4 | At-least-once queue delivery had no idempotency guarantee | Pre-render cache/status check before render |
| 5 | Optimistic lock (`version` column) conflicts had no resolution policy | Bounded jittered retry (3x, 50–200ms) → escalate to DLQ |
| 6 | `cost_attribution` keyed only at `video_part_job_id`, losing per-renderer/per-chunk cost visibility | Added nullable `chunk_id` + `pool` columns |
| 7 | Review Gate had no access control or audit trail | RBAC on `/approve` + `approved_by` column |
| 8 | GCM could be silently mutated/re-pointed mid-series, undermining stylistic-drift guarantee | GCM created once per `curriculum_jobs`, immutable after part 1 renders |
| 9 | No backpressure between Gateway and downstream queues | Gateway checks queue depth, returns 429 + `Retry-After` past threshold |

**v2.5 → v2.6** (two cloud-primitive corrections):

| # | Flaw in v2.5 | Fix in v2.6 |
|---|---|---|
| 10 | Idempotency contract specified "atomic commit-then-rename on MinIO writes" — object stores have no atomic rename, only non-atomic copy+delete | `PUT` directly to a deterministic key (safe to overwrite on redelivery); Postgres `chunks.status` write, not the storage layer, is the actual commit point |
| 11 | Deployment section said the sandbox runtime "must be baked into `Dockerfile.worker.manim`" — nesting a microVM hypervisor in a Docker image requires `--privileged`, which defeats the isolation boundary | Sandbox is enforced at the scheduler level: `gVisor` RuntimeClass on Kubernetes, or Fargate (natively Firecracker-backed) on ECS — Dockerfiles are unchanged from v2.4 |

Everything else from v2.4 (dual-channel generation, proportional timing inversion, declarative scene checkpoints, batched grounding, assembly-layer-only ducking, split CPU/GPU/healing pools) is retained unchanged — those were already correctly solved.

---

## 1. Executive Summary

SepraAI is a fault-tolerant backend infrastructure designed to autonomously generate 10–20 minute educational videos. Standard AI media pipelines fail at scale due to context limits, memory leaks, temporal desync, and — the risk this revision closes — **unsandboxed execution of model-generated code**. SepraAI solves these through an asynchronous Map-Reduce Orchestration Pattern, an Autonomous Verification State Machine, and (new in v2.5) an isolated execution boundary between "what the model wrote" and "what actually runs."

Core Engineering Solutions (carried forward):
- **Dual-Channel Generation** — decouples spoken narrative from programmatic visual code.
- **Proportional Timing Inversion** — rescales visual timing to match phonetic timestamps without breaking chained animation dependencies.
- **Stateless Ephemeral Chunking with Declarative Scene Checkpoints** — pure-JSON state snapshots, never pickled Manim objects.
- **Global Context Manifest (GCM)** — now immutable per curriculum series (v2.5 fix #8).
- **Assembly-Layer Audio Ducking** — applied once globally, never per-chunk.
- **Batched Grounded Verification** — one fact-check pass pre-split, not 40+ per-chunk calls.

New in v2.5:
- **Bounded Chunking** — silence-snapping with a hard max-length fallback.
- **Sandboxed Rendering Execution** — generated code never runs with ambient filesystem/network access.
- **Idempotent Worker Contracts** — safe under at-least-once queue delivery.

---

## 2. System Architecture Topology

```
[ 1. GATEWAY ] ---> FastAPI (Ingests curriculum params; sanitizes input against prompt injection;
                     NEW: checks cpu-manim/cpu-remotion queue depth, returns 429 + Retry-After
                     past configured backpressure threshold)
                      │
[ 2. STATE ] -----> PostgreSQL + pgvector (Job state, GCMs, Scene Checkpoints, Asset Hashes)
                      │
[ 2.5 BATCH GROUNDING ] -> Professor Agent fact-checks the FULL curriculum script once, pre-chunk
                      │
[ 2.75 FULL TTS + ALIGN ] -> Full-script TTS, then WhisperX word-level alignment + silence-gap
                      detection, BEFORE any chunk boundary is fixed
                      │
[ 3. ORCHESTRATOR ]-> Map-Reduce Semantic Splitter
                      (~30s target, snapped to nearest silence gap;
                       NEW: hard cap at 45s — if no true silence gap falls within tolerance,
                       force-split at the local minimum of speech energy instead of drifting
                       past the VRAM-safe chunk-length budget)
                      │
[ 4. VERIFICATION ]-> LangGraph Multi-Agent Squad ("Production House")
                      ├── Professor Agent: per-chunk logic/code checks (facts already grounded)
                      ├── Art Director Agent: 12-Column Grid enforcement, Manim/Remotion routing,
                      │             NEW: static AST/lint allowlist pass on generated visual code
                      │             before it is ever dispatched to a worker (blocks imports,
                      │             subprocess calls, filesystem/network access outside the
                      │             checkpoint I/O contract)
                      └── Studio Editor: WhisperX timestamps, proportional time-scale map
                      │
[ 4.5 HEALING POOL ] -> Persistently warm GPU instance serving vLLM/Llama-3, isolated from the
                      ephemeral WhisperX/NVENC pool
                      │
[ 5. EXECUTION ] ---> Three Worker Pools (Redis + ARQ), each running inside an isolated sandbox
                      (microVM or restrictive seccomp profile, no network, no filesystem access
                      outside the declared checkpoint I/O path) — NEW: closes the gap where
                      prompt-injection defense covered ingestion but not generated-code execution
                      ├── CPU Pool (Manim): video + voiceover only; idempotent — checks
                      │             asset_cache by content_hash before rendering, commits to
                      │             MinIO via write-temp-then-atomic-rename so a redelivered
                      │             job is a safe no-op
                      ├── CPU Pool (Remotion): same idempotency + sandbox contract
                      └── GPU Pool: WhisperX alignment + NVENC encoding (ephemeral, autoscaled)
                      │
[ 6. ASSEMBLY ] ----> FFmpeg Concatenator — uniform encode profile, one continuous background
                      track, global sidechaincompress ducking, fallback slides padded to exactly
                      match original chunk audio duration
                      │
[ 7. REVIEW GATE ] -> Human-in-the-loop preview + approval, NEW: RBAC-gated `/approve` endpoint,
                      `approved_by` recorded for audit
```

---

## 3. Technology Stack

Unchanged from v2.4, with one addition:

**Execution Isolation (NEW):** gVisor or Firecracker microVMs (or, at minimum, a locked-down seccomp/AppArmor profile with network egress disabled) wrapping every Manim and Remotion render subprocess. This is a distinct control from `input_sanitizer.py` — it protects against the *generated code itself* misbehaving or being adversarially steered via injection that survives ingestion sanitization, not just against malicious curriculum input.

---

## 4. Production Folder Structure

```
sepraai-backend/
├── api/
│   ├── routes.py                 # FastAPI endpoints (/generate, /status, /approve — RBAC-gated)
│   ├── dependencies.py           # DB sessions, Auth, Hash-Cache Middleware
│   ├── backpressure.py           # NEW: queue-depth check, 429 + Retry-After
│   └── input_sanitizer.py        # Strips/escapes curriculum input against prompt injection
├── core/
│   ├── config.py
│   ├── schemas.py                 # AtomicBeat, GCM, VideoPartJob, SceneCheckpoint
│   └── database.py
├── orchestration/
│   ├── semantic_splitter.py       # NEW: hard max-chunk-length fallback via speech-energy minimum
│   ├── time_scaler.py
│   └── arq_broker.py              # cpu-manim, cpu-remotion, gpu-align, healing
├── agents/
│   ├── graph.py
│   ├── batch_grounding_agent.py
│   ├── professor_agent.py
│   ├── art_director_agent.py      # NEW: static AST/lint allowlist pass before dispatch
│   ├── studio_editor_agent.py
│   └── healing_agent.py
├── workers/
│   ├── sandbox_runtime.py         # NEW: microVM/seccomp wrapper shared by Manim + Remotion workers
│   ├── run_worker_manim.py        # NEW: idempotency check via content_hash before render
│   ├── run_worker_remotion.py     # NEW: same idempotency contract
│   ├── run_worker_gpu.py
│   ├── run_worker_healing.py
│   ├── manim_renderer.py
│   ├── remotion_renderer.py
│   ├── scene_checkpoint.py        # {chunk_id, renderer_type, objects[]}
│   └── ffmpeg_muxer.py
├── infrastructure/
│   ├── docker/ (unchanged five images)
│   ├── docker-compose.yml
│   └── prometheus/
└── tests/
    └── test_sandbox_escape.py     # NEW: adversarial test — confirm generated code cannot reach
                                    #      network/filesystem outside the checkpoint contract
```

---

## 5. Database Architecture & Schemas

### 5.1 Entity Relationship Overview

```
curriculum_jobs (1) ──< video_part_jobs (1) ──< atomic_beats (1) ──< chunks (1) ──< scene_checkpoints
       │                       │                       │  ▲                │
       │                       └──< [gcm_id, immutable] │  └── NEW FK ──────┘  ├──< healing_attempts
       │                                                │                     ├──< asset_cache (content_hash)
       └──< cost_attribution [+ chunk_id, pool] (NEW)   └──── chunks.atomic_beat_id (NEW)
                                                                              └──< dead_letter_queue
```

### 5.2 Core Tables (deltas only — unchanged tables/columns from v2.4 omitted for brevity; full v2.4 schema still applies)

**`chunks`** (added column)

| Column | Type | Notes |
|---|---|---|
| `atomic_beat_id` | UUID FK | **NEW** — links each chunk back to the grounded script segment it was split from, so healing/debugging/Professor Agent checks have full provenance |

**`cost_attribution`** (added columns)

| Column | Type | Notes |
|---|---|---|
| `chunk_id` | UUID FK NULLABLE | **NEW** — null = job-level overhead (grounding, TTS, assembly); set = per-chunk render cost |
| `pool` | ENUM | **NEW** — `cpu_manim`, `cpu_remotion`, `gpu_align`, `gpu_healing`; enables true unit-economics breakdown by pool, which the CPU/GPU split architecture was designed around but the v2.4 schema didn't actually expose |

**`global_context_manifests`** (behavior change, no schema change)

- **NEW constraint (enforced at application layer, not DB):** one GCM row is created at `curriculum_jobs` creation time and referenced by every `video_part_jobs` row in that series. After `video_part_jobs` part 1 reaches `rendering`, the GCM row becomes immutable — any requested style change requires a new `curriculum_jobs` entry, not a mutation of the shared GCM. This closes the v2.4 gap where nothing stopped part 3 of a series from silently drifting to a different manifest.

**`video_part_jobs`** (added column)

| Column | Type | Notes |
|---|---|---|
| `approved_by` | TEXT/UUID NULLABLE | **NEW** — set by the RBAC-gated `/approve` endpoint; audit trail for the Review Gate |

All other v2.4 tables (`atomic_beats`, `scene_checkpoints`, `asset_cache`, `healing_attempts`, `dead_letter_queue`) are unchanged.

### 5.3 Indexing & Concurrency Strategy — additions

- `CREATE INDEX ON chunks (atomic_beat_id)` — supports the new provenance lookup.
- `CREATE INDEX ON cost_attribution (video_part_job_id, pool)` — supports per-pool cost rollups.
- **Optimistic lock conflict policy (NEW, closes v2.4 gap):** on a `version` mismatch during `UPDATE ... WHERE version = :expected`, the writer retries up to 3 times with jittered backoff (50–200ms). If all 3 attempts still conflict, the write is abandoned and the chunk/job is pushed to the same Dead-Letter Queue path used for exhausted healing retries, with `reason = 'lock_contention'`.
- **Idempotency contract (NEW, closes v2.4 gap — corrected in v2.6):** before rendering, a worker checks `chunks.status` and `asset_cache.content_hash`. If a matching cache entry already exists, or `chunks.status` is already past `rendering` for this `chunk_id`, the job is a no-op ack. Object keys are deterministic (derived from `chunk_id`/`content_hash`), and the worker `PUT`s directly to the final MinIO/S3 key — object stores have no atomic rename primitive (only copy+delete, which is non-atomic), but a `PUT` to a fixed key is itself atomic at the object level, so a redelivered ARQ job simply overwrites the same key with the same bytes. The commit point that actually makes this idempotent is the Postgres `chunks.status` write after the `PUT` succeeds — not anything at the storage layer.

---

## 6. Architectural Decision-Making Log (ADR additions for v2.5)

| Decision | Technology Chosen | Engineering Rationale |
|---|---|---|
| Chunk Length Bound | Hard 45s cap with speech-energy-minimum fallback split | Pure silence-snapping has no upper bound; dense narration (common in technical content) could produce chunks large enough to reintroduce the VRAM-leak risk the 30s chunking was built to prevent. A hard cap with a graceful fallback (split at the quietest point found, even if not true silence) preserves the AV-sync goal without an unbounded worst case. |
| Execution Sandboxing | gVisor RuntimeClass (Kubernetes) or Fargate/Firecracker (ECS) at the scheduler level — **not** baked into the worker Dockerfiles | `input_sanitizer.py` defends the *ingestion* boundary (curriculum text → prompt injection). It does not defend the *execution* boundary: the actual code that runs is LLM-generated Manim Python / Remotion JS. Treating that generated code as untrusted and sandboxing its execution closes a code-execution risk that's structurally separate from — and larger than — prompt injection at the Gateway. Corrected in v2.6: nesting a microVM hypervisor inside a Docker image requires `--privileged`, which defeats the boundary — the sandbox has to be enforced by how/where the container is scheduled (RuntimeClass / Fargate), not by anything in the image itself. |
| Idempotent Worker Contract | Content-hash pre-check + deterministic-key `PUT` (Postgres status write as commit point) | ARQ/Redis delivery is at-least-once. Without an idempotency check, a redelivered job after a mid-render crash can double-render or leave the cache/DB in an inconsistent state. Object stores (S3/MinIO) have no atomic rename primitive — only non-atomic copy+delete — so the safe pattern is a `PUT` to a fixed, deterministic key (safe to overwrite) with Postgres, not the storage layer, as the source of truth for "is this chunk done." |
| Lock Conflict Resolution | Bounded jittered retry → DLQ escalation | An optimistic `version` column without a stated conflict-resolution policy just moves the failure mode from "silent corruption" to "silent infinite retry" or "silent drop." Bounding it and routing to the existing DLQ/human-review path reuses infrastructure already built for healing exhaustion. |
| Cost Attribution Granularity | Added `chunk_id` (nullable) + `pool` to `cost_attribution` | The entire platform is architected around CPU/GPU/healing pool separation specifically for cost reasons, but v2.4's cost table couldn't actually answer "what did the Remotion pool cost us this month" — only job-level totals. |
| Review Gate Access Control | RBAC on `/approve`, `approved_by` audit column | An approval gate with no access control is not a control — anyone hitting the endpoint can publish. |
| GCM Lifecycle | Immutable per curriculum series after part 1 renders | The GCM's entire purpose is guaranteeing zero stylistic drift across a multi-part series; nothing in v2.4 actually enforced that the same manifest stays attached to every part, so drift could reappear via silent mutation. |
| Gateway Backpressure | Queue-depth check + 429/Retry-After | Without backpressure, a burst of `/generate` calls floods Postgres and Redis before the ASGs react, risking cascading failure at exactly the layer meant to absorb load spikes. |

---

## 7. Implementation Planning: Risk-First Sprints (deltas)

**Sprint 1 (add):** Add `chunks.atomic_beat_id`, `cost_attribution.chunk_id`/`pool`, `video_part_jobs.approved_by` to migrations. Add backpressure middleware to Gateway.

**Sprint 2 (add):** `semantic_splitter.py` implements the 45s hard cap with speech-energy-minimum fallback split, not silence-snap-only.

**Sprint 3 (add):** Art Director Agent gains a static AST/lint allowlist pass (block imports, subprocess, filesystem/network calls outside the checkpoint I/O contract) that runs *before* a chunk is dispatched to a worker — a rejection here routes to healing, not straight to the sandbox.

**Sprint 4 (add):** `sandbox_runtime.py` wraps both `run_worker_manim.py` and `run_worker_remotion.py`; add `test_sandbox_escape.py` as a required CI gate — a render job that successfully reaches network or filesystem outside its declared I/O path fails the build. Add idempotency check (`content_hash` + status) as the first line of both render workers; uploads `PUT` directly to a deterministic key (no copy+delete rename dance — object stores don't support atomic move), with the Postgres status write as the actual commit point.

**Sprint 5 (add):** Enforce GCM immutability at the application layer once a series' part 1 reaches `rendering`. Add RBAC middleware + `approved_by` write on the `/approve` route. Implement the optimistic-lock retry-then-DLQ policy as a shared utility used by both `chunks.version` and `video_part_jobs.version` writers.

---

## 8. Testing Strategy (addition)

- **Sandbox escape tests (NEW, CI-blocking):** adversarial Manim/Remotion payloads attempting network calls, filesystem reads outside the checkpoint path, or subprocess spawning must be reliably blocked.
- **Chunk-length-bound tests (NEW):** synthetic dense-narration (no natural pauses) input must still produce chunks ≤ 45s.
- **Idempotency tests (NEW):** simulated worker crash + ARQ redelivery must not double-render or corrupt `asset_cache`/MinIO state.
- Existing v2.4 suite (unit, AV-sync integration, visual regression, load/lock-contention) retained unchanged.

---

## 9. Deployment Strategy

Unchanged from v2.4, with one addition — **corrected in v2.6**: the sandbox boundary is a **scheduler/runtime configuration, not a Dockerfile concern**. `Dockerfile.worker.manim` and `Dockerfile.worker.remotion` stay exactly as they were in v2.4; you cannot nest a hardware-virtualized microVM (Firecracker) inside a standard Docker image without `--privileged` mode, which would defeat the isolation boundary entirely. Instead:

- **On Kubernetes:** deploy the Manim/Remotion worker pods with `runtimeClassName: gvisor` (or equivalent), so the container runs under the `runsc` sandboxed runtime instead of standard `runc` — no image changes required.
- **On ECS:** use **AWS Fargate** for the Manim/Remotion worker task definitions specifically (not EC2-backed ECS), since Fargate is natively backed by Firecracker microVMs per task. If EC2-backed ECS is required for cost reasons, install and configure gVisor as the container runtime on the underlying EC2 instances instead.
- Either way, the sandbox is enforced by *where and how the container is scheduled*, not by what's inside the image — this closes the v2.5 gap where the isolation guarantee was described as something baked into the build artifact.