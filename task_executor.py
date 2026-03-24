"""
Task Executors - Handle execution logic for different task types.

This module provides:
- SimpleTaskExecutor: Executes simple tasks with AI self-evaluation loop
- NestedTaskExecutor: Executes nested tasks with subtasks and AI decision points
- SubtaskExecutor: Dispatches subtask execution based on type
"""

import os
import time
import subprocess
import logging
from typing import Optional

from codebuddy_client import CodeBuddyClient, AICallError

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Configuration file error (YAML syntax, missing fields, etc.)"""
    pass


class ExecutionError(Exception):
    """Task execution error (command failure, timeout, etc.)"""
    pass


class SubtaskResult:
    """Result of a subtask execution."""
    
    def __init__(self, success: bool, output: str = "", logs: str = "", error_type: str = None):
        self.success = success
        self.output = output
        self.logs = logs
        self.error_type = error_type


class SimpleTaskExecutor:
    """
    Executes simple tasks using AI self-evaluation loop.
    
    The AI attempts the task, evaluates completion, and iterates
    until the criteria are met or max attempts are reached.
    """

    def execute(self, task: dict, client: CodeBuddyClient, state_manager, is_subtask: bool = False, conv_logger=None, parent_task_id: str = None) -> bool:
        """
        Execute a simple task.
        
        Args:
            task: Task configuration dict
            client: CodeBuddyClient instance
            state_manager: State manager for persistence
            is_subtask: Whether this is a subtask within a nested task
            conv_logger: Optional ConversationLogger instance
            parent_task_id: Parent task ID if this is a subtask (for log organization)
            
        Returns:
            bool: True if task completed successfully
        """
        task_id = str(task['id'])
        max_attempts = task.get('max_attempts', 20)
        
        current_state = state_manager.get_task_state(task_id)
        attempts = current_state.get('attempts', 0)
        
        logger.info(f"Executing simple task {task_id}: {task['name']}")
        
        while attempts < max_attempts:
            attempts += 1
            state_manager.mark_task_status(
                task_id, "in_progress",
                attempts=attempts,
                last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
            )
            
            print(f"\n   Attempt #{attempts}")
            
            # Build prompt
            prompt = self._build_prompt(task, attempts, current_state)
            
            try:
                # First attempt of a main task: don't continue session
                # Subtasks and subsequent attempts: continue session
                continue_session = is_subtask or (attempts > 1)
                
                result = client.ask(prompt, continue_session=continue_session)
                
                # Log conversation (use full log with tool calls if available)
                if conv_logger:
                    conv_logger.log_conversation(
                        task_id=task_id,
                        task_name=task['name'],
                        prompt=prompt,
                        response=client.last_full_log or result,
                        attempt=attempts,
                        parent_task_id=parent_task_id,
                    )
                
                # Check if AI reports completion
                if self._check_completion(result):
                    print(f"   ✅ Task {task_id} completed!")
                    state_manager.mark_task_status(
                        task_id, "completed",
                        attempts=attempts,
                        last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
                        ai_reasoning=result[:500],
                    )
                    # Record history
                    state_manager.add_task_history(task_id, {
                        "attempt": attempts,
                        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "result": "completed",
                        "ai_response": result[:500],
                    })
                    return True
                else:
                    print(f"   ⏳ Not completed yet, AI will try to improve...")
                    state_manager.add_task_history(task_id, {
                        "attempt": attempts,
                        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "result": "not_completed",
                        "ai_response": result[:500],
                    })
                    
            except AICallError as e:
                logger.error(f"AI call failed for task {task_id}: {e}")
                print(f"   ❌ AI call error: {e}")
                # Log error conversation
                if conv_logger:
                    conv_logger.log_conversation(
                        task_id=task_id,
                        task_name=task['name'],
                        prompt=prompt,
                        response=f"❌ AI Call Error: {e}",
                        attempt=attempts,
                        parent_task_id=parent_task_id,
                        metadata={"type": "error"},
                    )
                state_manager.add_task_history(task_id, {
                    "attempt": attempts,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "result": "error",
                    "error": str(e),
                })
        
        # Max attempts reached
        print(f"   ❌ Task {task_id} failed after {max_attempts} attempts")
        state_manager.mark_task_status(
            task_id, "failed",
            attempts=attempts,
            last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        return False

    def _build_prompt(self, task: dict, attempt: int, state: dict) -> str:
        """Build the prompt for AI."""
        parts = [
            f"Task: {task['name']}",
            f"Completion Criteria: {task['completion_criteria']}",
        ]
        
        if task.get('initial_hint') and attempt == 1:
            parts.append(f"Initial Hint: {task['initial_hint']}")
        
        if attempt > 1:
            history = state.get('history', [])
            if history:
                recent = history[-3:]  # Last 3 attempts
                history_text = "\n".join(
                    f"  - Attempt {h.get('attempt', '?')}: {h.get('result', 'unknown')} - {h.get('ai_response', '')[:200]}"
                    for h in recent
                )
                parts.append(f"Previous Attempts:\n{history_text}")
            parts.append(
                "Please analyze what went wrong and try a different approach."
            )
        
        parts.append(
            "\nPlease try to complete this task. "
            "When done, indicate the result:\n"
            "- ✅ completed: if the completion criteria are met\n"
            "- ❌ not completed: if not met, explain what you plan to improve"
        )
        
        return "\n\n".join(parts)

    def _check_completion(self, response: str) -> bool:
        """
        Check if the AI reports the task as completed.
        
        Args:
            response: AI response text
            
        Returns:
            bool: True if AI indicates completion
        """
        response_lower = response.lower()
        
        # Positive indicators
        completion_markers = [
            "✅ completed",
            "✅ complete",
            "✅ 完成",
            "✅completed",
            "✅complete",
            "✅完成",
        ]
        
        # Negative indicators
        failure_markers = [
            "❌ not_completed",
            "❌ not completed",
            "❌ not_complete",
            "❌ not complete",
            "❌ 未完成",
            "❌not_completed",
            "❌not completed",
            "❌not_complete",
            "❌not complete",
            "❌未完成",
        ]
        
        # Check negative first (more specific)
        for marker in failure_markers:
            if marker.lower() in response_lower:
                return False
        
        # Then check positive
        for marker in completion_markers:
            if marker.lower() in response_lower:
                return True
        
        # Default: not completed
        return False


class NestedTaskExecutor:
    """
    Executes nested tasks with subtasks and AI decision points.
    
    Two AI decision points:
    1. When a subtask fails: AI analyzes and decides retry_from
    2. When all subtasks complete: AI evaluates if main task is done
    """

    def __init__(self):
        self.subtask_executor = SubtaskExecutor()

    def execute(self, task: dict, client: CodeBuddyClient, state_manager, conv_logger=None) -> bool:
        """
        Execute a nested task.
        
        Args:
            task: Task configuration with subtasks
            client: CodeBuddyClient instance  
            state_manager: State manager for persistence
            conv_logger: Optional ConversationLogger instance
            
        Returns:
            bool: True if main task completed
        """
        task_id = str(task['id'])
        max_attempts = task.get('max_attempts', 20)
        subtasks = task.get('subtasks', [])
        
        if not subtasks:
            raise ConfigError(f"Nested task {task_id} has no subtasks")
        
        # Register nested task with conversation logger
        if conv_logger:
            subtask_ids = [str(st['id']) for st in subtasks]
            conv_logger.register_nested_task(task_id, task['name'], subtask_ids)
        
        logger.info(f"Executing nested task {task_id}: {task['name']}")
        
        current_state = state_manager.get_task_state(task_id)
        attempts = current_state.get('attempts', 0)
        
        while attempts < max_attempts:
            attempts += 1
            state_manager.mark_task_status(
                task_id, "in_progress",
                attempts=attempts,
                current_round=attempts,
                max_attempts=max_attempts,
            )
            
            print(f"\n   📋 Round #{attempts} of nested task {task_id}")
            
            # Execute subtasks in order
            all_completed = True
            for subtask in subtasks:
                subtask_id = str(subtask['id'])
                subtask_state = state_manager.get_task_state(subtask_id)
                
                # Skip already completed subtasks
                if subtask_state.get('status') == 'completed':
                    print(f"\n   📌 Subtask {subtask_id}: {subtask['name']} (already completed, skipping)")
                    continue
                
                print(f"\n   📌 Executing subtask {subtask_id}: {subtask['name']}")
                print(f"      Type: {subtask['type']}")
                
                result = self.subtask_executor.execute(
                    subtask, client, state_manager,
                    conv_logger=conv_logger, parent_task_id=task_id,
                )
                
                if not result.success:
                    all_completed = False
                    print(f"\n   ❌ Subtask {subtask_id} failed!")
                    
                    # AI Decision Point 1: Analyze failure
                    ai_decision = self._ai_analyze_failure(
                        client, task, subtask, subtasks, result, state_manager,
                        conv_logger=conv_logger, round_num=attempts,
                    )
                    
                    # Reset subtasks based on AI decision
                    retry_from = ai_decision.get('retry_from', subtask_id)
                    self._reset_subtasks_from(retry_from, subtasks, state_manager)
                    
                    # Record AI decision
                    state_manager.add_ai_decision(task_id, {
                        "attempt": attempts,
                        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "failed_at": subtask_id,
                        "retry_from": retry_from,
                        "reasoning": ai_decision.get('reasoning', ''),
                        "suggested_fix": ai_decision.get('suggested_fix', ''),
                        "confidence": ai_decision.get('confidence', 'unknown'),
                    })
                    
                    break  # Break subtask loop, start new round
            
            if not all_completed:
                print(f"\n   ⏳ Subtask failed, starting new round...")
                continue
            
            # All subtasks completed - AI Decision Point 2: Evaluate main task
            print(f"\n   📊 All subtasks completed, evaluating main task...")
            ai_evaluation = self._ai_evaluate_main_task(
                client, task, subtasks, state_manager,
                conv_logger=conv_logger, round_num=attempts,
            )
            
            if ai_evaluation.get('main_task_completed', False):
                print(f"\n   ✅ Main task {task_id} completed!")
                state_manager.mark_task_status(
                    task_id, "completed",
                    attempts=attempts,
                    last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
                )
                
                # Record evaluation
                state_manager.add_main_task_evaluation(task_id, {
                    "round": attempts,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "completed": True,
                    "analysis": ai_evaluation.get('analysis', ''),
                })
                return True
            else:
                print(f"\n   ⏳ Main task not yet completed.")
                print(f"      Analysis: {ai_evaluation.get('analysis', 'N/A')}")
                print(f"      Next strategy: {ai_evaluation.get('next_strategy', 'N/A')}")
                
                # Reset subtasks based on AI decision
                retry_from = ai_evaluation.get('retry_from', str(subtasks[0]['id']))
                self._reset_subtasks_from(retry_from, subtasks, state_manager)
                
                # Record evaluation
                state_manager.add_main_task_evaluation(task_id, {
                    "round": attempts,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "completed": False,
                    "analysis": ai_evaluation.get('analysis', ''),
                    "next_strategy": ai_evaluation.get('next_strategy', ''),
                    "suggested_improvements": ai_evaluation.get('suggested_improvements', []),
                    "retry_from": retry_from,
                })
        
        # Max attempts reached
        print(f"\n   ❌ Nested task {task_id} failed after {max_attempts} rounds")
        state_manager.mark_task_status(
            task_id, "failed",
            attempts=attempts,
            last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        return False

    def _ai_analyze_failure(
        self, client, task, failed_subtask, all_subtasks, result, state_manager,
        conv_logger=None, round_num=1,
    ) -> dict:
        """
        AI Decision Point 1: Analyze subtask failure.
        
        Returns:
            dict with keys: analysis, retry_from, reasoning, suggested_fix, confidence
        """
        task_id = str(task['id'])
        failed_id = str(failed_subtask['id'])
        
        # Build context for AI
        task_history = []
        for st in all_subtasks:
            st_id = str(st['id'])
            st_state = state_manager.get_task_state(st_id)
            task_history.append({
                "subtask_id": st_id,
                "name": st['name'],
                "type": st['type'],
                "status": st_state.get('status', 'pending'),
                "attempts": st_state.get('attempts', 0),
                "ai_reasoning": st_state.get('ai_reasoning', ''),
            })
        
        prompt = f"""A subtask has failed. Please analyze the failure and decide the retry strategy.

