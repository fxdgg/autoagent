# Best Practice: Setup & Deployment

Patterns for **environment setup, dependency installation, build configuration, and deployment** tasks.

---

## Recommended Structures

| Scenario | Structure | Why |
|----------|-----------|-----|
| Simple setup (install deps, configure) | Single `simple` task | One logical unit. |
| Setup + work that depends on it | Top-level `simple` setup task + `nested` work task | Setup runs first as a standalone task; work can retry without reinstalling. |
| Expensive one-time build (Docker, compilation) | Top-level `long_running` build task | Runs first as a standalone task, then subsequent tasks depend on it. |
| Multi-environment deployment | `nested` with per-environment subtasks | Each environment is an independent failure mode. |

---

## Patterns

### Pattern 1: Separate setup from dependent work

Make expensive setup steps **top-level tasks** so they run before dependent work. Dependent tasks reference the setup output (e.g., installed packages) and can retry independently.

```yaml
- id: 1
  name: "Set up development environment and verify"
  type: nested
  completion_criteria: |
    1. All dependencies installed
    2. Project builds successfully
    3. Smoke tests pass
  subtasks:
    - id: 1.1
      name: "Install dependencies"
      type: simple_once
      model: lite
      completion_criteria: |
        1. pip install -e ".[dev]" exits with code 0
        2. pip list shows all required packages
      initial_hint: |
        Install project with dev dependencies: pip install -e ".[dev]"
        If install fails due to system dependencies, check requirements.txt
        for notes on OS-specific packages.

- id: 2
  name: "Build project and run smoke tests"
  type: nested
  completion_criteria: |
    1. Project builds successfully
    2. Smoke tests pass
  initial_hint: |
    Dependencies should already be installed from Task 1.
  subtasks:
    - id: 2.1
      name: "Build project"
      type: simple
      completion_criteria: |
        1. python -m build exits with code 0
      initial_hint: |
        Run: python -m build

    - id: 2.2
      name: "Run smoke tests"
      type: simple
      completion_criteria: |
        1. pytest tests/smoke/ exits with code 0
      initial_hint: |
        Run: pytest tests/smoke/
```

### Pattern 2: Docker or long-running builds

When the build itself takes more than a minute, make it a **top-level** `long_running` task. Subsequent testing runs as a separate task that depends on it.

```yaml
subtasks:
  - id: 1.1
    name: "Build Docker image"
    type: long_running_once
    completion_criteria: |
      1. Docker image built: docker images shows myapp:latest
      2. Build exit code 0
    initial_hint: |
      Run: docker build -t myapp:latest .
      This may take several minutes.

  - id: 1.2
    name: "Run integration tests against container"
    type: simple
    completion_criteria: |
      1. docker run myapp:latest pytest tests/integration/ exits with code 0
```

### Pattern 3: Environment validation before work

When subsequent tasks depend on specific environment state, add a validation step at the beginning. This catches issues early and gives clear error messages.

```yaml
subtasks:
  - id: 1.1
    name: "Validate environment prerequisites"
    type: simple
    model: lite
    completion_criteria: |
      1. Python >= 3.10 available
      2. Node.js >= 18 available
      3. Docker daemon running
      4. Port 8080 not in use
      5. Results logged to env_check.txt
    initial_hint: |
      Check each prerequisite and write results to env_check.txt.
      If any check fails, report clearly which prerequisite is missing.
      Do NOT attempt to install missing prerequisites — just report.

  - id: 1.2
    name: "Set up project"
    type: simple
    completion_criteria: |
      1. Dependencies installed
      2. Config files generated
    initial_hint: |
      Read env_check.txt to confirm prerequisites passed.
      If any failed, report the issue — do not proceed with setup.
```

### Pattern 4: Multi-stage deployment

For deployments with multiple stages (build → deploy → verify), each stage should be a separate subtask. Use `system_prompt_prefix` to prevent the deploy step from "fixing" code.

