---
tags: [aso/plan, aso/ui, aso/ux]
status: proposed
updated: 2026-08-13
---

# UI Rebuild — Clear Workflow, 3D Visual Layer, Live Agent Arena, Decision-First Results

## 1. Intent

This plan refines the existing UI rebuild specification without changing the product workflow or backend direction.

The existing plan already establishes the right product sequence:

1. Repository analysis
2. Task selection from commit history
3. Explicit harness × model pairs
4. Execution summary
5. Live agent activity and code edits
6. KPI comparison and recommendations

It also already establishes several important technical constraints:

- custom components instead of MUI
- explicit harness/model pairs instead of a forced Cartesian product
- live workspace diffs plus agent-step telemetry
- one persistent React Three Fiber canvas
- exact numerical results rendered as crisp DOM
- persisted SSE events
- model availability/preflight states
- statistical weakness and insufficient-signal states

This proposal keeps those decisions except for one UX change:

> Replace **3D-first navigation** with **2D-first interaction inside a persistent 3D visual environment**.

The goal is to make the application creative and memorable without making a technical benchmarking workflow harder to understand.

---

# 2. Product experience principle

The product should feel like:

> **A laboratory where AI coding stacks compete on the user's own codebase.**

The user should never feel like they are operating a benchmark framework.

They should feel like they are answering a sequence of simple questions:

| Stage | User question |
|---|---|
| Repository | Can you reliably benchmark my repo? |
| Tasks | What should the agents attempt? |
| Agent Stacks | Which setups should compete? |
| Review | What exactly will happen? |
| Live | What are the agents doing? |
| Results | Which stack should I use? |

Every screen should primarily answer one of these questions.

Advanced implementation details remain available, but they should not dominate the default workflow.

---

# 3. Primary UX change: 2D-first, 3D-enhanced

## Existing direction

The current plan specifies a full 3D-first interface where spatial navigation is the primary surface.

That creates a risk: this product ultimately asks users to trust precise measurements and make a technical decision.

Spatial navigation can make the application memorable, but it can also increase cognitive load.

## Proposed direction

Use:

> **Conventional, extremely clear 2D interaction + meaningful 3D state visualization.**

### 2D owns

- forms
- buttons
- navigation
- repository information
- task selection
- model selection
- settings
- code diffs
- logs
- tables
- metrics
- recommendations
- charts

### 3D owns

- atmosphere
- repository-analysis visualization
- Agent Stack nodes
- transitions between stages
- execution lanes
- run-state visualization
- experiment launch
- winner reveal

### Never encode precise values in 3D

Do not communicate:

- 92% correctness
- 17.4k tokens
- 2m 41s duration
- reliability
- confidence
- cost

through node size, depth, perspective, glow strength, or position alone.

Those values must remain normal DOM text.

---

# 4. Persistent workflow navigation

Use a simple progress/navigation bar throughout setup:

```text
Repository ── Tasks ── Agent Stacks ── Review ── Run ── Results
    ✓          ✓            ●
```

Properties:

- always visible during the main workflow
- completed stages are clickable when safe
- current stage is obvious
- future stages are visible but subdued
- navigation works without the 3D canvas
- scene camera/state may transition when the stage changes

This provides a stable mental model while the scene creates visual continuity.

---

# 5. Visual identity

## Direction

Professional developer tooling with a scientific-experiment identity.

Avoid:

- game HUD styling
- neon overload
- decorative particles everywhere
- giant glassmorphism cards
- excessive gradients
- sci-fi typography
- rotating 3D objects with no meaning

Prefer:

- nearly black background
- subtle depth
- one primary electric accent
- restrained green/amber/red status colors
- thin borders
- crisp typography
- generous whitespace
- controlled glow around active experiment elements
- subtle technical grid/network motifs

## Inspiration qualities

Aim for the clarity/polish associated with:

- Linear
- Vercel
- Raycast
- Stripe developer products

combined with the visual metaphor of:

- an experiment laboratory
- an execution arena
- a controlled race between agent stacks

---

# 6. Design tokens

Keep all design decisions centralized.

Suggested categories:

```text
design/
  tokens.ts
  typography.ts
  motion.ts
```

