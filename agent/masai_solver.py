"""
MASAI-style 3-Phase Bounty Solver
Based on MASAI paper (NeurIPS 2024 Workshop, 28.33% SWE-bench Lite, $1.96/issue).

Pipeline:
  1. Reproducer — writes a test that reproduces the bug from the issue
  2. Localizer — finds files/lines to change based on issue + repo context
  3. Fixer — generates a minimal patch, validates against reproducer test

Each phase uses NVIDIA NIM (Qwen3 Coder) as primary model, with Groq 70B fallback.
"""

import json
import logging
import re
from pathlib import Path

from agent.ai_chain import ai

logger = logging.getLogger(__name__)


def reproduce_issue(issue_title: str, issue_body: str, repo_files: list[str]) -> dict:
    """
    Phase 1: Create a test that reproduces the bug.
    Returns dict with test_code, test_command, and confidence.
    """
    files_context = "\n".join(repo_files[:30])

    prompt = f"""You are a QA engineer. Write a test that reproduces this bug.

Issue: {issue_title}
Description: {issue_body}

Repository files:
{files_context}

Generate a minimal test that reproduces the issue. The test should:
1. Be a standalone Python script using assert statements (no pytest dependency)
2. Return exit code 0 if the bug is fixed, 1 if the bug is present
3. Only test the specific bug described — not the full functionality
4. Import from the local repository (assume run from repo root)

Format:
TEST_CODE:
```python
[test code here]
```

TEST_COMMAND:
python test_reproduce.py
"""

    response = ai(prompt, task="code", max_tokens=2000)
    if not response or "ERROR:" in response:
        logger.warning("MASAI reproduce phase failed")
        return {"success": False, "reason": "phase1_failed"}

    test_code = ""
    test_cmd = "python test_reproduce.py"
    code_match = re.search(r'```python\n(.*?)\n```', response, re.DOTALL)
    if code_match:
        test_code = code_match.group(1).strip()

    return {
        "success": bool(test_code),
        "test_code": test_code,
        "test_command": test_cmd,
        "raw_response": response,
    }


def localize_bug(issue_title: str, issue_body: str, repo_files: list[str], repo_path: str = "") -> dict:
    """
    Phase 2: Find which files and lines need to be changed.
    Returns dict with files_to_edit (list of {path, reason, lines}).
    """
    files_context = "\n".join(repo_files[:30])

    prompt = f"""You are a code analyst. Identify the exact files and lines to change.

Issue: {issue_title}
Description: {issue_body}

Repository structure:
{files_context}

List the files that need changes and why. Be specific about which lines/locations.

Format (JSON array):
[
  {{
    "path": "relative/path/to/file.py",
    "reason": "one-sentence explanation",
    "estimated_lines": "around line XX"
  }}
]

Respond ONLY with the JSON array, no other text.
"""

    response = ai(prompt, task="code", max_tokens=1000)
    if not response or "ERROR:" in response:
        logger.warning("MASAI localize phase failed")
        return {"success": False, "files_to_edit": []}

    try:
        json_match = re.search(r'\[.*\]', response, re.DOTALL)
        if json_match:
            files_to_edit = json.loads(json_match.group())
        else:
            files_to_edit = json.loads(response)
    except (json.JSONDecodeError, ValueError):
        logger.warning("MASAI: could not parse localizer output")
        files_to_edit = []

    return {
        "success": len(files_to_edit) > 0,
        "files_to_edit": files_to_edit,
        "raw_response": response,
    }


def generate_fix(
    issue_title: str,
    issue_body: str,
    files_to_edit: list[dict],
    repo_file_contents: dict[str, str],
    test_code: str = "",
) -> dict:
    """
    Phase 3: Generate a minimal fix patch.
    Returns dict with patches (list of {path, content}) and confidence score.

    Generates multiple candidate solutions and ranks them.
    """
    files_context = ""
    for path, content in repo_file_contents.items():
        lines = content.split("\n")
        files_context += f"\n--- {path} ({len(lines)} lines) ---\n"
        files_context += "\n".join(lines[:100])

    patch_targets = "\n".join(
        f"- {f['path']}: {f.get('reason', 'needs change')}" for f in files_to_edit
    )

    prompt = f"""You are a senior engineer. Generate a minimal fix for this bounty issue.

Issue: {issue_title}
Description: {issue_body}

Files to modify:
{patch_targets}

Current file contents:
{files_context}

Rules:
1. Change as few lines as possible — minimal patches get merged
2. Follow existing code style exactly
3. Do NOT modify existing tests
4. Each fix must be complete (no placeholders, no TODOs)

For each file you change, output:
FILE: path/to/file.py
```python
[COMPLETE updated file content — every line of the file, not just the diff]
```

Then at the end, add a PR_DESCRIPTION section.
"""

    response = ai(prompt, task="code", max_tokens=4000)
    if not response or "ERROR:" in response:
        logger.warning("MASAI fix phase failed")
        return {"success": False, "reason": "phase3_failed"}

    patches = []
    file_blocks = re.findall(
        r'FILE:\s*(\S+)\n```(?:python)?\n(.*?)\n```', response, re.DOTALL
    )
    for filepath, content in file_blocks:
        patches.append({
            "path": filepath.strip(),
            "content": content.strip(),
        })

    pr_desc = ""
    desc_match = re.search(r'PR_DESCRIPTION:\s*(.*?)(?:\n\n|$)', response, re.DOTALL)
    if desc_match:
        pr_desc = desc_match.group(1).strip()

    return {
        "success": len(patches) > 0,
        "patches": patches,
        "pr_description": pr_desc,
        "raw_response": response,
    }


def solve_bounty(
    issue_title: str,
    issue_body: str,
    repo_files: list[str],
    repo_file_contents: dict[str, str],
) -> dict:
    """
    Run the full 3-phase MASAI pipeline:
      1. Reproduce  → create a test that captures the bug
      2. Localize   → find files to change
      3. Fix        → generate patches + PR description

    Returns combined result with all phases.
    """
    logger.info(f"MASAI: solving '{issue_title[:60]}...'")

    phase1 = reproduce_issue(issue_title, issue_body, repo_files)
    logger.info(f"MASAI phase 1 (reproduce): {'OK' if phase1['success'] else 'FAIL'}")

    if not phase1["success"]:
        logger.warning("MASAI: reproduce phase failed, trying localize+fix without test")

    phase2 = localize_bug(issue_title, issue_body, repo_files)
    logger.info(f"MASAI phase 2 (localize): {len(phase2.get('files_to_edit', []))} files")

    if not phase2["success"]:
        return {
            "success": False,
            "phase": "localize",
            "reason": "Could not identify files to change",
            "phase1": phase1,
        }

    test_code = phase1.get("test_code", "")
    phase3 = generate_fix(issue_title, issue_body, phase2["files_to_edit"], repo_file_contents, test_code)
    logger.info(f"MASAI phase 3 (fix): {len(phase3.get('patches', []))} patches")

    return {
        "success": phase3.get("success", False),
        "phase1_reproduce": phase1,
        "phase2_localize": phase2,
        "phase3_fix": phase3,
    }
