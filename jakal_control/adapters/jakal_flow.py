from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from ..config import AppConfig
from ..models import Job
from ..utils import ensure_directory, shorten, slugify


@dataclass(frozen=True)
class CommandSpec:
    label: str
    argv: list[str]


@dataclass(frozen=True)
class ExecutionPlan:
    cwd: str
    commands: list[CommandSpec]
    workspace_root: str
    repo_source: str
    prompt_summary: str | None

    def to_json(self) -> dict[str, object]:
        return {
            "cwd": self.cwd,
            "workspace_root": self.workspace_root,
            "repo_source": self.repo_source,
            "prompt_summary": self.prompt_summary,
            "commands": [asdict(command) for command in self.commands],
        }


class JakalFlowAdapter:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def build_execution_plan(self, job: Job) -> ExecutionPlan:
        repo_source = self._repo_source(job)
        workspace_root = ensure_directory(self.config.workspaces_dir / self._workspace_slug(job))
        prompt_file = self._resolve_prompt_file(job)
        prompt_text = (job.prompt_text or "").strip() or None
        commands: list[CommandSpec] = []

        if not self._is_initialized(job, repo_source, workspace_root):
            init_argv = self._base_command("init-repo", job, repo_source, workspace_root)
            if prompt_file:
                init_argv.extend(["--plan-file", str(prompt_file)])
            if prompt_text:
                init_argv.extend(["--plan-prompt", prompt_text])
            commands.append(CommandSpec(label="init-repo", argv=init_argv))

        run_argv = self._base_command("run", job, repo_source, workspace_root)
        if prompt_text:
            run_argv.extend(["--extra-prompt", prompt_text])
        commands.append(CommandSpec(label="run", argv=run_argv))

        prompt_summary = None
        if prompt_file:
            prompt_summary = f"prompt file: {prompt_file}"
        if prompt_text:
            prompt_summary = shorten(prompt_text, limit=180)

        return ExecutionPlan(
            cwd=str(Path(job.repository_path)),
            commands=commands,
            workspace_root=str(workspace_root),
            repo_source=repo_source,
            prompt_summary=prompt_summary,
        )

    def _is_initialized(self, job: Job, repo_source: str, workspace_root: Path) -> bool:
        argv = self._base_command("status", job, repo_source, workspace_root)
        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                cwd=job.repository_path,
                text=True,
                timeout=45,
            )
        except OSError:
            return False
        except subprocess.TimeoutExpired:
            return False
        return result.returncode == 0

    def _base_command(self, verb: str, job: Job, repo_source: str, workspace_root: Path) -> list[str]:
        argv = [*self.config.engine_command_parts, verb]
        argv.extend(["--repo-url", repo_source])
        argv.extend(["--branch", job.working_branch or "main"])
        argv.extend(["--workspace-root", str(workspace_root)])
        argv.extend(["--approval-mode", job.approval_mode or "never"])
        argv.extend(["--sandbox-mode", job.sandbox_mode or "workspace-write"])
        argv.extend(["--max-blocks", str(job.max_blocks or 1)])

        if job.model_provider:
            argv.extend(["--model-provider", job.model_provider])
        if job.local_model_provider:
            argv.extend(["--local-model-provider", job.local_model_provider])
        if job.model_name:
            argv.extend(["--model", job.model_name])
        if job.reasoning_effort:
            argv.extend(["--effort", job.reasoning_effort])
        if job.test_command:
            argv.extend(["--test-cmd", job.test_command])
        return argv

    def _repo_source(self, job: Job) -> str:
        if job.repository_url_override:
            return job.repository_url_override.strip()
        return str(Path(job.repository_path).expanduser().resolve())

    def _workspace_slug(self, job: Job) -> str:
        if job.workspace_name:
            return slugify(job.workspace_name)
        return f"{slugify(job.name)}-{job.id[:8]}"

    def _resolve_prompt_file(self, job: Job) -> Path | None:
        if not job.prompt_file_path:
            return None
        prompt_path = Path(job.prompt_file_path).expanduser()
        if prompt_path.is_absolute():
            return prompt_path
        return (Path(job.repository_path) / prompt_path).resolve()