```yaml
- id: 1
  name: "Deploy to staging"
  type: nested
  completion_criteria: |
    1. Application running on staging
    2. Health check passes: curl https://staging.example.com/health returns 200
  subtasks:
    - id: 1.1
      name: "Build production artifact"
      type: long_running
      completion_criteria: |
        1. dist/ directory contains production build
        2. Build exit code 0
      initial_hint: |
        Run: npm run build:prod
        Production builds can take several minutes.

    - id: 1.2
      name: "Deploy artifact to staging"
      type: simple
      model: lite
      max_attempts: 2
      system_prompt_prefix: |
        You are a deployment operator. Do NOT modify any source code.
      completion_criteria: |
        1. Deployment command succeeded
        2. Deployment log shows no errors
      initial_hint: |
        Run: ./scripts/deploy.sh staging
        If deploy fails, check the deployment log for error details.

    - id: 1.3
      name: "Verify deployment health"
      type: simple
      max_attempts: 1
      model: lite
      system_prompt_prefix: |
        You are a health check runner. Do NOT modify any source code or configuration.
      completion_criteria: |
        1. Health endpoint returns HTTP 200
        2. Version endpoint returns expected version
      initial_hint: |
        Check: curl -f https://staging.example.com/health
        Check: curl -f https://staging.example.com/version
        Wait up to 60 seconds for the service to become healthy.
```

### Pattern 5: Deployment with rollback on failure

When deploying to environments where a failed deployment should be actively rolled back (not just retried), add a rollback step. Use `system_prompt_prefix` to prevent the rollback step from "fixing" code.

```yaml
- id: 1
  name: "Record current deployment version for rollback"
  type: simple
  model: lite
  system_prompt_prefix: |
    You are a deployment operator. Do NOT modify any source code.
  completion_criteria: |
    1. Current version saved to deploy_state.txt (image tag or commit hash)
  initial_hint: |
    Record the current running version so we can roll back if needed.
    Write to deploy_state.txt: image tag, commit hash, timestamp.

- id: 2
  name: "Deploy to production with rollback safety"
  type: nested
  completion_criteria: |
    1. Application running on production
    2. Health check passes: curl https://app.example.com/health returns 200
  subtasks:
    - id: 2.1
      name: "Deploy new version"
      type: simple
      model: lite
      max_attempts: 1
      system_prompt_prefix: |
        You are a deployment operator. Do NOT modify any source code.
      completion_criteria: |
        1. Deployment command succeeded
        2. Deployment log shows no errors
      initial_hint: |
        Run: ./scripts/deploy.sh production
        If deploy fails, do NOT retry — let the parent handle it.

    - id: 2.2
      name: "Verify deployment health, rollback if unhealthy"
      type: simple
      max_attempts: 1
      model: lite
      system_prompt_prefix: |
        You are a health check and rollback operator. Do NOT modify any source code.
      completion_criteria: |
        1. Health endpoint returns HTTP 200, OR
        2. Rollback completed to previous version from deploy_state.txt
      initial_hint: |
        Check: curl -f --retry 5 --retry-delay 10 https://app.example.com/health
        If healthy: report success.
        If NOT healthy after retries:
        - Read deploy_state.txt for the previous version
        - Run: ./scripts/rollback.sh <previous_version>
        - Report that rollback was performed (this counts as task failure
          so the parent can retry the full deploy cycle)
```

---

## Anti-Patterns

| Anti-pattern | Problem | Better |
|--------------|---------|--------|
| Re-installing dependencies on every retry | Wastes time, especially for large dependency trees | Make installation a top-level task before dependent work |
| No environment validation | Failures deep in the pipeline with cryptic errors | Add a validation subtask at the start |
| Deploy step can modify source code | AI "helpfully" patches code instead of reporting deploy failure | Use `system_prompt_prefix` to restrict behavior |
| Using setup tasks for things that can go stale | If a later step changes config, the setup output may be invalid | Only make truly stable steps (deps, base images) standalone top-level tasks |