Tokens should cover:

- background
- surface levels
- primary accent
- text primary/secondary/faint
- success
- warning
- danger
- borders
- radii
- spacing
- type scale
- shadows
- glow
- transition duration
- easing

No arbitrary component-level color values unless technically necessary.

---

# 7. Frontend architecture

Preserve the existing frontend foundation:

- React 19
- TypeScript
- Vite
- TanStack Query
- React Router
- existing typed `src/api.ts`
- Recharts

Use:

- `three`
- `@react-three/fiber`
- `@react-three/drei`
- `framer-motion`

Suggested structure:

```text
src/
  design/
    tokens.ts
    typography.ts
    motion.ts

  ui/
    Button/
    Field/
    Select/
    Panel/
    Dialog/
    Toast/
    Chip/
    Badge/
    Tabs/
    Progress/
    Metric/
    EmptyState/
    Status/

  scene/
    Canvas.tsx
    stages.ts
    nodes/
      RepositoryNode.tsx
      AgentStackNode.tsx
      ExecutionLane.tsx
    effects/
      AmbientField.tsx
      StageTransition.tsx

  screens/
    Repository.tsx
    Tasks.tsx
    AgentStacks.tsx
    Review.tsx
    Live.tsx
    Results.tsx

  hooks/
    useExperimentStream.ts
    useStrategy.ts
    useModels.ts
```

---

# 8. Scene architecture

Use one persistent React Three Fiber `<Canvas>`.

Do not remount the scene between screens.

Each workflow stage defines:

- camera target
- camera distance
- visible scene elements
- active nodes
- ambient motion level
- transition behavior

Example:

```ts
type SceneStage =
  | "repository"
  | "tasks"
  | "stacks"
  | "review"
  | "live"
  | "results";
```

The scene should never block UI rendering.

DOM content loads first.

If WebGL fails, the entire workflow remains usable.

---

# 9. Motion rules

Animation should communicate real state.

## Good animation

### Repository analysis

A repository graph gradually forms as analysis progresses.

### Task discovery

Candidate commits appear as selected points along a subtle history line.

### Agent Stack creation

Harness and model nodes visually connect.

### Experiment launch

Selected stacks move into execution lanes.

### Live execution

Nodes progress through lanes as real run states change.

### Results

The winning stack is visually emphasized after the recommendation is already available in DOM.

## Avoid

- forced intro sequences
- slow camera flights
- navigation that requires dragging the scene
- decorative movement competing with code
- delayed result rendering for dramatic effect
- animation that makes users wait

---

# 10. Screen 1 — Repository

## User question

> Can my repository be benchmarked?

## Initial state

Keep this screen extremely focused.

```text
                         AGENT STACK LAB

                Find the best AI coding stack
                     for your repository.

            ┌───────────────────────────────┐
            │ github.com/user/repository    │
            │                    Analyze →  │
            └───────────────────────────────┘
```

Secondary option:

```text
or choose a local repository
```

No complex dashboard should appear before the first repository is selected.

---

## Analysis state

Explain what is happening in plain language.

```text
Analyzing your repository

✓ Detecting language and framework
✓ Finding tests and build commands
● Inspecting commit history
○ Identifying strong benchmark tasks
○ Verifying evaluation quality
```

If commands are executing inside a sandbox, a subtle line can say:

```text
Analysis runs in an isolated local container.
```

Do not expose internal evaluation-rung terminology here.

---

## Successful state

Lead with the conclusion:

```text
┌─────────────────────────────────────────────────┐

  ✓ Ready to benchmark

  backend-api

  Python · FastAPI
  127 tests
  38 candidate historical changes

  Evaluation quality
  ●●●●○  Strong

  We found enough deterministic signals to
  compare coding agents reliably.

                              Continue →

└─────────────────────────────────────────────────┘
```

Then:

```text
How we'll evaluate

✓ Existing repository tests
✓ Historical changes
✓ Hidden tests from selected commits

⚠ 2 setup suggestions

View evaluation strategy →
```

### Evaluation strategy details

The existing rung/strategy information remains available under an expandable advanced panel.

Do not remove the underlying information.

Only improve its presentation.

---

## Unbenchmarkable state

