# Jakal Control

Jakal Control is a local-first control plane for [Jakal Flow](https://github.com/Ahnd6474/Jakal-flow). It is not the coding engine itself. It is the scheduler, supervisor, retry manager, and local operations UI that decides when Jakal Flow runs on your machine and how each run is monitored.

This MVP stays intentionally narrow:

- Local job registration and editing
- One-time and recurring schedules in local time
- Automatic launch at schedule time
- Explicit run state tracking
- Persistent run history and log files
- Safe bounded retry policies
- Manual run, cancel, disable, and retry actions
- SQLite metadata storage and file-based logs

Out of scope for this version:

- Multi-machine orchestration
- Cloud sync or team collaboration
- Complex DAG workflows
- Advanced multi-agent routing

## Stack

- Backend: FastAPI
- Persistence: SQLite + SQLAlchemy
- Supervisor: in-process background coordinator + detached run wrapper
- UI: static local dashboard served by FastAPI
- Tests: pytest

## Project Layout

```text
jakal_control/
  adapters/           Jakal Flow CLI adapter
  services/           control service + scheduler/supervisor coordinator
  web/                local dashboard assets
  job_runner.py       detached wrapper used to persist status/log state
docs/
  architecture.md
examples/
  sample_jobs.json
  prompts/
tests/
```

## Setup

1. Create and activate a virtual environment if you want an isolated local install.
2. Install the app:

```bash
python -m pip install -e .[dev]
```

3. Make sure `Jakal Flow` is available on the machine. By default Jakal Control launches it with:

```bash
python -m jakal_flow
```

If your installation needs a different launcher command, set:

```bash
set JAKAL_CONTROL_ENGINE_COMMAND=python -m jakal_flow
```

Optional runtime settings:

- `JAKAL_CONTROL_HOME`: local data directory. Default is `./.jakal-control`
- `JAKAL_CONTROL_HOST`: default `127.0.0.1`
- `JAKAL_CONTROL_PORT`: default `8787`
- `JAKAL_CONTROL_TIMEZONE`: override detected local timezone

## Run

```bash
python -m jakal_control
```

Open:

```text
http://127.0.0.1:8787
```

The app creates a local data home containing:

- `jakal_control.db`: jobs, schedules, runs, attempts
- `runs/`: per-attempt command and status artifacts
- `workspaces/`: Jakal Flow workspace roots

## How Scheduling Works

- Schedules are stored in SQLite with their next due timestamp.
- The background coordinator wakes up every few seconds and checks for due schedules.
- Supported schedule types:
  - one-time
  - daily at a local time
  - every N hours
  - specific weekdays at a local time
- If a job is already at its concurrency limit, the schedule remains due instead of spawning duplicate local runs.
- One-time schedules disable themselves after firing.

## How Retries and Restarts Work

- Each job has a bounded retry policy:
  - max automatic retries
  - retry delay
  - retry on crash / launch failure
  - retry on non-zero exit
  - retry on stale detection
- Automatic retries are not infinite.
- Retries reuse the same logical run and create a new attempt under it.
- Manual retry creates a fresh run linked to the previous run.
- Stale runs remain visible and blocking until they recover, are cancelled, or are auto-retried by policy.

## How Jakal Flow Is Launched and Monitored

- Jakal Control does not modify Jakal Flow internals.
- It integrates through a CLI adapter that builds `python -m jakal_flow ...` commands.
- Before the first run, the adapter checks whether the job workspace is already initialized:
  - if not initialized, it runs `init-repo`
  - then it runs `run`
- Each attempt is executed through `jakal_control.job_runner`, a detached wrapper that:
  - launches the planned command sequence
  - writes a durable `status.json`
  - captures stdout/stderr into `output.log`
  - emits heartbeats while the process is alive
- On app restart, the coordinator rebuilds state from the persisted database plus the per-attempt status/log files.

## Job Definition Fields

Each job supports:

- name
- repository path
- optional repository URL override
- prompt text or prompt file path
- optional model/provider/effort fields
- optional workspace name
- optional test command
- concurrency limit
- stale timeout
- enabled / disabled state
- retry policy
- zero or more schedules

## Testing

```bash
pytest -q
```

Current test coverage focuses on:

- schedule calculation
- state transition rules
- service-layer persistence behavior
- retry promotion and due schedule claiming

## Example Configuration

See:

- [examples/sample_jobs.json](examples/sample_jobs.json)
- [examples/prompts/maintenance-plan.md](examples/prompts/maintenance-plan.md)

The sample JSON mirrors the API payload shape used by the dashboard.

## Implemented vs Deferred

Implemented now:

- job CRUD
- enable / disable
- manual run
- one-time and recurring scheduling
- persistent local history
- cancel and retry actions
- crash / failure / stale classification
- bounded retry policies
- log capture and tail viewing
- local dashboard

Deferred intentionally:

- remote workers
- multi-user coordination
- cloud services
- DAG orchestration
- richer machine-readable Jakal Flow integration
- plugin/extension architecture

## Architecture Doc

See [docs/architecture.md](docs/architecture.md).
