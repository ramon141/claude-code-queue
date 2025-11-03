"""
Queue manager with execution loop.
"""

import os
import time
import signal
import uuid
from datetime import datetime, timedelta
from typing import Optional, Callable, Dict, Any, Tuple

from .models import QueuedPrompt, QueueState, PromptStatus, ExecutionResult
from .storage import QueueStorage
from .claude_interface import ClaudeCodeInterface
from .chat_sessions import ChatSessionManager


class QueueManager:
    """Manages the queue execution lifecycle."""

    def __init__(
        self,
        storage_dir: str = "~/.claude-queue",
        claude_command: str = "claude",
        check_interval: int = 30,
        timeout: int = 3600,
    ):
        self.storage = QueueStorage(storage_dir)
        self.claude_interface = ClaudeCodeInterface(claude_command, timeout)
        self.chat_sessions = ChatSessionManager(storage_dir)
        self.check_interval = check_interval
        self.running = False
        self.state: Optional[QueueState] = None

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        print(f"\nReceived signal {signum}, shutting down gracefully...")
        self.stop()

    def start(self, callback: Optional[Callable[[QueueState], None]] = None) -> None:
        """Start the queue processing loop."""
        print("Starting Claude Code Queue Manager...")

        is_working, message = self.claude_interface.test_connection()
        if not is_working:
            print(f"Error: {message}")
            return

        print(f"✓ {message}")

        self.state = self.storage.load_queue_state()
        print(f"✓ Loaded queue with {len(self.state.prompts)} prompts")

        self.running = True

        try:
            while self.running:
                self._process_queue_iteration(callback)

                if self.running:
                    time.sleep(self.check_interval)

        except KeyboardInterrupt:
            print("\nShutdown requested by user")
        except Exception as e:
            print(f"Error in queue processing: {e}")
        finally:
            self._shutdown()

    def stop(self) -> None:
        """Stop the queue processing loop."""
        self.running = False

    def _shutdown(self) -> None:
        """Clean shutdown procedure."""
        print("Shutting down...")

        if self.state:
            for prompt in self.state.prompts:
                if prompt.status == PromptStatus.EXECUTING:
                    prompt.status = PromptStatus.QUEUED
                    prompt.add_log("Execution interrupted during shutdown")

            self.storage.save_queue_state(self.state)
            print("✓ Queue state saved")

        print("Queue manager stopped")

    def _process_queue_iteration(
        self, callback: Optional[Callable[[QueueState], None]] = None
    ) -> None:
        """Process one iteration of the queue."""
        previous_total_processed = self.state.total_processed if self.state else 0
        previous_failed_count = self.state.failed_count if self.state else 0
        previous_rate_limited_count = self.state.rate_limited_count if self.state else 0
        previous_last_processed = self.state.last_processed if self.state else None
        
        self.state = self.storage.load_queue_state()
        
        self.state.total_processed = max(self.state.total_processed, previous_total_processed)
        self.state.failed_count = max(self.state.failed_count, previous_failed_count)
        self.state.rate_limited_count = max(self.state.rate_limited_count, previous_rate_limited_count)
        if previous_last_processed and (not self.state.last_processed or self.state.last_processed < previous_last_processed):
            self.state.last_processed = previous_last_processed

        self._check_rate_limited_prompts()

        next_prompt = self.state.get_next_prompt()

        if next_prompt is None:
            rate_limited_prompts = [
                p for p in self.state.prompts if p.status == PromptStatus.RATE_LIMITED
            ]
            if rate_limited_prompts:
                print(
                    f"Waiting for rate limit reset ({len(rate_limited_prompts)} prompts rate limited)"
                )
            else:
                print("No prompts in queue")

            if callback:
                callback(self.state)
            return

        print(f"Executing prompt {next_prompt.id}: {next_prompt.content[:50]}...")
        self._execute_prompt(next_prompt)

        self.storage.save_queue_state(self.state)

        if callback:
            callback(self.state)

    def _check_rate_limited_prompts(self) -> None:
        """Check if any rate-limited prompts should be retried (simple periodic retry)."""
        current_time = datetime.now()

        for prompt in self.state.prompts:
            if prompt.status == PromptStatus.RATE_LIMITED:
                # Check if enough time has passed since last rate limit (5+ minutes)
                if (
                    prompt.rate_limited_at
                    and current_time >= prompt.rate_limited_at + timedelta(minutes=5)
                ):

                    if prompt.can_retry():
                        prompt.status = PromptStatus.QUEUED
                        prompt.add_log(f"Retrying after rate limit cooldown")
                        print(f"✓ Prompt {prompt.id} ready for retry after cooldown")
                    else:
                        prompt.status = PromptStatus.FAILED
                        prompt.add_log(f"Max retries ({prompt.max_retries}) exceeded")
                        print(f"✗ Prompt {prompt.id} failed - max retries exceeded")

    def _execute_prompt(self, prompt: QueuedPrompt) -> None:
        """Execute a single prompt."""
        prompt.status = PromptStatus.EXECUTING
        prompt.last_executed = datetime.now()
        prompt.add_log(
            f"Started execution (attempt {prompt.retry_count + 1}/{prompt.max_retries})"
        )

        self.storage.save_queue_state(self.state)

        # Handle session start prompts
        if prompt.is_session_start:
            result = self._execute_session_start(prompt)
        else:
            result = self.claude_interface.execute_prompt(prompt)

        self._process_execution_result(prompt, result)

    def _execute_session_start(self, prompt: QueuedPrompt) -> ExecutionResult:
        """Execute a session start prompt and create real Claude session using CLI."""
        import subprocess
        from pathlib import Path

        start_time = time.time()

        try:
            # Extract chat name from temp session ID
            temp_session_parts = prompt.session_id.split('-')
            chat_name = temp_session_parts[1] if len(temp_session_parts) > 1 else "unnamed"

            # Generate a real UUID for this session
            real_session_id = str(uuid.uuid4())

            # Execute via CLI to create new session with specific session ID
            original_cwd = os.getcwd()
            working_dir = Path(prompt.working_directory).resolve()
            if not working_dir.exists():
                working_dir.mkdir(parents=True, exist_ok=True)

            os.chdir(working_dir)

            cmd = [
                self.claude_interface.claude_command,
                "--print",
                "--dangerously-skip-permissions",
                "--session-id", real_session_id,
                prompt.content
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.claude_interface.timeout
            )

            os.chdir(original_cwd)

            # Check if execution was successful
            if result.returncode == 0:

                # Save real session to database
                if self.chat_sessions.save_chat_session(chat_name, real_session_id, prompt.working_directory):
                    # Update prompt with real session ID
                    old_temp_session_id = prompt.session_id
                    prompt.session_id = real_session_id
                    prompt.is_session_start = False  # Mark as no longer session start

                    # Update all other prompts in queue that have the same temp session ID
                    self._update_temp_session_ids(old_temp_session_id, real_session_id)

                    execution_time = time.time() - start_time
                    return ExecutionResult(
                        success=True,
                        output=result.stdout,
                        execution_time=execution_time
                    )
                else:
                    execution_time = time.time() - start_time
                    return ExecutionResult(
                        success=False,
                        output="",
                        error="Failed to save chat session to database",
                        execution_time=execution_time
                    )
            else:
                execution_time = time.time() - start_time
                return ExecutionResult(
                    success=False,
                    output="",
                    error=f"Failed to create Claude session: {result.stderr}",
                    execution_time=execution_time
                )

        except Exception as e:
            try:
                os.chdir(original_cwd)
            except:
                pass
            execution_time = time.time() - start_time
            return ExecutionResult(
                success=False,
                output="",
                error=f"Error creating session: {e}",
                execution_time=execution_time
            )

    def _update_temp_session_ids(self, old_temp_session_id: str, real_session_id: str) -> None:
        """Update all prompts in queue that have the same temp session ID."""
        for queue_prompt in self.state.prompts:
            if queue_prompt.session_id == old_temp_session_id:
                queue_prompt.session_id = real_session_id
                # Re-save the prompt file with updated session ID
                self.storage.save_prompt(queue_prompt)

    def _process_execution_result(
        self, prompt: QueuedPrompt, result: ExecutionResult
    ) -> None:
        """Process the result of prompt execution."""
        execution_summary = f"Execution completed in {result.execution_time:.1f}s"

        if result.success:
            prompt.status = PromptStatus.COMPLETED
            prompt.add_log(f"{execution_summary} - SUCCESS")
            if result.output:
                prompt.add_log(f"Output:\n{result.output}")

            self.state.total_processed += 1
            print(f"✓ Prompt {prompt.id} completed successfully")

        elif result.is_rate_limited:
            was_already_rate_limited = prompt.status == PromptStatus.RATE_LIMITED
            prompt.status = PromptStatus.RATE_LIMITED
            prompt.rate_limited_at = datetime.now()
            prompt.retry_count += 1

            prompt.add_log(f"{execution_summary} - RATE LIMITED")
            if result.rate_limit_info and result.rate_limit_info.limit_message:
                prompt.add_log(f"Message: {result.rate_limit_info.limit_message}")

            if not was_already_rate_limited and self.state is not None:
                self.state.rate_limited_count += 1
            print(f"⚠ Prompt {prompt.id} rate limited, will retry later")

        else:
            prompt.retry_count += 1

            if prompt.can_retry():
                prompt.status = PromptStatus.QUEUED
                prompt.add_log(f"{execution_summary} - FAILED (will retry)")
                if result.error:
                    prompt.add_log(f"Error: {result.error}")
                print(
                    f"✗ Prompt {prompt.id} failed, will retry ({prompt.retry_count}/{prompt.max_retries})"
                )
            else:
                prompt.status = PromptStatus.FAILED
                prompt.add_log(f"{execution_summary} - FAILED (max retries exceeded)")
                if result.error:
                    prompt.add_log(f"Error: {result.error}")

                self.state.failed_count += 1
                print(
                    f"✗ Prompt {prompt.id} failed permanently after {prompt.max_retries} attempts"
                )

        self.state.last_processed = datetime.now()

    def add_prompt(self, prompt: QueuedPrompt) -> bool:
        """Add a prompt to the queue."""
        try:
            if not self.state:
                self.state = self.storage.load_queue_state()

            self.state.add_prompt(prompt)

            success = self.storage.save_queue_state(self.state)
            if success:
                print(f"✓ Added prompt {prompt.id} to queue")
            else:
                print(f"✗ Failed to save prompt {prompt.id}")

            return success

        except Exception as e:
            print(f"Error adding prompt: {e}")
            return False

    def remove_prompt(self, prompt_id: str) -> bool:
        """Remove a prompt from the queue."""
        try:
            if not self.state:
                self.state = self.storage.load_queue_state()

            prompt = self.state.get_prompt(prompt_id)
            if prompt:
                if prompt.status == PromptStatus.EXECUTING:
                    print(f"Cannot remove executing prompt {prompt_id}")
                    return False

                prompt.status = PromptStatus.CANCELLED
                prompt.add_log("Cancelled by user")

                success = self.storage.save_queue_state(self.state)
                if success:
                    print(f"✓ Cancelled prompt {prompt_id}")
                else:
                    print(f"✗ Failed to cancel prompt {prompt_id}")

                return success
            else:
                print(f"Prompt {prompt_id} not found")
                return False

        except Exception as e:
            print(f"Error removing prompt: {e}")
            return False

    def get_status(self) -> QueueState:
        """Get current queue status."""
        if not self.state:
            self.state = self.storage.load_queue_state()
        return self.state

    def create_prompt_template(self, filename: str, priority: int = 0) -> str:
        """Create a prompt template file."""
        file_path = self.storage.create_prompt_template(filename, priority)
        return str(file_path)

    def find_session_by_chat_name(self, chat_name: str) -> Optional[str]:
        """Find session_id by chat name using ChatSessionManager or queued prompts."""
        # First check existing chat sessions
        session_id = self.chat_sessions.get_session_id(chat_name)
        if session_id:
            return session_id

        # If not found, check for queued session start prompts
        # Load state if not already loaded
        if not self.state:
            self.state = self.storage.load_queue_state()

        for prompt in self.state.prompts:
            if prompt.is_session_start and prompt.session_id and f"temp-{chat_name}-" in prompt.session_id:
                return prompt.session_id

        return None

    def create_chat_session(self, chat_name: str, initial_prompt: str, working_directory: str = ".") -> Tuple[bool, str, Optional[str]]:
        """Create a new chat session by adding initial prompt to queue."""
        try:
            # Check if chat already exists
            if self.chat_sessions.chat_exists(chat_name):
                return False, f"Chat '{chat_name}' already exists", None

            # Generate a temporary session ID that will be replaced with real UUID when executed
            temp_session_id = f"temp-{chat_name}-{uuid.uuid4().hex[:8]}"

            # Create initial prompt and mark as session start
            prompt = QueuedPrompt(
                content=initial_prompt,
                working_directory=working_directory,
                session_id=temp_session_id,
                is_session_start=True,
                priority=-1  # Higher priority to execute first
            )

            # Add to queue
            self.add_prompt(prompt)

            return True, f"Chat session '{chat_name}' queued for creation", temp_session_id

        except Exception as e:
            return False, f"Error creating chat session: {e}", None