This must remain a first-class result.

```text
We can't reliably benchmark this repository yet.

No deterministic test, build, or behavioral signal was found.

Recommended next steps

1. Add a basic test suite
2. Choose a historical change that introduced tests
3. Add a custom evaluation command
```

Do not show this only as a toast.

---

# 11. Screen 2 — Tasks

## User question

> What should the agents attempt?

The backend already recommends commits and explains why they were nominated.

Make that intelligence central to the UI.

---

## Recommended task cards

Prefer cards over a dense commit table for the default view.

```text
Recommended benchmark tasks                       3 selected

┌──────────────────────────────────────────────────────┐
│ ★ BEST SIGNAL                                        │
│                                                      │
│ Fix stale cache invalidation                         │
│ a8f24d · Bug fix · 4 files                          │
│                                                      │
│ ✓ Added tests                                        │
│ ✓ Clear behavioral change                            │
│ ✓ No external-service dependency                     │
│                                                      │
│ Why we recommend it                                  │
│ A contained bug fix with strong hidden tests and     │
│ a deterministic success signal.                      │
│                                                      │
│                                           [Selected] │
└──────────────────────────────────────────────────────┘
```

Signal labels:

- Best signal
- Strong
- Medium
- Weak

Commits with useful added tests should receive clear visual priority.

---

## Task detail drawer

On expansion show:

- commit SHA
- subject
- parent commit
- files changed
- historical patch size
- tests added
- hidden-test candidates
- inferred task type
- why selected
- evaluation strategy
- evaluation confidence

Allow task-description editing.

The historical solution remains hidden from the agent.

---

# 12. Screen 3 — Agent Stacks

## User question

> Which setups should compete?

Rename "Combinations" in the UI to:

> **Agent Stacks**

An Agent Stack currently means:

```text
Harness × Model
```

Later it may naturally grow into:

```text
Harness × Model × Prompt × Tools × Configuration
```

---

## Explicit pair selection

Preserve the existing explicit-pair behavior.

Never force:

```text
2 harnesses × 2 models = 4 stacks
```

The user may intentionally choose only:

```text
mini-SWE × Model A
smolagents × Model B
```

and therefore create exactly two stacks.

---

## Stack presentation

```text
Agent Stacks

Choose the setups you want to compare.

┌──────────────────────────────┐
│ mini-SWE-agent               │
│             ×                │
│ Qwen3 Coder                  │
│                              │
│ ● Available                  │
│                         ✕    │
└──────────────────────────────┘

┌──────────────────────────────┐
│ smolagents                   │
│             ×                │
│ GPT-OSS                      │
│                              │
│ ● Available                  │
│                         ✕    │
└──────────────────────────────┘

              + Add Agent Stack
```

---

## Add Agent Stack

Use a focused modal/drawer.

```text
Add Agent Stack

Harness
○ mini-SWE-agent
○ smolagents
○ OpenHands

                    ×

Model
○ Qwen Coder                     Available
○ GPT-OSS                        Available
○ DeepSeek Coder                 Slow
○ Another Model                  Unavailable

                         Add stack
```

Show availability states already defined by the backend:

- available
- slow
- unusable
- unchecked

Unusable models are disabled and display the reason.

Unchecked models may expose:

```text
Check availability
```

---

## 3D representation

Every selected stack becomes a scene node.

Conceptually:

```text
                    OpenHands
                        ×
                    Qwen Coder
                         ●


             ●                           ●
        mini-SWE                    smolagents
            ×                           ×
         Qwen                       GPT-OSS
```

This creates continuity:

the nodes selected here become the competitors shown during execution and results.

---

# 13. Screen 4 — Review

## User question

> What exactly is going to happen?

The screen should feel like experiment launch confirmation.

Not another settings form.

```text
READY TO RUN

3 Agent Stacks
×
4 coding tasks
×
3 repetitions

36 benchmark runs


Estimated
────────────────────────
~22 min
30 max model calls / run
$0.00 estimated API cost


Evaluation
────────────────────────
✓ Existing tests
✓ Hidden historical tests
✓ Regression analysis


                       Start experiment →
```

---

## Explain evaluation strength

