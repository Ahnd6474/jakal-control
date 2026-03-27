# Architecture Overview

## Positioning

- `Jakal Flow` is the execution engine.
- `Jakal Control` is the standalone local supervisor, scheduler, and run manager.

The MVP is designed to be operationally reliable on a single machine first, while leaving room for future expansion to remote workers and richer orchestration later.

## Core Components

### 1. Control Service

`jakal_control/services/control.py`

Responsible for:

- job create/update/delete
- enable/disable
- manual queueing
- cancel and manual retry actions
- dashboard aggregation
- log tail retrieval

This layer owns the application-facing rules around concurrency blocking, payload validation, and how domain entities are serialized for the UI.

### 2. Scheduler / Supervisor Coordinator

`jakal_control/services/coordinator.py`

Runs in the background inside the local app process. On each tick it:

1. synchronizes active runs from persisted runner status files,
2. claims due schedules,
3. launches queued or retry-waiting runs when capacity is available.

The coordinator is deliberately simple and explicit. It does not depend on an external broker or cloud scheduler.

### 3. Jakal Flow Adapter

`jakal_control/adapters/jakal_flow.py`

Builds the concrete `Jakal Flow` CLI plan.

Responsibilities:

- resolve repository source
- resolve workspace root
- check whether the workspace is already initialized
- emit `init-repo` when needed
- emit the actual `run` command
- pass through optional model/provider/test configuration

This keeps the integration boundary clean and makes it easier to swap in a richer adapter later if Jakal Flow gains a machine-readable API.

### 4. Detached Job Runner

`jakal_control/job_runner.py`

Each attempt is launched through a wrapper process rather than having the web app directly own stdout/stderr pipes.

The runner:

- executes the planned command list
- writes `status.json`
- writes `output.log`
- updates heartbeats while alive
- records final exit result

Why this exists:

- the web app can restart and still recover run state from disk
- stdout/stderr capture remains practical
- supervision stays local and file-backed

### 5. Web App

`jakal_control/main.py` + `jakal_control/web/*`

FastAPI serves:

- the JSON API
- the local dashboard HTML/CSS/JS

The UI polls for current state rather than depending on a websocket layer. That keeps the MVP simpler and easier to operate locally.

## Persistence Model

### SQLite Tables

- `jobs`
- `schedules`
- `runs`
- `run_attempts`

### Separation of Concerns

- `Job` stores durable job configuration.
- `Schedule` stores recurrence rules and next due time.
- `Run` stores a logical execution request and final outcome.
- `RunAttempt` stores the process-level details for each retry attempt.

This separation avoids mixing immutable job configuration with transient process state.

## State Model

Primary run states:

- `queued`
- `starting`
- `running`
- `succeeded`
- `failed`
- `cancelled`
- `retry_waiting`
- `stale`

Important behavior:

- `stale` is treated as a supervision state for suspected hangs.
- automatic retry moves the logical run to `retry_waiting`
- each retry creates a new `run_attempts` row

State transitions are intentionally explicit and test-covered in `jakal_control/state_machine.py`.

## Scheduling Model

Supported schedule types:

- once
- daily
- every N hours
- weekdays at a local time

Each schedule stores:

- schedule shape
- timezone
- next due timestamp
- enabled state

The coordinator recomputes `next_run_at` after each successful claim. One-time schedules disable themselves after they fire.

## Retry Model

Retry policy is configured per job:

- max automatic retries
- retry delay
- retry on crash
- retry on non-zero exit
- retry on stale

The retry decision is made centrally in the coordinator after each attempt outcome is classified.

## Failure Classification

Current MVP categories:

- `success`
- `task_failure`
- `crash`
- `stale`
- `cancelled`

Since the MVP does not rely on internal Jakal Flow status hooks, failure classification is intentionally conservative and based on process outcome plus persisted runner state.

## Recovery After Restart

Recovery is based on two durable sources:

1. SQLite metadata
2. per-attempt files under `runs/<run-id>/attempt-<n>/`

On restart the coordinator can:

- inspect `status.json`
- check whether the wrapper PID still exists
- recover heartbeat timestamps
- continue showing log history

This provides practical local resiliency without a message queue or distributed state store.

## Why This Fits the MVP

This architecture prioritizes:

- explicit state transitions
- local durability
- bounded retries
- operational clarity
- clean future seams for richer adapters or remote execution later

It intentionally avoids premature distributed design while still keeping the domain model extensible enough for future orchestration work.