Main Task: {task['name']}
Main Task Completion Criteria: {task['completion_criteria']}

Failed Subtask:
  ID: {failed_id}
  Name: {failed_subtask['name']}
  Type: {failed_subtask['type']}
  Error: {result.logs or result.output}
  Error Type: {result.error_type or 'unknown'}

All Subtasks Status:
{self._format_task_history(task_history)}

Please respond in the following JSON format:
```json
{{
    "analysis": "Description of why the failure occurred",
    "retry_from": "{failed_id}",
    "reasoning": "Why retry from this subtask",
    "suggested_fix": "Specific fix to try",
    "confidence": "high/medium/low"
}}
```

Important: retry_from should be the ID of the subtask to restart from. 
It can be the failed subtask itself, or an earlier subtask if the root cause is there.
Available subtask IDs: {[str(s['id']) for s in all_subtasks]}
"""
        
        print(f"\n   🤖 [AI Decision Point 1: Failure Analysis]")
        
        try:
            decision = client.ask(prompt, expect_json=True, continue_session=True)
            print(f"      AI Analysis: {decision.get('analysis', 'N/A')[:200]}")
            print(f"      AI Decision: retry_from = {decision.get('retry_from', failed_id)}")
            print(f"      Suggested Fix: {decision.get('suggested_fix', 'N/A')[:200]}")
            # Log AI decision (use full log with tool calls if available)
            if conv_logger:
                import json
                response_for_log = client.last_full_log or json.dumps(decision, indent=2, ensure_ascii=False)
                conv_logger.log_nested_task_ai_call(
                    task_id=str(task['id']),
                    task_name=task['name'],
                    call_type="failure_analysis",
                    prompt=prompt,
                    response=response_for_log,
                    round_num=round_num,
                )
            return decision
        except AICallError as e:
            logger.warning(f"Failed to get AI decision, using default: {e}")
            print(f"      ⚠️ AI analysis failed, retrying from {failed_id}")
            return {
                "analysis": f"AI analysis failed: {e}",
                "retry_from": failed_id,
                "reasoning": "Default: retry from failed subtask",
                "suggested_fix": "Retry the same subtask",
                "confidence": "low",
            }

    def _ai_evaluate_main_task(
        self, client, task, subtasks, state_manager,
        conv_logger=None, round_num=1,
    ) -> dict:
        """
        AI Decision Point 2: Evaluate main task completion.
        
        Returns:
            dict with keys: main_task_completed, analysis, retry_from, 
                           next_strategy, suggested_improvements, confidence
        """
        task_id = str(task['id'])
        
        # Collect all subtask results
        execution_results = []
        for st in subtasks:
            st_id = str(st['id'])
            st_state = state_manager.get_task_state(st_id)
            execution_results.append({
                "subtask_id": st_id,
                "name": st['name'],
                "type": st['type'],
                "status": st_state.get('status', 'unknown'),
                "attempts": st_state.get('attempts', 0),
                "ai_reasoning": st_state.get('ai_reasoning', ''),
                "history": st_state.get('history', [])[-3:],  # Last 3 entries
            })
        
        # Check for log files of long_running subtasks
        log_contents = {}
        for st in subtasks:
            if st.get('type') == 'long_running':
                st_id = str(st['id'])
                log_file = f"logs/{st_id}.log"
                if os.path.exists(log_file):
                    try:
                        with open(log_file, 'r') as f:
                            content = f.read()
                            # Get last 2000 chars
                            log_contents[st_id] = content[-2000:] if len(content) > 2000 else content
                    except Exception:
                        pass
        
        log_section = ""
        if log_contents:
            log_section = "\nRelevant Log Files:\n"
            for st_id, content in log_contents.items():
                log_section += f"\n--- logs/{st_id}.log (last part) ---\n{content}\n"
        
        prompt = f"""All subtasks are completed. Please evaluate whether the main task is finished.