If a task uses weak signals:

```text
⚠ Limited evaluation confidence

1 selected task can only be checked for build success.

It will contribute less confidence to the final recommendation.
```

Never describe build-only success as correctness.

---

## Advanced settings

Hide configuration complexity behind:

```text
Advanced settings
```

Include:

- repetitions
- request budget
- token budget
- timeout
- concurrency
- CPU limit
- memory limit
- temperature
- scoring weights

If mini-SWE-agent requires a larger request budget for fair comparison, surface a contextual recommendation.

Example:

```text
Recommended: 30 model calls

mini-SWE-agent often needs more iterations than smolagents.
Using a smaller limit may make the comparison unfair.
```

---

# 14. Screen 5 — Live Experiment

## User question

> What are the agents doing?

This is the experiential centerpiece of the application.

The existing telemetry plan supports:

- lifecycle events
- agent steps
- code edits
- model calls
- persisted SSE replay

Do not present all information with equal visual weight.

---

## Primary layout

Use:

1. experiment progress
2. run/stack selector
3. focused run
4. detail tabs

Example:

```text
Experiment 14                               8 / 36 complete

                    ● mini-SWE × Qwen
                    RUNNING
                    02:14

      ┌────────────────────────────────────────┐
      │ Reading auth/session.py                │
      │                                        │
      │ → Found stale session cache            │
      │ → Editing session.py                   │
      │ → Running pytest                       │
      │                                        │
      │ tests/auth/test_session.py             │
      │ ███████████████████░  23 / 24         │
      └────────────────────────────────────────┘


✓ smolagents × Qwen
● mini-SWE × Qwen
○ smolagents × GPT-OSS
```

---

## Run selector

Clearly distinguish:

- queued
- preparing
- running
- evaluating
- completed
- failed
- rate limited
- timed out

Clicking a run changes the focused panel.

Do not force users to inspect every run simultaneously.

---

# 15. Live detail tabs

Use:

```text
Timeline | Code | Model Calls | Logs
```

## Timeline

Human-readable observable activity.

```text
12:04  Read auth/session.py
12:06  Identified stale cache behavior
12:07  Edited session.py
12:09  Ran pytest
12:10  23 / 24 tests passed
```

Do not expose private chain-of-thought.

Use observable summaries/actions only.

---

## Code

Present live bounded diffs in a mini-IDE-like panel.

```diff
session.py

- return cache[user_id]
+ session = cache.get(user_id)
+ if session and not session.expired:
+     return session
```

Animate the arrival of new edits subtly.

Do not animate the code itself excessively.

---

## Model Calls

Show:

```text
#12  200 OK       20.4s      631 output tokens
#13  200 OK       15.2s      212 output tokens
#14  429 retry    waiting
```

Expandable detail:

- exact model
- provider
- latency
- token usage
- retry
- error category
- cost

---

## Logs

Raw observable harness logs.

Requirements:

- bounded
- virtualized
- searchable if inexpensive
- no secrets
- no hidden reasoning
- clear truncation indicator

---

# 16. Live 3D experiment arena

Use the scene to represent the experiment.

Concept:

```text
                         TASK PROGRESS →

mini-SWE × Qwen        ●━━━━━━━●━━━━━━●

smolagents × Qwen      ●━━━━━━━━━━●

smolagents × GPT       ●━━━━●
```

Possible state language:

- dim node = queued
- pulsing node = running
- scanning ring = evaluating
- stable accent = completed
- restrained red = failed
- amber = rate limited

The scene reflects real run state.

It does not replace the status text.

---

# 17. Telemetry integrity

Preserve the existing backend plan:

```text
host <tmp_root>/telemetry   → container /telemetry
host <tmp_root>/workspace   → container /workspace
```

Telemetry must never enter the measured patch.

Continue emitting structured events such as:

```json
{
  "i": 3,
  "at": "2026-08-13T01:12:04Z",
  "kind": "action",
  "text": "Opening config.py",
  "tool": "python",
  "tokens_out": 162
}
```

and edit events:

```json
{
  "file": "config.py",
  "added": 18,
  "removed": 2,
  "preview": "..."
}
```

Persist them as `RunEvent` records and use the existing SSE replay behavior.

