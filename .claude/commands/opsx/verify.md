---
name: "OPSX: Verify"
description: Independent verification of a completed change before archive. Spawns a leaf subagent with no parent context to validate against openspec/verify-template.md
category: Workflow
tags: [workflow, verify, experimental, qa]
---

Independent verification of a completed change before archive.

**Input**: Specify a change name after `/opsx:verify` (e.g., `/opsx:verify 2026-07-08-t0-task-management`). If omitted, prompt for available archived changes.

**Purpose**: Spawn an independent leaf subagent (NO parent context) that validates the change against `openspec/verify-template.md`. This catches PM/Dev blind spots by giving the verifier a fresh perspective.

**Steps**

1. **If no change name provided, prompt for selection**

   Run `ls openspec/changes/archive/` to get archived changes. Use AskUserQuestion to let the user select.

   Show only changes with a complete 4-file structure (proposal.md + spec-deltas/ + tasks.md).

2. **Pre-flight: gather evidence in the parent context**

   Before spawning the subagent, the parent collects raw evidence so the subagent doesn't need context inheritance:

   ```bash
   # git history
   cd <project-root>
   git log --oneline main..HEAD 2>/dev/null || git log --oneline -20
   
   # archive structure
   ls -la "openspec/changes/archive/<change-name>/"
   ls -la "openspec/changes/archive/<change-name>/spec-deltas/" 2>/dev/null
   
   # task completion
   grep -c '\[x\]' "openspec/changes/archive/<change-name>/tasks.md"
   grep -c '\[ \]' "openspec/changes/archive/<change-name>/tasks.md"
   
   # e2e scripts available
   ls scripts/e2e/ 2>/dev/null
   
   # backend health (best-effort, non-fatal)
   curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health 2>/dev/null || echo "no-backend"
   ```

   Capture all output. This becomes the "Evidence Pack" passed to the subagent.

3. **Spawn INDEPENDENT leaf subagent via delegate_task**

   The subagent must have **zero access to parent conversation context**. It sees only:
   - Project root path
   - Change name
   - Evidence Pack (raw output from step 2)
   - Template path: `openspec/verify-template.md`
   - Output path: `openspec/changes/archive/<change-name>/VERIFICATION_REPORT.md`

   Use `delegate_task` with `role='leaf'`:

   ```python
   delegate_task(
       goal=f"Verify change '{change_name}' against checklist",
       context=f"""
       Project root: {project_root}
       Change name: {change_name}
       Archive path: openspec/changes/archive/{change_name}/
       
       You are an INDEPENDENT verification subagent. You have NO context
       from the conversation that spawned you. Treat this as a cold audit.
       
       === EVIDENCE PACK (raw output, pre-gathered by parent) ===
       {evidence_pack_text}
       ============================================================
       
       Your job:
       1. Read openspec/verify-template.md (the checklist)
       2. For each checklist item, mark ✓/✗ with evidence (file path, line
          number, command output, commit hash). DO NOT trust the evidence
          pack blindly — re-verify the most critical items yourself.
       3. Run e2e if available and backend is running
       4. Write VERIFICATION_REPORT.md to:
          {project_root}/openspec/changes/archive/{change_name}/VERIFICATION_REPORT.md
       5. Return PASS / PASS-with-warnings / FAIL with one-line summary
       
       Tools: terminal, file, search. NO web, NO memory, NO parent context.
       Respond in Chinese (project default).
       """,
       toolsets=["terminal", "file", "search"]
   )
   ```

4. **Parse subagent verdict and surface to user**

   The subagent returns one of:
   - **PASS** → "✓ 验收通过。可执行 `/opsx:archive`"
   - **PASS-with-warnings** → show warning items, ask user to confirm archive
   - **FAIL** → show ✗ items + remediation steps, DO NOT archive

5. **Display summary**

   ```
   ## Verify Complete: <change-name>
   
   | Section | Result |
   |---------|--------|
   | 1. 文件交付 | ✓/✗ |
   | 2. Git 卫生 | ✓/✗ |
   | 3. 代码/测试 | ✓/✗ |
   | 4. 业务回归 | ✓/⚠/✗ |
   | 5. 文档 | ✓/✗ |
   
   **Verdict**: PASS | PASS-with-warnings | FAIL
   **Report**: openspec/changes/archive/<change-name>/VERIFICATION_REPORT.md
   **Next**: /opsx:archive <change-name>
   ```

**Guardrails**
- Subagent MUST be role=leaf (cannot delegate further)
- Subagent MUST have NO access to parent context (self-contained prompt)
- Subagent SHOULD re-verify at least 2 critical claims (commit hash + e2e status)
- VERIFICATION_REPORT.md is the audit trail — never delete, even on FAIL
- If evidence pack is incomplete, subagent fills the gap itself (don't pre-block)
- Verifier output language: Chinese (project default per user preference)