Main Task: {task['name']}
Completion Criteria: {task['completion_criteria']}

Execution Results:
{self._format_execution_results(execution_results)}
{log_section}

Please respond in the following JSON format:
```json
{{
    "main_task_completed": true/false,
    "analysis": "Detailed analysis of results vs criteria",
    "retry_from": "{subtasks[0]['id']}",
    "next_strategy": "Strategy for next round if not completed",
    "suggested_improvements": ["improvement 1", "improvement 2"],
    "confidence": "high/medium/low"
}}
```

Important: 
- Set main_task_completed to true ONLY if ALL completion criteria are met.
- If not completed, retry_from should be the subtask ID to restart from.
- Available subtask IDs: {[str(s['id']) for s in subtasks]}
"""
        
        print(f"\n   🤖 [AI Decision Point 2: Main Task Evaluation]")
        
        try:
            evaluation = client.ask(prompt, expect_json=True, continue_session=True)
            completed = evaluation.get('main_task_completed', False)
            print(f"      AI Evaluation: {'✅ COMPLETED' if completed else '❌ NOT COMPLETED'}")
            print(f"      Analysis: {evaluation.get('analysis', 'N/A')[:200]}")
            # Log AI evaluation (use full log with tool calls if available)
            if conv_logger:
                import json
                response_for_log = client.last_full_log or json.dumps(evaluation, indent=2, ensure_ascii=False)
                conv_logger.log_nested_task_ai_call(
                    task_id=str(task['id']),
                    task_name=task['name'],
                    call_type="main_task_evaluation",
                    prompt=prompt,
                    response=response_for_log,
                    round_num=round_num,
                )
            return evaluation
        except AICallError as e:
            logger.warning(f"Failed to get AI evaluation, defaulting to not completed: {e}")
            print(f"      ⚠️ AI evaluation failed, marking as not completed")
            return {
                "main_task_completed": False,
                "analysis": f"AI evaluation failed: {e}",
                "retry_from": str(subtasks[0]['id']),
                "next_strategy": "Retry all subtasks",
                "suggested_improvements": [],
                "confidence": "low",
            }

    def _reset_subtasks_from(self, retry_from: str, subtasks: list, state_manager):
        """
        Reset subtask states starting from retry_from.
        
        All subtasks from retry_from onwards are reset to 'pending'.
        """
        should_reset = False
        retry_from = str(retry_from)
        
        for subtask in subtasks:
            st_id = str(subtask['id'])
            if st_id == retry_from:
                should_reset = True
            if should_reset:
                state_manager.mark_task_status(st_id, "pending", attempts=0)
                logger.info(f"Reset subtask {st_id} to pending")

    def _format_task_history(self, history: list) -> str:
        """Format task history for prompt."""
        lines = []
        for item in history:
            lines.append(
                f"  - {item['subtask_id']} ({item['name']}): "
                f"status={item['status']}, attempts={item['attempts']}"
            )
            if item.get('ai_reasoning'):
                lines.append(f"    AI reasoning: {item['ai_reasoning'][:200]}")
        return "\n".join(lines)

    def _format_execution_results(self, results: list) -> str:
        """Format execution results for prompt."""
        lines = []
        for r in results:
            lines.append(
                f"  - {r['subtask_id']} ({r['name']}): "
                f"status={r['status']}, attempts={r['attempts']}"
            )
            if r.get('ai_reasoning'):
                lines.append(f"    Result: {r['ai_reasoning'][:300]}")
        return "\n".join(lines)


class SubtaskExecutor:
    """
    Dispatches subtask execution based on type (simple or long_running).
    """

    def __init__(self):
        self.simple_executor = SimpleTaskExecutor()

    def execute(self, subtask: dict, client: CodeBuddyClient, state_manager, conv_logger=None, parent_task_id: str = None) -> SubtaskResult:
        """
        Execute a single subtask.
        
        Args:
            subtask: Subtask configuration
            client: CodeBuddyClient instance
            state_manager: State manager
            conv_logger: Optional ConversationLogger instance
            parent_task_id: Parent task ID for log organization
            
        Returns:
            SubtaskResult: Result of execution
        """
        subtask_type = subtask.get('type', 'simple')
        
        if subtask_type == 'simple':
            return self._execute_simple_subtask(
                subtask, client, state_manager,
                conv_logger=conv_logger, parent_task_id=parent_task_id,
            )
        elif subtask_type == 'long_running':
            return self._execute_long_running_subtask(
                subtask, client, state_manager,
                conv_logger=conv_logger, parent_task_id=parent_task_id,
            )
        else:
            raise ConfigError(f"Unknown subtask type: {subtask_type}")

    def _execute_simple_subtask(
        self, subtask: dict, client: CodeBuddyClient, state_manager,
        conv_logger=None, parent_task_id: str = None,
    ) -> SubtaskResult:
        """Execute a simple subtask via AI."""
        success = self.simple_executor.execute(
            subtask, client, state_manager, is_subtask=True,
            conv_logger=conv_logger, parent_task_id=parent_task_id,
        )
        
        subtask_id = str(subtask['id'])
        state = state_manager.get_task_state(subtask_id)
        
        return SubtaskResult(
            success=success,
            output=state.get('ai_reasoning', ''),
            logs="",
            error_type=None if success else "ai_failed",
        )

    def _execute_long_running_subtask(
        self, subtask: dict, client: CodeBuddyClient, state_manager,
        conv_logger=None, parent_task_id: str = None,
    ) -> SubtaskResult:
        """
        Execute a long-running subtask using nohup.
        
        1. Start the command in background with nohup
        2. Monitor the process
        3. When done, ask AI to evaluate the result
        """
        subtask_id = str(subtask['id'])
        command = subtask.get('command')
        
        if not command:
            raise ConfigError(f"Long-running subtask {subtask_id} missing 'command' field")
        
        # Ensure directories exist
        os.makedirs("logs", exist_ok=True)
        os.makedirs("monitors", exist_ok=True)
        
        log_file = f"logs/{subtask_id}.log"
        pid_file = f"monitors/{subtask_id}.pid"
        
        print(f"      Starting long-running task: {command}")
        print(f"      Log file: {log_file}")
        
        # Start the background task
        full_command = f"nohup {command} > {log_file} 2>&1 & echo $! > {pid_file}"
        
        try:
            subprocess.run(full_command, shell=True, check=True)
        except subprocess.CalledProcessError as e:
            state_manager.mark_task_status(
                subtask_id, "failed",
                error_type="launch_failed",
                last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
            )
            return SubtaskResult(
                success=False,
                output=f"Failed to launch: {e}",
                error_type="launch_failed",
            )
        
        state_manager.mark_task_status(
            subtask_id, "in_progress",
            log_file=log_file,
            pid_file=pid_file,
            started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        
        print(f"      ✅ Task launched, monitoring...")
        
        # Monitor the process
        result = self._monitor_and_wait(subtask_id, log_file, pid_file)
        
        # Ask AI to analyze the result
        return self._ai_analyze_long_running_result(
            subtask, client, state_manager, result, log_file,
            conv_logger=conv_logger, parent_task_id=parent_task_id,
        )

    def _monitor_and_wait(self, subtask_id: str, log_file: str, pid_file: str) -> str:
        """
        Monitor a long-running process until completion.
        
        Args:
            subtask_id: ID of the subtask
            log_file: Path to the log file
            pid_file: Path to the PID file
            
        Returns:
            str: "finished", "error", or "timeout"
        """
        check_interval = 30  # seconds
        max_wait = 24 * 3600  # 24 hours max
        elapsed = 0
        
        while elapsed < max_wait:
            # Check if the process is still running
            try:
                if os.path.exists(pid_file):
                    with open(pid_file, 'r') as f:
                        pid = f.read().strip()
                    if pid:
                        # Check if process exists
                        result = subprocess.run(
                            f"kill -0 {pid} 2>/dev/null",
                            shell=True,
                            capture_output=True,
                        )
                        if result.returncode != 0:
                            # Process has ended
                            logger.info(f"Process {pid} for {subtask_id} has ended")
                            
                            # Check for errors in log
                            if os.path.exists(log_file):
                                with open(log_file, 'r') as f:
                                    log_content = f.read()
                                error_patterns = [
                                    "ERROR", "Exception", "Traceback",
                                    "CUDA out of memory", "OOM", "Killed",
                                ]
                                for pattern in error_patterns:
                                    if pattern in log_content:
                                        return "error"
                            return "finished"
            except Exception as e:
                logger.warning(f"Monitor check failed: {e}")
            
            time.sleep(check_interval)
            elapsed += check_interval
            
            if elapsed % 300 == 0:  # Print status every 5 minutes
                print(f"      ⏳ Still running... ({elapsed // 60} minutes elapsed)")
        
        return "timeout"

    def _ai_analyze_long_running_result(
        self, subtask, client, state_manager, status, log_file,
        conv_logger=None, parent_task_id: str = None,
    ) -> SubtaskResult:
        """
        Ask AI to analyze the result of a long-running task.
        """
        subtask_id = str(subtask['id'])
        
        # Read log content
        log_content = ""
        if os.path.exists(log_file):
            try:
                with open(log_file, 'r') as f:
                    content = f.read()
                    log_content = content[-2000:] if len(content) > 2000 else content
            except Exception:
                log_content = "(failed to read log file)"
        
        prompt = f"""A long-running task has finished. Please analyze the result.