Absence of harness telemetry means unknown, not zero.

---

# 18. Screen 6 — Results

## User question

> Which stack should I use?

This is the product's actual output.

Start with the recommendation.

Do not start with a dashboard of charts.

---

## Hero recommendation

```text
BEST STACK FOR THIS REPOSITORY

╭──────────────────────────────────────────────╮
│                                              │
│           mini-SWE-agent × Qwen3             │
│                                              │
│               92 / 100                       │
│                                              │
│          Best overall balance                │
│                                              │
│  94% correctness     93% reliability         │
│  2m 41s avg          17.4k tokens            │
│                                              │
╰──────────────────────────────────────────────╯
```

---

## Why it won

Immediately explain the result.

```text
Why it won

✓ Solved 11 of 12 tasks
✓ No critical regressions
✓ Lowest token usage among stacks above 90% correctness
✓ Consistent across all 3 repetitions
```

This is more valuable than presenting only a composite score.

---

# 19. Recommendation categories

Show four recommendation cards:

### Best Balanced

Best tradeoff across quality, reliability, time, tokens, and resources.

### Highest Quality

The strongest correctness result regardless of efficiency.

### Most Reliable

The most consistent result across repetitions/tasks.

### Most Efficient

The strongest acceptable solution for time/token/resource use.

Example:

```text
Other strong choices

Highest quality
OpenHands × Qwen

Most reliable
mini-SWE × Qwen

Most efficient
smolagents × GPT-OSS
```

---

# 20. Comparison visualization

## Primary: horizontal metric bars

Prefer easy visual comparison.

```text
                    mini-SWE × Qwen     smolagents × Qwen

Correctness               94 █████████      88 ████████
Reliability               93 █████████      96 █████████
Execution efficiency      82 ████████       95 █████████
Token efficiency          89 █████████      94 █████████
Resource efficiency       90 █████████      91 █████████
```

Radar charts may exist as an optional visualization but should not be the primary comparison mechanism.

---

# 21. Pareto frontier

Preserve the existing Pareto analysis.

Show:

- correctness vs tokens
- correctness vs duration

Example:

```text
Correctness
100│
   │                 ● A
 90│           ● B
   │
 80│    ● C
   └──────────────────────────
                tokens →
```

Highlight frontier stacks.

Add plain-language interpretation.

Example:

> Stack B uses 43% fewer tokens than Stack A while giving up only 2 percentage points of correctness.

This converts analysis into a useful decision.

---

# 22. Reliability and statistical honesty

Keep caveats next to the recommendation.

Never hide them in a footer.

If fewer than three repetitions complete:

```text
⚠ Provisional recommendation

Only 2 repetitions completed successfully.
The ranking is useful directionally but is not yet a strong reliability signal.
```

Show:

- completed repetitions
- success rate
- mean/median
- variance
- timeout rate
- empty-patch rate
- harness crash rate
- provider failure rate

Do not claim significance from a tiny sample.

---

# 23. Insufficient evaluation signal

Preserve this as a first-class result.

```text
No winner can be declared

The selected tasks do not provide enough deterministic evidence
to distinguish these Agent Stacks reliably.

Why

No usable tests or behavioral checks were available.

Recommended next step

Choose another historical task or add a deterministic evaluation command.
```

The system should prefer "we don't know" over a misleading recommendation.

---

# 24. Protected paths should be task-aware

Do not permanently treat all tests, CI files, or Makefiles as prohibited.

Some legitimate tasks require modifying them.

Represent the policy per task.

Example:

```json
{
  "protected_paths": [
    "tests/**",
    ".github/**"
  ],
  "allowed_paths": []
}
```

For historical replay where tests act as hidden evaluation, protect them.

For tasks such as:

```text
Add missing authentication tests
```

or:

```text
Fix the CI workflow
```

the relevant paths must be allowed.

Show this only in advanced task/evaluation details unless it affects the user.

---

# 25. Cost terminology

Use:

> **Inference Cost**

rather than a generic "Cost."

Track independently:

- API cost
- input tokens
- output tokens
- cached tokens
- wall-clock time
- CPU time
- peak memory
- GPU usage when local inference is added later

