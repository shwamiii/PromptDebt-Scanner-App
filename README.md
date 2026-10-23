# PromptDebt Scanner

Built as part of the ITMDA3-34 Formative Deliverable 4.

A mobile-first web app that checks how well a public GitHub repository keeps its AI
coding-tool instruction files (`CLAUDE.md`, `AGENTS.md`, `.cursorrules`,
`.github/copilot-instructions.md`, `Plan.md`) in step with its code. Paste a repo URL
and get a **Prompt Debt Score**, the evidence behind it, and findings you can track on
a watchlist and triage.

## How it relates to the research

PromptDebt Scanner is the applied counterpart to the research paper *Prompts as
Technical Debt: A Study on Maintaining AI-Generated Codebases and Traceability between
Prompts and Source Code*. The paper argues that AI-assisted development creates a new
kind of technical debt: the reasoning behind AI-generated code lives in prompts that
are rarely stored, versioned or reviewed.

Most prompts are discarded and can't be analysed. The ones that survive are the agent
instruction files teams commit alongside their code, the same artefacts the paper's
repository-mining phase targets. The app measures the paper's observable dimensions
for those files:

- **Storage and discoverability:** which artefacts exist, and whether the README
  mentions them.
- **Maintenance behaviour:** how far each artefact lags behind the code, measured in
  days and in commits.
- **Structural quality:** size (context bloat), rules repeated across files, and paths
  that no longer exist.

## Features

- **Scan** any public repo by URL, with no account. Results are "as of HEAD" (measured
  against the latest commit, not today), so re-scanning an unchanged repo gives the
  same numbers.
- **Report:** a 0–100 Prompt Debt Score with a points breakdown, every artefact's
  measurements, broken references with line numbers and reasons, and findings.
- **Watchlist** (CRUD): save repos with a label and notes, rescan, see each repo's
  score and open findings.
- **AI review** (optional): one model call per scan finds rules that contradict each
  other, which count towards the score, and writes a short "what's most wrong"
  overview.
- **Triage** (CRUD): mark findings on watched repos as Open, Acknowledged, Fixed or
  Ignored, with a note. Findings marked Fixed but still detected are flagged.
- **Anonymous identity:** each device gets a random key instead of an account. Copy it
  to another device, or delete all your data.
- **Installable** as a Progressive Web App on Android and iOS, and ready to wrap with
  Capacitor for an app-store build.