Subtask: {subtask['name']}
Completion Criteria: {subtask['completion_criteria']}
Status: {status}

Log (last part):
{log_content}

Please evaluate:
1. Did the task complete successfully?
2. Do the results meet the completion criteria?

Respond with:
- ✅ COMPLETED: if the criteria are met
- ❌ NOT_COMPLETED: if not met, explain why
"""
        
        try:
            result = client.ask(prompt, continue_session=True)
            
            # Log conversation (use full log with tool calls if available)
            if conv_logger:
                conv_logger.log_conversation(
                    task_id=str(subtask['id']),
                    task_name=subtask['name'],
                    prompt=prompt,
                    response=client.last_full_log or result,
                    attempt=1,
                    parent_task_id=parent_task_id,
                    metadata={"type": "long_running_analysis"},
                )
            
            # Check completion
            completion_markers = ["✅ completed", "✅ complete", "✅ 完成", "criteria met", "criteria are met"]
            is_completed = any(m.lower() in result.lower() for m in completion_markers)
            
            # Also check for negative
            failure_markers = ["❌ not_completed", "❌ not completed", "not yet completed", "criteria not met"]
            is_failed = any(m.lower() in result.lower() for m in failure_markers)
            
            if is_failed:
                is_completed = False
            
            if is_completed:
                state_manager.mark_task_status(
                    subtask_id, "completed",
                    last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
                    ai_reasoning=result[:500],
                )
                print(f"      ✅ Long-running task {subtask_id} completed!")
            else:
                state_manager.mark_task_status(
                    subtask_id, "failed",
                    error_type="validation_failed",
                    last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
                    ai_reasoning=result[:500],
                )
                print(f"      ❌ Long-running task {subtask_id} did not meet criteria")
            
            return SubtaskResult(
                success=is_completed,
                output=result[:500],
                logs=log_content,
                error_type=None if is_completed else "validation_failed",
            )
            
        except AICallError as e:
            logger.error(f"Failed to analyze long-running result: {e}")
            error_status = status != "finished"
            state_manager.mark_task_status(
                subtask_id, "failed",
                error_type=status,
                last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
            )
            return SubtaskResult(
                success=False,
                output=f"AI analysis failed: {e}",
                logs=log_content,
                error_type=status,
            )
