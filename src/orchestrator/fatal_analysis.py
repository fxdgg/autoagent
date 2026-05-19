"""Shared Fatal Analysis helpers for linear and AI scheduling modes."""

import json
import time
import logging

from ai_client import AICallError
from orchestrator.orchestrator_common import create_ai_client
from prompts.fatal_analysis import (
    build_fatal_analysis_prompt,
    build_fatal_workflow,
)
from prompts.shared import prepend_system_prompt_prefix
from util.truncation_limits import limits

logger = logging.getLogger(__name__)

FATAL_ANALYSIS_ID = "fatal_analysis"


class FatalAnalysisMixin:
    """Mixin that runs the reserved ``fatal_analysis`` task."""

    @staticmethod
    def _is_reserved_task(task: dict) -> bool:
        return str(task.get("id")) == FATAL_ANALYSIS_ID

    def _normal_tasks(self) -> list:
        return [t for t in self.todos if not self._is_reserved_task(t)]

    @staticmethod
    def _strip_schedule_prefix(task_or_subtask: dict) -> dict:
        item = dict(task_or_subtask)
        if "_display_id" in item:
            item["id"] = item["_display_id"]
        if item.get("subtasks"):
            item["subtasks"] = [
                FatalAnalysisMixin._strip_schedule_prefix(st)
                for st in item.get("subtasks", [])
            ]
        return item

    def _get_fatal_analysis_task(self) -> dict | None:
        return next((t for t in self.todos if self._is_reserved_task(t)), None)

    def _build_fatal_event(
        self,
        *,
        current_task: dict,
        failed_task: dict,
        reason: str,
        response_text: str,
        round_label: str = "",
        schedule_round: int | None = None,
    ) -> dict:
        failed_display_id = str(failed_task.get("_display_id", failed_task["id"]))
        return {
            "current_task": self._strip_schedule_prefix(current_task),
            "failed_task": self._strip_schedule_prefix(failed_task),
            "failed_task_id": failed_display_id,
            "reason": reason or "Fatal prerequisite failure",
            "response_text": response_text or "",
            "round_label": round_label or "",
            "schedule_round": schedule_round,
            "has_subtasks": bool(current_task.get("subtasks")),
        }

    def _available_fatal_retry_ids(self, fatal_event: dict) -> list[str]:
        current_task = fatal_event["current_task"]
        current_id = str(current_task.get("_display_id", current_task["id"]))
        ids: list[str] = []

        for task in self._normal_tasks():
            tid = str(task.get("_display_id", task["id"]))
            if not tid.isdigit() or not current_id.isdigit():
                continue
            if int(tid) < int(current_id):
                ids.append(tid)

        if current_task.get("subtasks"):
            ids.extend(
                str(st.get("_display_id", st["id"]))
                for st in current_task.get("subtasks", [])
            )
        else:
            ids.append(current_id)

        ids.append("stop")
        return ids

    def _normalize_fatal_retry_from(self, retry_from: str, available_ids: list[str]) -> str:
        retry_from = str(retry_from or "").strip()
        if retry_from in available_ids:
            return retry_from
        suffix = "." + retry_from
        matches = [rid for rid in available_ids if rid.endswith(suffix)]
        if len(matches) == 1:
            return matches[0]
        return "stop" if "stop" in available_ids else available_ids[0]

    def _run_fatal_analysis(self, fatal_event: dict, project_description: str = "") -> dict:
        fatal_task = self._get_fatal_analysis_task()
        available_ids = self._available_fatal_retry_ids(fatal_event)
        failed_id = fatal_event["failed_task_id"]

        if not fatal_task:
            return {
                "analysis": "No reserved fatal_analysis task is defined.",
                "retry_from": "stop",
                "suggested_fix": "",
            }

        workflow_text = build_fatal_workflow(
            tasks=self._normal_tasks(),
            current_task=fatal_event["current_task"],
            failed_task=fatal_event["failed_task"],
            failed_task_id=failed_id,
            fatal_reason=fatal_event["reason"],
            state_manager=self.state_manager,
            include_subtasks=bool(fatal_event["current_task"].get("subtasks")),
        )
        prompt = build_fatal_analysis_prompt(
            fatal_task=fatal_task,
            project_description=project_description,
            workflow_text=workflow_text,
            failed_task_output=fatal_event["response_text"],
            failed_task_id=failed_id,
            available_retry_ids=available_ids,
        )
        prompt = prepend_system_prompt_prefix(prompt, fatal_task)

        fatal_model_role = fatal_task.get("model", "evaluation")
        if fatal_model_role in self.model_roles:
            fatal_model = self.model_roles[fatal_model_role]
        else:
            fatal_model = fatal_model_role
        original_model = self.provider.model
        if fatal_model:
            self.provider.set_model(fatal_model)

        context_id = "fatal_analysis"
        if fatal_event.get("schedule_round") is not None:
            context_id = f"schedule_{fatal_event['schedule_round']}_fatal_analysis"
        client = create_ai_client(
            provider=self.provider,
            workspace=self.workspace,
            timeout=self.timeout,
            bash_timeout=self.bash_timeout,
            context_id=context_id,
            use_cli=self.use_cli,
            backoff_max_wait=self.backoff_max_wait,
            session_dir=self.session_dir,
        )

        round_num = fatal_event.get("round_label") or str(fatal_event.get("schedule_round") or 1)
        current_task = fatal_event["current_task"]
        current_id = str(current_task.get("_display_id", current_task["id"]))

        print(f"\n   🧯 [Fatal Analysis] {failed_id}: {fatal_event['reason'][:limits.get('log_promptlike_preview')]}")

        try:
            if self.conv_logger:
                if current_task.get("subtasks"):
                    if hasattr(self.conv_logger, "register_nested_task"):
                        self.conv_logger.register_nested_task(
                            current_id,
                            current_task["name"],
                            [str(st.get("_display_id", st["id"])) for st in current_task.get("subtasks", [])],
                        )
                    else:
                        inner_logger = getattr(self.conv_logger, "_inner", None)
                        if inner_logger and hasattr(inner_logger, "register_nested_task"):
                            inner_logger.register_nested_task(
                                current_id,
                                current_task["name"],
                                [str(st.get("_display_id", st["id"])) for st in current_task.get("subtasks", [])],
                                filename_prefix=getattr(self.conv_logger, "_prefix", None),
                            )
                self.conv_logger.log_nested_prompt(
                    task_id=current_id,
                    task_name=current_task["name"],
                    call_type="fatal_analysis",
                    prompt=prompt,
                    round_num=round_num,
                    failed_subtask_id=failed_id if fatal_event["has_subtasks"] else None,
                )

            decision = client.ask(prompt, expect_json=True)
            if self.conv_logger:
                response_for_log = client.last_full_log or json.dumps(decision, indent=2, ensure_ascii=False)
                self.conv_logger.log_nested_response(
                    task_id=current_id,
                    task_name=current_task["name"],
                    response=response_for_log,
                    call_type="fatal_analysis",
                    round_num=round_num,
                    failed_subtask_id=failed_id if fatal_event["has_subtasks"] else None,
                )
        except AICallError as e:
            logger.warning(f"Fatal analysis failed, stopping AutoAgent: {e}")
            decision = {
                "analysis": f"Fatal analysis AI call failed: {e}",
                "retry_from": "stop",
                "suggested_fix": "",
            }
        finally:
            self.provider.set_model(original_model)

        retry_from = self._normalize_fatal_retry_from(decision.get("retry_from"), available_ids)
        decision["retry_from"] = retry_from
        if retry_from == "stop":
            decision["suggested_fix"] = decision.get("suggested_fix", "")

        record_key = f"fatal_analysis:{failed_id}:{int(time.time())}"
        self.state_manager.state["tasks"][record_key] = {
            "status": "completed",
            "analysis": decision.get("analysis", ""),
            "retry_from": retry_from,
            "suggested_fix": decision.get("suggested_fix", ""),
            "failed_task_id": failed_id,
            "fatal_reason": fatal_event["reason"],
        }
        self.state_manager.save_state()
        return decision
