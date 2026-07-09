#!/usr/bin/env bash
# Run this skill's pipeline under OpenAI's Codex CLI instead of Claude Code.
#
# Codex CLI supports the same Agent Skills format this repo already uses
# (SKILL.md + scripts/ + references/), so there is no separate Codex-specific
# pipeline -- this just shells out to `codex exec` and points it at this
# skill's SKILL.md and the screenshot folder you give it, explicitly by path
# rather than relying on Codex's `.agents/skills/` auto-discovery (which
# requires this folder to live in a specific location relative to Codex's
# working directory).
#
# Usage:
#   scripts/run_via_codex.sh [--full-access] <screenshot-folder> [extra instructions...]
#
# Requires the Codex CLI installed and authenticated:
#   https://developers.openai.com/codex/cli
#
# Sandbox: defaults to --sandbox workspace-write, which lets Codex write
# output files but may not reach a screenshot folder outside its working
# directory tree. Pass --full-access as the first argument to use
# --sandbox danger-full-access instead if your screenshots live somewhere
# workspace-write can't see -- that grants Codex unrestricted filesystem
# access for this run, so only use it if you understand that tradeoff.

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SANDBOX="workspace-write"

if [[ "${1:-}" == "--full-access" ]]; then
  SANDBOX="danger-full-access"
  shift
fi

if [[ $# -lt 1 ]]; then
  echo "Usage: run_via_codex.sh [--full-access] <screenshot-folder> [extra instructions...]" >&2
  exit 1
fi

SCREENSHOT_PATH="$1"
shift
EXTRA="$*"

if ! command -v codex >/dev/null 2>&1; then
  echo "codex CLI not found. Install it from https://developers.openai.com/codex/cli and authenticate before running this." >&2
  exit 1
fi

PROMPT="Use the Agent Skill at ${SKILL_DIR} -- read its SKILL.md and follow the workflow exactly, including spawning subagents for the review/organize/digest steps where the instructions call for it -- to process the screenshots at ${SCREENSHOT_PATH}. ${EXTRA}"

echo "Running via Codex CLI (sandbox: ${SANDBOX})..." >&2
codex exec --sandbox "${SANDBOX}" "${PROMPT}"