A free API model can have:

```text
API cost: $0.00
```

without implying that its latency or resource consumption is zero.

---

# 26. Future recommendation dataset

Begin recording task/repository characteristics now.

Useful metadata:

```text
Repository
──────────
language
framework
repository size
lines of code
test count

Task
────
task type
historical patch size
files touched
description length
dependency changes
hidden tests available
evaluation confidence

Stack
─────
harness
model
configuration

Outcome
───────
correctness
reliability
tokens
duration
resources
failure categories
```

Long-term this becomes:

```text
Repository characteristics
+
Task characteristics
+
Agent Stack
        ↓
Observed outcome
```

This dataset can later power the meta-recommendation system.

---

# 27. Accessibility

Because the plan removes MUI, custom primitives must deliberately restore accessibility.

Required:

- visible focus states
- complete keyboard navigation
- semantic controls
- labelled inputs
- ARIA where necessary
- dialog focus trapping
- escape-to-close
- screen-reader status announcements
- sufficient contrast
- reduced-motion support
- skip-scene option

The entire workflow must work if the Three.js scene is unavailable or disabled.

---

# 28. Reduced-motion behavior

When `prefers-reduced-motion` is enabled:

- disable camera travel
- disable ambient floating motion
- disable lane movement animation
- avoid animated result reveals
- use immediate state transitions
- retain static scene elements if useful

Do not simply slow animations down.

Remove unnecessary movement.

---

# 29. Responsive behavior

The product is desktop-first because live code inspection and benchmarking are inherently information-dense.

Still support smaller screens gracefully.

## Desktop

Full scene + content layout.

## Tablet

Reduce scene prominence.

Use stacked content where needed.

## Mobile

Prioritize:

- repository state
- task selection
- stack selection
- experiment progress
- recommendation

Hide or greatly simplify:

- complex 3D scene
- multi-column telemetry
- large analytical charts

Never make mobile users manipulate a 3D camera.

---

# 30. Existing backend capabilities to reuse

Do not rebuild working capabilities.

Continue using:

- typed API client
- repository registration
- repository evaluation strategy
- commit history endpoint
- task-from-commit endpoint
- harness listing
- model listing
- explicit experiment combinations
- persisted SSE stream
- results endpoint
- run-detail endpoint

The existing SSE replay behavior is especially valuable for the live interface.

Late subscribers should still reconstruct the run timeline.

---

# 31. Backend additions required for this UI

## Agent activity

Add:

- `agent_step`
- `edit`

events.

## Model availability

Persist preflight state:

```text
available
slow
unusable
unchecked
```

Allow on-demand probe/recheck.

## Optional UX enrichment

If inexpensive, expose task-level metadata useful for cards:

- inferred task type
- patch size
- files touched
- test additions
- evaluation confidence

Do not block the UI rebuild on speculative backend enrichment.

---

# 32. Build sequence

The application must remain usable after every phase.

## Phase 1 — Telemetry + model availability

Backend first.

Implement:

- separate telemetry volume
- agent-step events
- code-edit events
- persisted preflight outcomes
- model availability states
- model probe endpoint
- tests proving telemetry never contaminates patches

Keep existing UI operational.

---

## Phase 2 — Design system

Create:

- tokens
- typography
- motion
- Button
- Field
- Select
- Panel
- Dialog
- Toast
- Chip
- Badge
- Tabs
- Progress
- Metric
- EmptyState
- Status

Port accessibility behavior intentionally.

---

## Phase 3 — Clear 2D workflow

Rebuild:

1. Repository
2. Tasks
3. Agent Stacks
4. Review

Do this before adding the 3D shell.

Exit criterion:

> A new user can complete setup without documentation and without any 3D scene.

---

## Phase 4 — Persistent 3D visual layer

Add:

- persistent R3F canvas
- stage-based camera states
- repository graph
- Agent Stack nodes
- transitions
- reduced-motion behavior
- graceful WebGL failure

The 3D layer must not change workflow semantics.

---

## Phase 5 — Live Agent Arena

Build:

- experiment progress
- run selector
- focused run
- Timeline tab
- Code tab
- Model Calls tab
- Logs tab
- execution lanes
- live scene updates
- virtualization

