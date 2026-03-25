"""
Task Executors - Handle execution logic for different task types.

This module provides:
- SimpleTaskExecutor: Executes simple tasks with AI self-evaluation loop
- NestedTaskExecutor: Executes nested tasks with subtasks and AI decision points
- SubtaskExecutor: Dispatches subtask execution based on type
"""

import os
import json
import time
import subprocess
import logging
from typing import Optional

from codebuddy_client import AIClient, CodeBuddyClient, AICallError

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
                
                # Write prompt to log BEFORE calling AI (crash safety)
                if conv_logger:
                    conv_logger.log_prompt(
                        task_id=task_id,
                        task_name=task['name'],
                        prompt=prompt,
                        attempt=attempts,
                        parent_task_id=parent_task_id,
                    )
                
                result = client.ask(prompt, continue_session=continue_session)
                
                # Append response to log AFTER AI returns
                if conv_logger:
                    conv_logger.log_response(
                        task_id=task_id,
                        response=client.last_full_log or result,
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
                # Append error as response (prompt was already logged above)
                if conv_logger:
                    conv_logger.log_response(
                        task_id=task_id,
                        response=f"AI Call Error: {e}",
                        parent_task_id=parent_task_id,
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
            "When you are done, you MUST include a status line in your response.\n\n"
            "**CRITICAL INSTRUCTION**: Your response MUST end with EXACTLY one of these "
            "two status lines (copy-paste verbatim, on its own line):\n\n"
            "  ✅ completed\n\n"
            "  ❌ not completed: <reason>\n\n"
            "This status line is MANDATORY. Do NOT omit it. Do NOT rephrase it. "
            "Do NOT embed it inside a sentence or heading. "
            "It must appear as the LAST line of your response, standalone, "
            "exactly as shown above (with the emoji prefix)."
        )
        
        return "\n\n".join(parts)

    def _check_completion(self, response: str) -> bool:
        """
        Check if the AI reports the task as completed.
        
        Uses a multi-layer strategy:
        1. Check for strict markers (✅ COMPLETED / ❌ NOT_COMPLETED)
        2. Check for common variations the AI might use despite instructions
        3. Scan for contextual completion phrases as a fallback
        
        Args:
            response: AI response text
            
        Returns:
            bool: True if AI indicates completion
        """
        response_lower = response.lower()
        
        # --- Layer 1: Strict negative markers (check first, most specific) ---
        strict_failure_markers = [
            "❌ not_completed",
            "❌ not completed",
            "❌ not_complete",
            "❌ not complete",
            "❌not_completed",
            "❌not completed",
            "❌not_complete",
            "❌not complete",
            "❌ 未完成",
            "❌未完成",
        ]
        for marker in strict_failure_markers:
            if marker.lower() in response_lower:
                return False
        
        # --- Layer 2: Strict positive markers ---
        strict_completion_markers = [
            "✅ completed",
            "✅ complete",
            "✅completed",
            "✅complete",
            "✅ 完成",
            "✅完成",
        ]
        for marker in strict_completion_markers:
            if marker.lower() in response_lower:
                return True
        
        # --- Layer 3: Fuzzy positive patterns (AI often rephrases) ---
        # These catch cases like "✅ Task Completed Successfully",
        # "✅ All criteria met", "✅ Done", etc.
        import re
        fuzzy_positive_patterns = [
            r'✅.*(?:completed?|done|success|criteria\s+(?:are\s+)?met|finish)',
            r'(?:task|all)\s+(?:has been\s+)?completed?\s+successfully',
            r'all\s+completion\s+criteria\s+(?:have been\s+|are\s+)?met',
            r'(?:completed?|done|success).*✅',
        ]
        # Only check the last 1000 chars to focus on the conclusion
        tail = response_lower[-1000:] if len(response_lower) > 1000 else response_lower
        for pattern in fuzzy_positive_patterns:
            if re.search(pattern, tail):
                # Double-check: make sure there's no "not completed" nearby
                not_patterns = [
                    r'not\s+(?:yet\s+)?completed?',
                    r'criteria\s+(?:are\s+)?not\s+met',
                    r'fail',
                ]
                has_negation = any(re.search(np, tail) for np in not_patterns)
                if not has_negation:
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

    def __init__(self, session_dir: str = None):
        self.subtask_executor = SubtaskExecutor(session_dir=session_dir)
        self.session_dir = session_dir

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
            # Write prompt to log BEFORE calling AI (crash safety)
            if conv_logger:
                conv_logger.log_nested_prompt(
                    task_id=str(task['id']),
                    task_name=task['name'],
                    call_type="failure_analysis",
                    prompt=prompt,
                    round_num=round_num,
                )
            
            decision = client.ask(prompt, expect_json=True, continue_session=True)
            print(f"      AI Analysis: {decision.get('analysis', 'N/A')[:200]}")
            print(f"      AI Decision: retry_from = {decision.get('retry_from', failed_id)}")
            print(f"      Suggested Fix: {decision.get('suggested_fix', 'N/A')[:200]}")
            # Append response to log AFTER AI returns
            if conv_logger:
                import json
                response_for_log = client.last_full_log or json.dumps(decision, indent=2, ensure_ascii=False)
                conv_logger.log_nested_response(
                    task_id=str(task['id']),
                    task_name=task['name'],
                    response=response_for_log,
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
        # Long-running task logs are now stored in the log session directory.
        # We look for signal files to find the output log paths.
        log_contents = {}
        for st in subtasks:
            if st.get('type') == 'long_running':
                st_id = str(st['id'])
                # Try to find the output log via the signal file
                try:
                    session_dir = self.session_dir
                    if not session_dir:
                        continue
                    signal_file = os.path.join(session_dir, "lr_tasks", f"lr_{st_id}_signal.json")
                    if os.path.exists(signal_file):
                        with open(signal_file, 'r', encoding='utf-8') as f:
                            signal_data = json.load(f)
                        output_log = signal_data.get('output_log', '')
                        if output_log and os.path.exists(output_log):
                            with open(output_log, 'r', encoding='utf-8', errors='replace') as f:
                                content = f.read()
                            log_contents[st_id] = content[-2000:] if len(content) > 2000 else content
                except Exception:
                    pass
        
        log_section = ""
        if log_contents:
            log_section = "\nRelevant Log Files:\n"
            for st_id, content in log_contents.items():
                log_section += f"\n--- lr_{st_id}_output.log (last part) ---\n{content}\n"
        
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
            # Write prompt to log BEFORE calling AI (crash safety)
            if conv_logger:
                conv_logger.log_nested_prompt(
                    task_id=str(task['id']),
                    task_name=task['name'],
                    call_type="main_task_evaluation",
                    prompt=prompt,
                    round_num=round_num,
                )
            
            evaluation = client.ask(prompt, expect_json=True, continue_session=True)
            completed = evaluation.get('main_task_completed', False)
            print(f"      AI Evaluation: {'✅ COMPLETED' if completed else '❌ NOT COMPLETED'}")
            print(f"      Analysis: {evaluation.get('analysis', 'N/A')[:200]}")
            # Append response to log AFTER AI returns
            if conv_logger:
                import json
                response_for_log = client.last_full_log or json.dumps(evaluation, indent=2, ensure_ascii=False)
                conv_logger.log_nested_response(
                    task_id=str(task['id']),
                    task_name=task['name'],
                    response=response_for_log,
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

    def __init__(self, session_dir: str = None):
        self.simple_executor = SimpleTaskExecutor()
        self.session_dir = session_dir

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
        Execute a long-running subtask via autoagent-exec.
        
        Flow:
        1. Build a prompt telling the AI to use autoagent-exec
        2. AI calls autoagent-exec which starts the command with fast-fail detection
        3. If AI reports LONG_RUNNING_IN_PROGRESS, poll the signal file until done
        4. When done, restart AI to analyze results
        
        The autoagent-exec script handles:
        - Fast-fail detection (errors within 10s are reported immediately)
        - Background process management
        - Signal file creation and updates
        """
        subtask_id = str(subtask['id'])
        max_attempts = subtask.get('max_attempts', 5)
        
        # Resolve the autoagent-exec script path
        autoagent_exec_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "autoagent_exec.py"
        )
        
        # Use the session_dir passed from orchestrator
        if not self.session_dir:
            raise ConfigError(
                "SubtaskExecutor.session_dir is not set. "
                "Cannot execute long-running tasks without a log session directory."
            )
        log_session_dir = self.session_dir
        
        logger.info(f"Executing long-running subtask {subtask_id}: {subtask['name']}")
        logger.info(f"  autoagent-exec: {autoagent_exec_path}")
        logger.info(f"  log session dir: {log_session_dir}")
        
        for attempt in range(1, max_attempts + 1):
            state_manager.mark_task_status(
                subtask_id, "in_progress",
                attempts=attempt,
                last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
            )
            
            print(f"\n      Long-running task attempt #{attempt}")
            
            # Build prompt for AI
            prompt = self._build_long_running_prompt(
                subtask, autoagent_exec_path, log_session_dir, attempt, state_manager,
            )
            
            try:
                continue_session = (attempt > 1)
                
                # Write prompt to log BEFORE calling AI (crash safety)
                if conv_logger:
                    conv_logger.log_prompt(
                        task_id=subtask_id,
                        task_name=subtask['name'],
                        prompt=prompt,
                        attempt=attempt,
                        parent_task_id=parent_task_id,
                    )
                
                result = client.ask(prompt, continue_session=continue_session)
                
                # Append response to log AFTER AI returns
                if conv_logger:
                    conv_logger.log_response(
                        task_id=subtask_id,
                        response=client.last_full_log or result,
                        parent_task_id=parent_task_id,
                    )
                
                # Check if AI reported LONG_RUNNING_IN_PROGRESS
                if self._check_long_running_in_progress(result):
                    print(f"      ⏳ AI submitted long-running task, waiting for completion...")
                    
                    # Poll the signal file
                    signal_file = os.path.join(log_session_dir, "lr_tasks", f"lr_{subtask_id}_signal.json")
                    output_log = os.path.join(log_session_dir, "lr_tasks", f"lr_{subtask_id}_output.log")
                    
                    monitor_status = self._poll_signal_file(subtask_id, signal_file)
                    
                    # Restart AI to analyze the result
                    return self._ai_analyze_long_running_result(
                        subtask, client, state_manager,
                        monitor_status, output_log,
                        conv_logger=conv_logger, parent_task_id=parent_task_id,
                    )
                
                # Check for normal completion (AI might have handled it directly)
                if self.simple_executor._check_completion(result):
                    print(f"      ✅ Long-running task {subtask_id} completed directly!")
                    state_manager.mark_task_status(
                        subtask_id, "completed",
                        attempts=attempt,
                        last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
                        ai_reasoning=result[:500],
                    )
                    return SubtaskResult(success=True, output=result[:500])
                
                # AI didn't complete and didn't submit long-running — maybe fast-fail retry
                print(f"      ⏳ Not completed yet, retrying...")
                state_manager.add_task_history(subtask_id, {
                    "attempt": attempt,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "result": "not_completed",
                    "ai_response": result[:500],
                })
                
            except AICallError as e:
                logger.error(f"AI call failed for long-running task {subtask_id}: {e}")
                print(f"      ❌ AI call error: {e}")
                state_manager.add_task_history(subtask_id, {
                    "attempt": attempt,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "result": "error",
                    "error": str(e),
                })
        
        # Max attempts exhausted
        print(f"      ❌ Long-running task {subtask_id} failed after {max_attempts} attempts")
        state_manager.mark_task_status(
            subtask_id, "failed",
            attempts=max_attempts,
            last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        return SubtaskResult(
            success=False,
            output=f"Failed after {max_attempts} attempts",
            error_type="max_attempts_exceeded",
        )

    def _build_long_running_prompt(
        self, subtask: dict, exec_path: str, log_session_dir: str,
        attempt: int, state_manager,
    ) -> str:
        """
        Build the prompt that tells AI to use autoagent-exec for long-running tasks.
        """
        subtask_id = str(subtask['id'])
        parts = [
            f"Task: {subtask['name']}",
            f"Type: long_running (⚠️ This task may take a long time)",
            f"Completion Criteria: {subtask['completion_criteria']}",
        ]
        
        if subtask.get('initial_hint') and attempt == 1:
            parts.append(f"Initial Hint: {subtask['initial_hint']}")
        
        if attempt > 1:
            state = state_manager.get_task_state(subtask_id)
            history = state.get('history', [])
            if history:
                recent = history[-3:]
                history_text = "\n".join(
                    f"  - Attempt {h.get('attempt', '?')}: {h.get('result', 'unknown')} - {h.get('ai_response', '')[:200]}"
                    for h in recent
                )
                parts.append(f"Previous Attempts:\n{history_text}")
            parts.append(
                "The previous attempt failed. Please analyze what went wrong "
                "and adjust your command or approach."
            )
        
        # Escape backslashes in paths for display in prompt
        exec_display = exec_path.replace("\\", "/")
        log_dir_display = log_session_dir.replace("\\", "/")
        
        parts.append(f"""\n**IMPORTANT: Long-Running Task Instructions**

This task is expected to take a long time (e.g., profiling, training, large data processing).
You MUST use the `autoagent-exec` launcher to run the command:

```bash
python "{exec_display}" --log-dir "{log_dir_display}" --task-id {subtask_id} -- <your command here>
```

**How it works:**
1. autoagent-exec will start your command and watch it for 10 seconds
2. If the command fails within 10 seconds (e.g., file not found, permission error),
   the error will be shown immediately — you can then fix the command and retry
3. If the command is still running after 10 seconds, it will be detached to the
   background and you will see a "TASK SUBMITTED" message

**When you see "TASK SUBMITTED":**
- Do NOT run any more commands
- Do NOT wait for the task to complete
- Simply output your final status as:

  ⏳ LONG_RUNNING_IN_PROGRESS

This status line is MANDATORY when the task has been submitted.
AutoAgent will call you back when the task completes with the results.

**If autoagent-exec reports an error (fast-fail within 10s):**
- Read the error output carefully
- Fix the command (e.g., correct the path, fix arguments)
- Try running autoagent-exec again with the corrected command
- If you believe the task cannot be done, output: ❌ not completed: <reason>""")
        
        return "\n\n".join(parts)

    def _check_long_running_in_progress(self, response: str) -> bool:
        """
        Check if AI reported that a long-running task has been submitted.
        """
        response_lower = response.lower()
        patterns = [
            "long_running_in_progress",
            "long running in progress",
            "⏳ long_running_in_progress",
        ]
        return any(p in response_lower for p in patterns)

    def _poll_signal_file(
        self, subtask_id: str, signal_file: str,
        check_interval: int = 15, max_wait: int = 24 * 3600,
    ) -> str:
        """
        Poll the signal file until the long-running task completes.
        
        Returns:
            str: "finished", "error", or "timeout"
        """
        elapsed = 0
        
        while elapsed < max_wait:
            if os.path.exists(signal_file):
                try:
                    with open(signal_file, "r", encoding="utf-8") as f:
                        signal_data = json.load(f)
                    
                    status = signal_data.get("status", "unknown")
                    
                    if status == "finished":
                        exit_code = signal_data.get("exit_code", -1)
                        logger.info(
                            f"Long-running task {subtask_id} finished "
                            f"(exit code {exit_code})"
                        )
                        print(f"      ✅ Long-running task finished (exit code {exit_code})")
                        return "finished"
                    
                    elif status == "error":
                        exit_code = signal_data.get("exit_code", -1)
                        logger.warning(
                            f"Long-running task {subtask_id} failed "
                            f"(exit code {exit_code})"
                        )
                        print(f"      ❌ Long-running task failed (exit code {exit_code})")
                        return "error"
                    
                    # status == "running" — keep polling
                    
                except (json.JSONDecodeError, IOError) as e:
                    logger.debug(f"Signal file read error (will retry): {e}")
            
            time.sleep(check_interval)
            elapsed += check_interval
            
            if elapsed % 300 == 0:  # Print status every 5 minutes
                print(f"      ⏳ Still running... ({elapsed // 60} minutes elapsed)")
        
        print(f"      ⏰ Long-running task timed out after {max_wait // 3600}h")
        return "timeout"

    def _ai_analyze_long_running_result(
        self, subtask, client, state_manager, status, output_log,
        conv_logger=None, parent_task_id: str = None,
    ) -> SubtaskResult:
        """
        Ask AI to analyze the result of a long-running task.
        
        Instead of embedding log content in the prompt, we provide the
        file path so the AI can read it using its Read tool.
        """
        subtask_id = str(subtask['id'])
        
        # Normalize path for display
        output_log_display = output_log.replace("\\", "/")
        
        prompt = f"""A long-running task has finished. Please analyze the result.

Subtask: {subtask['name']}
Completion Criteria: {subtask['completion_criteria']}
Task Status: {status}

The task output has been saved to:
  {output_log_display}

Please:
1. Read the output log file above to understand what happened
2. Evaluate whether the task completed successfully
3. Check if the results meet the completion criteria
4. If the task produced output files, you may examine them as needed

**CRITICAL INSTRUCTION**: Your response MUST end with EXACTLY one of these
two status lines (copy-paste verbatim, on its own line):

  ✅ completed

  ❌ not completed: <reason>

This status line is MANDATORY. Do NOT omit it. Do NOT rephrase it.
It must appear as the LAST line of your response, standalone,
exactly as shown above (with the emoji prefix).
"""
        
        try:
            # Write prompt to log BEFORE calling AI (crash safety)
            if conv_logger:
                conv_logger.log_prompt(
                    task_id=subtask_id,
                    task_name=subtask['name'],
                    prompt=prompt,
                    attempt=1,
                    parent_task_id=parent_task_id,
                    metadata={"type": "long_running_analysis"},
                )
            
            result = client.ask(prompt, continue_session=True)
            
            # Append response to log AFTER AI returns
            if conv_logger:
                conv_logger.log_response(
                    task_id=subtask_id,
                    response=client.last_full_log or result,
                    parent_task_id=parent_task_id,
                )
            
            # Reuse the same robust check logic from SimpleTaskExecutor
            is_completed = self.simple_executor._check_completion(result)
            
            # Read log content for SubtaskResult
            log_content = ""
            if os.path.exists(output_log):
                try:
                    with open(output_log, 'r', encoding='utf-8', errors='replace') as f:
                        content = f.read()
                    log_content = content[-2000:] if len(content) > 2000 else content
                except Exception:
                    log_content = "(failed to read log file)"
            
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
            state_manager.mark_task_status(
                subtask_id, "failed",
                error_type=status,
                last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
            )
            return SubtaskResult(
                success=False,
                output=f"AI analysis failed: {e}",
                logs="",
                error_type=status,
            )
