# Claude Code Queue

A tool to queue Claude Code prompts and automatically execute them when token limits reset, preventing manual waiting during 5-hour limit windows.

## Features

-   **Markdown-based Queue**: Each prompt is a `.md` file with YAML frontmatter
-   **Automatic Rate Limit Handling**: Detects rate limits and waits for reset windows
-   **Priority System**: Execute high-priority prompts first
-   **Retry Logic**: Automatically retry failed prompts
-   **Persistent Storage**: Queue survives system restarts
-   **CLI Interface**: Simple command-line interface

## Installation

```bash
pip install claude-code-queue
```

Or, for local development:

```bash
cd claude-code-queue
pip install -e .
```

## Quick Start

After installation, use the `claude-queue` command:

1. **Test Claude Code connection:**

    ```bash
    claude-queue test
    ```

2. **Add a quick prompt:**

    ```bash
    claude-queue add "Fix the authentication bug" --priority 1
    ```

3. **Create a detailed prompt template:**

    ```bash
    claude-queue template my-feature --priority 2
    # Edit ~/.claude-queue/queue/my-feature.md with your prompt
    ```

4. **Start the queue processor:**
    ```bash
    claude-queue start
    ```

## Usage

### Adding Prompts

**Quick prompt:**

```bash
claude-queue add "Implement user authentication" --priority 1 --working-dir /path/to/project
```

**Template for detailed prompt:**

```bash
claude-queue template auth-feature
```

This creates `~/.claude-queue/queue/auth-feature.md`:

```markdown
---
priority: 0
working_directory: .
context_files: []
max_retries: 3
estimated_tokens: null
---

# Prompt Title

Write your prompt here...

## Context

Any additional context or requirements...

## Expected Output

What should be delivered...
```

### Managing the Queue

**Check status:**

```bash
claude-queue status --detailed
```

**List prompts:**

```bash
claude-queue list --status queued
```

**Cancel a prompt:**

```bash
claude-queue cancel abc123
```

### Running the Queue

**Start processing:**

```bash
claude-queue start
```

**Start with verbose output:**

```bash
claude-queue start --verbose
```

## How It Works

1. **Queue Processing**: Runs prompts in priority order (lower number = higher priority)
2. **Rate Limit Detection**: Monitors Claude Code output for rate limit messages
3. **Automatic Waiting**: When rate limited, waits for the next 5-hour window
4. **Retry Logic**: Failed prompts are retried up to `max_retries` times
5. **File Organization**:
    - `~/.claude-queue/queue/` - Pending prompts
    - `~/.claude-queue/completed/` - Successful executions
    - `~/.claude-queue/failed/` - Failed prompts
    - `~/.claude-queue/queue-state.json` - Queue metadata

## Configuration

### Command Line Options

```bash
claude-queue --help
```

Key options:

-   `--storage-dir`: Queue storage location (default: `~/.claude-queue`)
-   `--claude-command`: Claude CLI command (default: `claude`)
-   `--check-interval`: Check interval in seconds (default: 30)
-   `--timeout`: Command timeout in seconds (default: 3600)

### Prompt Configuration

Each prompt supports these YAML frontmatter options:

```yaml
---
priority: 1 # Execution priority (0 = highest)
working_directory: /path/to/project # Where to run the prompt
context_files: # Files to include as context
    - src/main.py
    - README.md
max_retries: 3 # Maximum retry attempts
estimated_tokens: 1000 # Estimated token usage (optional)
---
```

## Examples

### Basic Usage

```bash
# Add a simple prompt
claude-queue add "Run tests and fix any failures" --priority 1

# Create template for complex prompt
claude-queue template database-migration --priority 2

# Start processing
claude-queue start
```

### Complex Prompt Template

```markdown
---
priority: 1
working_directory: /Users/me/my-project
context_files:
    - src/auth.py
    - tests/test_auth.py
    - docs/auth-requirements.md
max_retries: 2
estimated_tokens: 2000
---

# Fix Authentication Bug

There's a bug in the user authentication system where users can't log in with special characters in their passwords.

## Context

-   The issue affects passwords containing @, #, $ symbols
-   Error occurs in the password validation function
-   Tests are failing in test_auth.py

## Requirements

1. Fix the password validation to handle special characters
2. Update tests to cover edge cases
3. Ensure backward compatibility

## Expected Output

-   Fixed authentication code
-   Updated test cases
-   Documentation update if needed
```

## Rate Limit Handling

The system automatically detects Claude Code rate limits by monitoring:

-   "usage limit reached" messages
-   Claude's reset time information
-   Standard rate limit error patterns

When rate limited:

1. Prompt status changes to `rate_limited`
2. System calculates next reset time (5-hour windows)
3. Queue processing pauses until reset
4. Failed prompt is retried automatically

## Troubleshooting

**Queue not processing:**

```bash
# Check Claude Code connection
claude-queue test

# Check queue status
claude-queue status --detailed
```

**Prompts stuck in executing state:**

-   Stop queue processor (Ctrl+C)
-   Restart with `claude-queue start`
-   Executing prompts will reset to queued status

**Rate limit not detected:**

-   Check if Claude Code output format changed
-   File an issue with the error message you received

## Directory Structure

```
~/.claude-queue/
├── queue/               # Pending prompts
│   ├── 001-fix-bug.md
│   └── 002-feature.executing.md
├── completed/           # Successful executions
│   └── 001-fix-bug-completed.md
├── failed/              # Failed prompts
│   └── 003-failed-task.md
└── queue-state.json     # Queue metadata
```