---

## Phase 6 — Decision-first results

Build:

- hero recommendation
- why-it-won explanation
- four recommendation categories
- metric comparison bars
- Pareto plots
- reliability details
- caveats
- provisional-result state
- insufficient-signal state

---

## Phase 7 — Cleanup

Only after all screens have moved:

- remove MUI
- remove Emotion
- update ADR
- accessibility review
- performance review
- keyboard-only test
- reduced-motion test
- responsive review
- visual polish
- documentation update

---

# 33. Testing requirements

Preserve all existing backend gates.

Add/maintain frontend and integration tests for:

## Telemetry

- telemetry files never enter the produced patch
- agent-step events preserve order
- edit events preserve order
- late SSE subscribers receive historical events
- unknown telemetry remains unknown rather than zero

## Stack selection

- explicit pairs remain explicit
- two harnesses + two models can still produce exactly two stacks
- unavailable models are disabled
- unavailable reason is visible
- slow models remain selectable with warning

## Repository

- analysis progress is visible
- unbenchmarkable state is first-class
- suggested repo changes are visible
- advanced evaluation strategy can be opened

## Tasks

- recommended commits show `why`
- commits with hidden tests are visibly preferred
- task selection persists

## Review

- run count calculation is correct
- weak evaluation signal is clearly explained
- advanced settings remain optional

## Live

- run status updates correctly
- selected run changes focused telemetry
- long event lists are bounded/virtualized
- code previews are bounded
- rate limiting is visible
- logs do not reveal secrets

## Results

- recommendation appears before detailed charts
- exact numeric scores render in DOM
- `statistically_weak` remains visible
- insufficient signal declares no winner
- Pareto points match API values
- recommendation explanation is rendered

## Accessibility

- keyboard navigation
- focus indicators
- dialogs trap focus
- escape closes dialogs
- controls have labels
- reduced motion removes camera travel
- workflow remains usable when scene fails

---

# 34. Performance budget

The 3D layer must remain subordinate to application performance.

Targets:

- UI content paints without waiting for WebGL assets
- scene remains smooth on integrated graphics where possible
- no large textures unless necessary
- no expensive post-processing by default
- event rendering is virtualized
- code/log previews are bounded
- charts render only when visible where practical
- background tabs do not waste significant rendering work

If performance degrades, reduce scene complexity before compromising UI responsiveness.

---

# 35. UX success criteria

The redesign is successful when a new user can:

1. paste a repository URL
2. understand whether it can be benchmarked
3. understand how evaluation will work
4. see which historical tasks are recommended and why
5. choose exact Agent Stacks
6. understand model availability
7. understand total benchmark runs before starting
8. understand weak evaluation signals
9. watch a selected agent's observable workflow
10. inspect live code edits
11. understand provider/model activity
12. identify the recommended stack immediately after completion
13. understand why it won
14. understand the quality/efficiency tradeoff
15. recognize when the recommendation is statistically weak
16. recognize when no reliable winner exists
17. complete the workflow without touching the 3D scene

---

# 36. Final product hierarchy

The interface should optimize for this order:

```text
CLARITY
   ↓
TRUST
   ↓
DECISION QUALITY
   ↓
LIVE VISIBILITY
   ↓
CREATIVITY / DELIGHT
```

Creativity matters, but it must support the product rather than compete with it.

The memorable experience should come from:

- watching real Agent Stacks compete
- seeing real code changes arrive
- understanding the benchmark as it happens
- receiving a clear recommendation

not from making the user learn a novel navigation system.

---

# 37. Final design statement

Build a UI that feels like a sophisticated AI engineering laboratory while behaving like an exceptionally simple developer tool.

The core visual metaphor is:

```text
YOUR REPOSITORY
       ↓
REAL CODING TASKS
       ↓
AGENT STACKS ENTER THE ARENA
       ↓
LIVE EXECUTION
       ↓
MEASURED RESULTS
       ↓
BEST STACK FOR YOUR CODEBASE
```

The 3D environment gives this sequence identity and continuity.

The 2D interface gives it clarity, accessibility, and trust.

Both should work together, but when they conflict:

> **clarity wins.**
