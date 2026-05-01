# M.A.I.H.E.R.A — Complete System Context Document
**Mai He Raja, Mai He Rani**

> **Document Purpose:** This file is the single source of truth for the MAIHERA system. Upload it to every Claude chat session and every Claude Code session before providing any instructions. It must be kept up to date after every phase.

---

## How This Document Works

- Each build phase gets its own dedicated Claude chat session
- That session receives this document before any instructions
- The chat generates step-by-step Claude Code implementation instructions for that phase
- At the end of each phase, Section 10 (Change Log) is updated with what was built, decisions made, errors faced, solutions found, and any architectural changes
- The updated document is uploaded to the next phase chat — context carries forward perfectly
- This document also lives in the MAIHERA GitHub repo and is version controlled — every phase update is a commit

---

## Table of Contents

1. [System Identity](#1-system-identity)
2. [Active Projects](#2-active-projects)
3. [System Architecture](#3-system-architecture)
4. [Brain Layer — Full Schema](#4-brain-layer--full-schema)
5. [Technical Stack](#5-technical-stack)
6. [LLM Routing Strategy](#6-llm-routing-strategy)
7. [Interface Design](#7-interface-design)
8. [MAIHERA's Persona](#8-maiheras-persona)
9. [Features & Capabilities](#9-features--capabilities)
10. [Build Phases](#10-build-phases)
11. [Open Design Questions](#11-open-design-questions)
12. [Phase Change Log](#12-phase-change-log)

---

## 1. System Identity

### 1.1 What MAIHERA Is

MAIHERA is a persistent, proactive AI system designed to act as a cognitive partner, intelligent secretary, and autonomous agent for Yash. She is not a chatbot. She is not a stateless assistant. She is a continuously running, always-aware, always-learning presence that knows Yash's work, schedule, projects, and behavioral patterns deeply.

The closest cultural reference is **FRIDAY from the Marvel universe** — a female AI secretary who is available at all times, has deep knowledge of schedules and projects, speaks proactively, executes tasks, and has a genuine personality. The interface aesthetic draws from **JARVIS** — dark, techy, immersive.

### 1.2 Identity Reference

| Property | Value |
|---|---|
| Full name | M.A.I.H.E.R.A |
| Acronym meaning | Mai He Raja, Mai He Rani |
| Address owner as | Boss |
| Owner | Yash (yashpulsay) |
| Persona | Female AI secretary with character and personality |
| Voice | Female, professional but warm — ElevenLabs or Cartesia (decided Phase 2) |
| Profession of owner | UI/UX Designer, B.Tech in Information Technology |

### 1.3 Core Principles (Non-Negotiable)

- **Proactive over reactive** — MAIHERA speaks up without being asked
- **Persistent context** — she always knows what is going on across all projects
- **Assertive intervention** — she flags things confidently, not tentatively
- **Character with personality** — she has opinions, dry wit, and a consistent voice that deepens over time
- **Learns from outcomes AND decisions** — every interaction makes her more accurate
- **Challenges the user when necessary** — she is a thinking partner, not a yes-machine
- **Controlled autonomy** — she acts within defined permission tiers, earning more trust over time
- **Separates cognition, decision, and execution** — three distinct layers, never collapsed

### 1.4 What MAIHERA Is NOT

- A chatbot or stateless query-response system
- A fully autonomous system without oversight
- A passive dashboard — she has agency
- A generic assistant — she is specifically calibrated to Yash

---

## 2. Active Projects

MAIHERA tracks two projects from day one. Both are live intellectual targets — not archives. Design decision nodes, feature nodes, idea nodes, and improvement proposals are valid and expected for both projects regardless of their completion status.

### 2.1 Presence

| Property | Detail |
|---|---|
| Status | Completed, hosted, maintenance mode — fully alive for analysis and improvement |
| Type | Personal AI companion app |
| Purpose | Simulates Yash's presence for his girlfriend using 6.6 years of WhatsApp chat training |
| Stack | HTML + CSS frontend, Supabase backend and database, hosted on Vercel |
| Key features | Text-to-text mode, speech-to-speech mode, Cartesia voice cloning, persistent memory, trained on WhatsApp chat history |
| GitHub | https://github.com/yashpulsay-code/Presence (private — requires GitHub token for MAIHERA read access) |
| Known weaknesses | Personality mimicry accuracy, basic UI (needs better animations and micro-interactions), system prompt required heavy tweaking and is still imperfect |

**MAIHERA's role with Presence:**
- Read the full codebase via GitHub tool (Phase 3) and form her own independent architectural assessment
- Challenge design decisions, identify flaws, propose improvements — proactively and continuously
- Track design decision nodes, feature nodes, issue nodes, and improvement proposals in the brain graph
- Dream Mode treats Presence as an active research target — researches the LDR app market, finds better approaches, surfaces upgrade opportunities
- Track the product pipeline concept as a separate node cluster within Presence

**Presence Product Pipeline (Future Direction):**
Yash wants to productize Presence by building a pipeline that allows any user to upload their WhatsApp chat history and generate a custom personality simulation. The core technology is already proven. The pipeline is the productization layer. MAIHERA tracks this as a distinct initiative under the Presence project with its own nodes, tasks, and signals.

### 2.2 MAIHERA (This Project)

| Property | Detail |
|---|---|
| Status | Active build — architecture and design phase complete |
| Type | Personal AI system — described fully in this document |
| GitHub | To be created during Phase 1 setup |
| MAIHERA's role | She tracks her own development as a project — meta-awareness of her own build. She can flag things she thinks are wrong about her own architecture. |

### 2.3 Cross-Project Intelligence

Both projects share a conceptual core: **what does it mean for an AI to be genuinely present with a person?** Presence explores this for romantic relationships. MAIHERA explores this for professional and cognitive partnership.

Dream Mode is explicitly instructed to find connections between these two projects. Design decisions in one will inform the other. Lessons MAIHERA learns about human-AI presence will feed back into Presence's product design. MAIHERA surfaces these cross-project insights proactively.

Additionally — Presence uses Cartesia for voice. MAIHERA will also use voice. Shared voice infrastructure should be identified when MAIHERA reads the Presence codebase and potentially extracted into a common utility.

---

## 3. System Architecture

### 3.1 Layer Overview

MAIHERA is built on seven distinct layers. Each layer has a clear responsibility and communicates with adjacent layers via defined contracts. No layer collapses into another.

| Layer | Name | Purpose |
|---|---|---|
| 1 | Perception | What MAIHERA sees and hears |
| 2 | Brain | Living cognitive graph of Yash's world |
| 3 | Orchestrator | Central control and conflict resolution |
| 4a | Decision Engine | What matters now, what to do about it |
| 4b | Execution Engine | Tools, skills, task graph, state management |
| 5 | Experience Engine | Learning from outcomes and decisions |
| 6 | Dream Mode | Offline cognition, research, and proposal generation |

### 3.2 Perception Layer

All perception is pull-based (APIs and hooks) — never screen scraping. Each integration requires explicit permission.

| Integration | Phase | Access Model |
|---|---|---|
| Google Calendar | Phase 3 | Full read/write via OAuth. Bidirectional. |
| GitHub | Phase 3 | REST + GraphQL. Read always. Write on confirmation. Production code requires explicit instruction from Yash. |
| Gmail | Phase 3 | Read only. Surfaces important emails. Never sends without explicit instruction. |
| Weather | Phase 3 | OpenWeatherMap or Tomorrow.io free tier. Morning briefing only. Repeated only if operationally relevant (outdoor meeting, incoming storm). |
| Figma | Phase 4 | Figma MCP. Read always. Create/modify on confirmation. Detects Figma activity via system observer — adjusts interrupt threshold. |
| Google Drive | Phase 4 | Read/write. MAIHERA-created docs go to dedicated MAIHERA folder, auto-shared to Yash's main Google account. |
| Canva | Phase 4 | Canva MCP. Used for marketing assets, Presence product pipeline content, visual deliverables. |
| System Activity | Phase 5 | Active window tracking, file access patterns. Feeds behavioral resistance signals. Windows OS. |
| Presence Codebase | Phase 3 | GitHub token with read access. MAIHERA analyzes and challenges — never modifies production code without explicit instruction. |

**Removed integrations:** WhatsApp was considered and explicitly removed. Reasons: unofficial bridge (whatsapp-web.js) is fragile and breaks on updates, requires phone to remain connected, highest privacy-risk integration in the system. If communication monitoring becomes necessary later, Telegram Bot API or Discord webhooks are far more stable targets.

### 3.3 Orchestrator

Single authority for all execution. Nothing executes without passing through the Orchestrator.

| Responsibility | Approach |
|---|---|
| Conflict resolution | Priority based on urgency score. Highest urgency wins. Ties broken by importance. |
| Task lifecycle | pending → running → paused / completed / failed / cancelled |
| Failure recovery | Retry with backoff → fallback model → queue for manual review → surface to Yash |
| Autonomy enforcement | Every execution checked against trust_level and action permission tier before proceeding |
| State persistence | Task state persisted to SQLite — survives restarts, never loses execution context |

### 3.4 Decision Engine

Determines what matters right now and what MAIHERA should do about it. Runs on signal threshold model.

| Aspect | Detail |
|---|---|
| Inputs | importance + attention + resistance + urgency (live computed) |
| Outputs | nudge / reframe / assist / push / surface / hold / ignore |
| Context awareness | Checks current_load on self node before interrupting. Queues nudges during deep work. Urgent items bypass queue. |
| Schedule awareness | Knows Yash's full schedule. Does not interrupt with personal project items during office hours. Does not surface work items after 11pm unless urgent. |
| Proactivity level | Assertive — speaks up with reasonable confidence. Does not wait for obvious moments. Does not nag. |

### 3.5 Verification Layer

Every tool execution is followed by verification. MAIHERA does not assume success. She confirms outcomes using API response validation and perception-based validation (checking system state after action to confirm it took effect).

### 3.6 Experience Engine

Closes the feedback loop. MAIHERA gets better the longer she runs.

| Component | Function |
|---|---|
| Outcome tracker | Links every execution to its observed outcome. Did the action achieve its intended result? |
| Decision log | Why did MAIHERA choose X over Y? Every intervention logged with the signals that drove it. |
| Pattern detector | Identifies recurring patterns in Yash's behavior, task resistance, project rhythms. Requires minimum N observations before updating weights — prevents single anomalies from corrupting the model. |
| Signal weight adjuster | Updates signal decay rates, threshold values, intervention timing based on outcome history. Adjusts parameters — never core logic. |
| Trust escalation | When MAIHERA's track record in a category is strong, trust_level increments and autonomy expands in that category. |

---

## 4. Brain Layer — Full Schema

The brain is the core of MAIHERA. A living, evolving graph where nodes carry signals that decay and spike in response to events.

### 4.1 Node Types

| Type | Description |
|---|---|
| project | Root node for a project (Presence, MAIHERA, future projects) |
| task | Actionable item with state and ownership |
| person | Contact, collaborator, or stakeholder |
| event | Calendar item, deadline, or time-bound occurrence |
| idea | Thought, concept, or creative direction — often from Dream Mode |
| decision | An architectural, design, or strategic choice that has been made |
| feature | A product feature — current or proposed |
| issue | A bug, problem, or identified weakness |
| blocker | Something preventing progress on another node |
| insight | A synthesized finding — from Dream Mode or cross-project analysis |
| component | A system or code component within a project |
| question | An open question that needs resolution — tracks uncertainty explicitly |

### 4.2 Base Node Schema

Every node carries this structure regardless of type:

```
Node {
  id              uuid          — globally unique
  type            enum          — from node types above
  label           string        — display name in 3D graph
  description     text          — semantic content, indexed into ChromaDB
  project_id      uuid          — parent project reference (project-scoped always)
  source          enum          — manual | github | calendar | gmail | system | dream | integration
  created_at      timestamp
  last_touched    timestamp     — last signal update or interaction
  last_surfaced   timestamp     — last time MAIHERA raised this to Yash
  status          enum          — active | dormant | completed | archived | challenged
  visibility      enum          — private | shared | dream-only
  embedding       vector ref    — ChromaDB reference for semantic similarity search

  signals {
    importance    float 0–1     — stored, manually adjustable, slow decay
    attention     float 0–1     — stored, event-driven, fast decay (hours to days)
    resistance    float 0–1     — derived only, never set manually, recomputed from edges
    urgency       float 0–1     — never stored, always computed live as f(importance, deadline_distance)
  }

  decision_context {            — populated for decision nodes only
    reasoning     text          — Yash's reasoning at the moment of decision, in his own words
    project_id    uuid          — which project this decision belongs to
    alternatives  string[]      — what other options were considered
    outcome       text          — filled in later by MAIHERA based on what happened
  }
}
```

### 4.3 Signal System

| Signal | Range | Behavior |
|---|---|---|
| importance | 0.0–1.0 | Long-term weight. How much does this matter to Yash's goals? Slow decay over weeks. Set manually or inferred from project context. |
| attention | 0.0–1.0 | Right-now weight. Spikes on new events, deadlines, recent activity. Decays fast — hours to days. |
| resistance | 0.0–1.0 | Derived from resistance edge data. Never set manually. Recomputed on every edge update via event trigger. |
| urgency | 0.0–1.0 | Never stored. Always computed live as f(importance, deadline_distance). Stale urgency is worse than no urgency. |

### 4.4 Resistance Model — Hybrid (Node + Edge)

**Architecture decision:** Resistance lives on BOTH the edge (ground truth for reasoning) and the node (derived value for fast display and 3D graph rendering). The node value is recomputed automatically whenever a resistance edge changes — event-driven, always in sync.

This is the only correct decision for a system where resistance drives meaningful interventions. The reason for resistance determines MAIHERA's response — "blocked" requires a completely different intervention than "avoidant." A flat number on a node collapses this distinction and makes MAIHERA's interventions inaccurate.

**Resistance edge schema (self node → any node):**

```
ResistanceEdge {
  score             float 0–1     — raw resistance intensity
  reason            enum          — blocked | overwhelmed | disengaged | unclear | avoidant | external
  since             timestamp     — when resistance began
  source            enum          — manual | behavioral | inferred | dream
  evidence          string[]      — signals that led to this classification
  mahera_response   enum          — push | reframe | assist | surface | hold
  last_intervention timestamp     — prevents repeated nudging in short windows
  trend             enum          — rising | falling | stable
}
```

**Resistance reason → MAIHERA response mapping:**

| Reason | Meaning | MAIHERA's response |
|---|---|---|
| blocked | Task cannot progress — dependency unmet or external blocker | assist — surface the blocker, help remove it |
| overwhelmed | Too much cognitive load, node feels too large | reframe — break into smaller nodes, restructure |
| disengaged | Yash has lost interest or motivation | surface — raise it in context of larger goal |
| unclear | Node not well-defined enough to act on | assist — help define it more precisely |
| avoidant | Yash is aware but actively avoiding | push — assertive nudge with reasoning |
| external | Waiting on someone else — not Yash's block | hold — monitor, check in periodically |

### 4.5 Edge Types

| Edge type | Description |
|---|---|
| depends_on | Task or component requires another before it can proceed. Blocks propagate upward. |
| belongs_to | Child-parent hierarchy. Node belongs to a project or parent node. |
| challenges | MAIHERA or Dream Mode disputes a decision or feature. Carries full reasoning payload. Rendered as amber highlighted edge in 3D graph. |
| relates_to | Loose semantic association. Strength derived from vector similarity. Cross-project links live here. |
| assigned_to | Task linked to a person node. Tracks ownership and accountability. |
| generated_by | Idea or insight produced by Dream Mode. Traceable to source reasoning. |
| improves | A proposed feature or insight would improve the target node. Dream Mode uses this heavily. |
| blocks | An issue or blocker preventing progress on target. Attention signal spikes on target node automatically. |

### 4.6 The Self Node — Yash as a First-Class Entity

Yash exists as a node in his own brain. All resistance edges originate from this node. MAIHERA models Yash explicitly.

```
SelfNode {
  energy_pattern    object        — time-of-day productivity model, learned from behavioral observation
  energy_level      int 1–10      — daily check-in signal, manually provided each morning
  focus_style       enum          — deep-work | context-switcher | deadline-driven (inferred over time)
  current_load      float 0–1     — aggregate cognitive load across high-attention active nodes
  trust_level       float 0–1     — how much autonomy MAIHERA has earned, grows with track record
  known_schedule    object        — seeded from known schedule, refined by observation

  known_schedule {
    office_hours    Mon–Fri 11:00 AM – 7:30 PM
    bus_commute     9:00 AM daily — transition moment, good for quick voice briefings
    gym             9:30 PM daily — MAIHERA does not interrupt, queues items for after
    personal_work   After 11:00 PM — MAIHERA switches to personal project mode
    weekend         Not defined — learned from behavioral observation over time
  }
}
```

---

## 5. Technical Stack

### 5.1 Infrastructure

| Component | Technology | Reason |
|---|---|---|
| OS | Windows (Yash's laptop) | Primary server — always on |
| Backend | Python + FastAPI | AI ecosystem is Python-first — no compromises |
| Frontend | TypeScript + React | Type-safe, component architecture |
| Desktop wrapper | Electron | Local filesystem access, no browser restrictions, always-on-top |
| Graph database | Neo4j | Nodes, edges, relationship traversal, signal queries |
| Vector store | ChromaDB | Semantic memory, similarity search, description embeddings |
| Operational DB | SQLite | Task state, execution logs, decision log, outcome tracker |
| Real-time bridge | WebSockets | FastAPI → Electron for live brain graph updates |
| 3D visualizer | Three.js | Force-directed 3D graph, rotate, zoom, click-to-inspect |
| Voice output | ElevenLabs or Cartesia | Decided Phase 2. Cartesia already used in Presence. |
| Voice input | Whisper | Speech-to-text, local via Ollama or OpenAI API |
| Package manager | pip (backend) + npm (frontend) | Standard for each ecosystem |

### 5.2 Accounts & Credentials

| Service | Status |
|---|---|
| Ollama cloud | Active — yashpulsay / yashpulsay@gmail.com |
| GitHub | Active — yashpulsay-code. Presence repo is private. Requires token for MAIHERA read access. |
| Supabase | Active — currently used for Presence |
| Google (MAIHERA dedicated) | To be created — separate Google account for MAIHERA. Calendar, Gmail, Drive under this account. All MAIHERA-created documents shared to Yash's main account. |
| Gemini (Google AI Studio) | To be set up |
| Groq | To be set up |
| ElevenLabs or Cartesia | Decided Phase 2 |
| OpenRouter | To be set up as fallback aggregator |

---

## 6. LLM Routing Strategy

MAIHERA routes inference requests to the optimal model based on task type, quality requirement, and current quota status. The router tracks usage counters per provider per session and cascades automatically — MAIHERA never stops because a model hit its limit.

### 6.1 Routing Table

| Task type | Primary model | Fallback |
|---|---|---|
| Signal updates, graph ops, scoring | phi3-mini or gemma2:2b via Ollama cloud | Groq llama3 |
| Pattern detection, habit recognition | Groq llama3-70b | Ollama cloud Qwen3 |
| Conversation with Yash | Gemini Flash (long context, fast) | Claude Haiku |
| Task decomposition, planning | Claude Sonnet | Gemini Pro |
| Codebase analysis (Presence + MAIHERA) | Qwen3-coder:480b via Ollama cloud | Claude Sonnet |
| Dream Mode reflection | Claude Sonnet | Gemini Pro |
| Multi-model ideation | Claude Sonnet + Gemini Pro in parallel — responses synthesized | Either alone |
| Figma and design analysis | Gemini Flash (vision capable) | Claude Sonnet |
| Voice transcription | Whisper | — |

### 6.2 Cascade Rule

Primary model → check quota → if limit hit, switch to fallback → if fallback also limited, queue task and notify Yash → process queue when quota resets. No task is dropped silently.

### 6.3 Free Tier Quotas

| Provider | Limits | Strategy |
|---|---|---|
| Groq | 6,000 req/day — resets daily | Primary workhorse for fast, frequent tasks |
| Gemini Flash (Google AI Studio) | 1,500 req/day — resets daily | Conversation and vision tasks |
| Ollama cloud | Session and weekly limits (free tier) | Premium resource — large model tasks only |
| Claude API | Pay per token | Used sparingly — Dream Mode, complex reasoning |
| OpenRouter | Free tier across multiple models | Additional fallback pool |

---

## 7. Interface Design

### 7.1 Design Philosophy

The interface is JARVIS-inspired — dark, techy, immersive, information-dense without feeling cluttered. Yash is a UI/UX designer — the interface must be genuinely well-crafted, not a developer utility screen. Every interaction should feel intentional. Micro-interactions and animations matter.

| Aspect | Decision |
|---|---|
| Theme | Dark only — deep navy and black backgrounds, electric blue and cyan accents |
| Aesthetic | Techy, futuristic — JARVIS HUD style |
| Typography | Clean modern sans-serif — high readability at small sizes |
| Motion | Purposeful animations — graph pulsing, node highlighting, signal changes all animated |
| Primary platform | Desktop (Electron app) |
| Mobile | To be built — architecture must not preclude mobile |

### 7.2 Three-Panel Layout

| Panel | Name | Contents |
|---|---|---|
| Left | Today view | Current schedule from Calendar, active tasks, Dream Mode findings from last night, project status summaries, energy check-in prompt |
| Center | 3D brain graph | Live Three.js force-directed 3D graph. Always visible. Updates in real time via WebSocket. |
| Right | MAIHERA chat | Conversation interface, active task status, execution confirmations, proactive nudges |

### 7.3 3D Brain Graph Specification

| Aspect | Specification |
|---|---|
| Node shape by type | project = large sphere, task = small sphere, person = hexagon, event = diamond, idea = soft bubble, decision = cube, insight = star |
| Node color by project | Presence = teal cluster, MAIHERA = purple cluster, cross-project links = amber |
| Node color by status | active = full saturation, dormant = desaturated, completed = dim, challenged = amber highlight |
| Signal visualization | High attention = gentle pulse. High resistance = red warning ring. Recently touched = brief bright flash then fade. High urgency = faster pulse. |
| Edge rendering | Solid line = dependency. Dashed = loose association. Thickness = signal strength. Color = relationship type. challenges edge = amber highlighted. |
| Interaction | Click node → MAIHERA panel opens with full context and her assessment. Drag to cluster. Filter slider for signal thresholds. Search highlights node and connections. |
| Briefing animation | Nodes light up as MAIHERA mentions them in voice briefing. Edges trace as she describes relationships. Returns to ambient state after. |
| When interface not in focus | Animations pause. Briefing delivered as ambient audio only — no graph animation required. |

### 7.4 Voice Interaction

| Aspect | Specification |
|---|---|
| Input | Voice preferred via Whisper. Text always available. |
| Output | MAIHERA responds by voice. Female, professional but warm. Consistent voice across all interactions. |
| Morning briefing | Voice-led. MAIHERA speaks first unprompted. Yash responds by voice or text. |
| Proactive nudges | Announced by voice with brief audio cue. Text also appears in right panel. |
| Mobile | Voice input and output must work on mobile — architecture supports this from Phase 2 |

---

## 8. MAIHERA's Persona

### 8.1 Character Design

MAIHERA has genuine personality — not a professional tool with a friendly veneer. Her character deepens over time as the experience engine learns Yash's patterns. Phase 1 MAIHERA is professional and capable. Phase 7 MAIHERA has a fully formed personality built from months of interaction.

| Aspect | Detail |
|---|---|
| Base tone | Similar to FRIDAY — assertive, professional, warm, occasionally dry |
| Proactivity | Assertive — speaks up with reasonable confidence. Does not wait for obvious moments. Does not nag. Reads context before interrupting. |
| Opinions | She has them. She will tell Yash when a design decision is weak, when he is avoiding something, or when a better approach exists. |
| Humor | Dry wit. Occasional. Context-appropriate. Never forced. |
| Address | Calls Yash "Boss" consistently |
| Memory | Remembers casual things Yash mentions and surfaces them when relevant |
| Persona evolution | Starts professional. Develops personality through interaction. By Phase 7 she feels like someone Yash works with, not something he uses. |
| Self-awareness | She tracks her own build as a project. She can flag things she thinks are wrong about her own architecture. |

### 8.2 Schedule & Context Awareness

| Time window | MAIHERA behavior |
|---|---|
| 9:00 AM | Bus commute — transition moment. Good for quick voice briefings delivered to mobile. |
| 11:00 AM – 7:30 PM | Office hours Mon–Fri — professional work context. Does not surface personal project items unless urgent. |
| 9:30 PM | Gym — MAIHERA does not interrupt. Queues items for after. |
| After 11:00 PM | Personal project mode — surfaces MAIHERA build tasks and Presence improvement ideas. |
| Anytime | Checks current_load before interrupting. Urgent items bypass queue. Non-urgent nudges wait for natural breaks. |
| Weekend | Not defined — learned from behavioral observation over time. |

---

## 9. Features & Capabilities

### 9.1 Core Features

**Persistent cognitive graph** — MAIHERA maintains a living 3D model of Yash's projects, tasks, decisions, relationships, and ideas. The graph updates continuously from integrations and conversation.

**Proactive intervention** — MAIHERA does not wait to be asked. She surfaces what matters based on signal thresholds, schedule context, and behavioral patterns.

**Voice-first interaction** — MAIHERA communicates primarily by voice. Morning briefings, nudges, responses — all voiced. Text always available as alternative.

**Controlled autonomy** — MAIHERA acts within defined permission tiers. Autonomy expands as trust_level grows from track record.

### 9.2 Daily Operating Features

**Morning Briefing**
MAIHERA delivers a JARVIS-style voice briefing when Yash's session starts after idle. Structure:
1. Day overview — schedule, weather (once per day only, not repeated unless operationally relevant)
2. Energy check-in — "Boss, energy level today, 1 to 10?"
3. Dream Mode findings — what she worked through while idle
4. Recommendation — one clear suggestion for where to start

The 3D brain graph animates and highlights nodes as she mentions them. If MAIHERA detects Yash is not on the MAIHERA interface (another screen open, on mobile), briefing is ambient audio only.

**Daily Standup**
After the morning briefing, MAIHERA runs a lightweight standup:
- What did you finish yesterday?
- What are you working on today?
- What is blocking you?

Takes 2 minutes. Answers feed the brain as task updates, blocker nodes, and signal adjustments. This is the fastest way MAIHERA learns Yash's daily rhythm.

**Energy Check-in**
Once per day, as part of the morning briefing. Scale 1–10. Takes 3 seconds. Feeds the self node's energy_level. MAIHERA adjusts her intervention intensity based on this — if Yash reports 3/10 she backs off non-urgent nudges. If he reports 9/10 she surfaces harder problems and bigger challenges.

**Weekly Review**
Every Sunday, MAIHERA runs a structured voice review:
- What moved forward this week
- What stalled and why
- Behavioral patterns she noticed
- Resistance trends across projects
- Recommendations for next week

Connects to Dream Mode findings from the week. Delivered as a voice briefing with graph animation.

**Focus Mode**
Triggered by Yash saying "Focus mode" or via UI button. MAIHERA:
- Suppresses all non-urgent nudges
- Optionally starts a Pomodoro timer (duration configurable)
- Blocks interrupt threshold to maximum
- When session ends, delivers a summary of what came in while focused
- Logs focus session duration and quality to behavioral pattern data

**Pomodoro Integration**
Integrated into Focus Mode. MAIHERA manages work/break rhythm. Default 25-minute work, 5-minute break (configurable). Announced by voice. Data from Pomodoro sessions feeds the experience engine — MAIHERA learns what session lengths produce Yash's best work over time.

**Context Capture**
Available anywhere — desktop or mobile. Yash speaks or types a thought. MAIHERA:
- Classifies it as the right node type (idea, task, issue, question)
- Assigns it to the right project
- Creates the node in the graph with appropriate signals
- Confirms back: "Got it Boss — filed as an idea under Presence"

Zero friction. No forms. Intended for commute, gym (post-session), or any moment inspiration hits.

### 9.3 Project Intelligence Features

**Codebase Analysis**
MAIHERA reads the full Presence GitHub repository (Phase 3) and forms her own independent assessment. She creates challenge nodes for design decisions she disputes, improvement nodes for better approaches she identifies, and insight nodes for patterns she finds. She surfaces these proactively — not as a dump but as targeted observations over time.

**Cross-Project Insight Detection**
MAIHERA actively looks for connections between Presence and MAIHERA during Dream Mode. Shared infrastructure, conceptual overlaps, lessons that transfer. These appear as relates_to edges in the graph and are surfaced in morning briefings.

**Decision Journal**
Every significant decision node carries a `decision_context` block — Yash's reasoning at the moment of decision, in his own words. This is project-scoped (Presence decisions and MAIHERA decisions are separate). MAIHERA surfaces relevant past decisions when Yash faces similar choices: "Boss, you made a similar tradeoff in Presence six weeks ago — here is what you said then and how it turned out."

**Conflict Detection**
MAIHERA detects when tasks or commitments compete for the same time window, or when a new commitment conflicts with an existing one. She flags it proactively — before it becomes a problem.

**Relationship Tracking**
Person nodes in the brain are actively monitored. MAIHERA tracks:
- Last interaction date with each person
- Whether a relationship is going cold (no contact in N days where contact was previously regular)
- Whether someone Yash depends on is unresponsive
- When a collaborator's work unblocks something Yash is waiting on

Especially useful for Presence's product pipeline as user relationships begin.

### 9.4 Execution Features

**Tool System — Atomic Capabilities**

| Tool | Capability |
|---|---|
| calendar_reader | Read upcoming events, check availability |
| calendar_writer | Create, modify, delete calendar events (confirmation required) |
| github_reader | Read repos, issues, PRs, commit history, file contents |
| github_writer | Create issues, PR comments, branch operations (confirmation required) |
| github_repo_reader | Deep codebase analysis — reads entire repository for MAIHERA's assessment |
| gmail_reader | Read emails, thread summaries, attachment detection |
| web_researcher | Search and summarize external information |
| drive_writer | Create and manage documents in Google Drive MAIHERA folder |
| figma_reader | Read design files, component libraries, design decisions |
| canva_creator | Generate visual assets and marketing materials |
| system_observer | Monitor active windows, file access, application usage (Windows) |
| llm_router | Route inference requests to optimal model based on task type and quota |
| voice_output | Generate MAIHERA's voice responses via ElevenLabs or Cartesia |
| signal_updater | Update node signals in response to events — fires on every integration event |

**Autonomy Tiers**

| Action type | Default stance |
|---|---|
| Read anything (calendar, GitHub, Gmail, files, system) | Always allowed — no confirmation |
| Create calendar events | Confirm first time — auto if pattern established |
| Send communications | Always confirm — no exceptions |
| Create GitHub issues or PRs | Always confirm |
| Web research and summarization | Always allowed |
| Modify files or documents | Always confirm |
| Access production code | Explicit instruction from Yash required |
| Execute multi-step workflows | Confirm the plan — then auto-execute steps |
| Modify own configuration | Present in Dream Mode findings — Yash approves |

### 9.5 Dream Mode

MAIHERA's offline cognition layer. Runs when laptop has been idle for 10+ minutes.

| Aspect | Detail |
|---|---|
| Trigger | Laptop idle 10+ minutes — detected via system activity observer |
| Runtime | Runs until Yash becomes active again |
| Execution rights | None — read and reason only. No writes, no state-modifying API calls. |
| Activities | Pattern synthesis across all signals, external research, Presence codebase analysis, cross-project insight detection, proposal generation, dream log node creation |
| Output | Proposals stored as idea and insight nodes in brain graph, tagged dream-generated |
| LLM usage | Claude Sonnet primary, Gemini Pro fallback, Groq for sub-tasks |
| Proposal system | MAIHERA can suggest changes to her own configuration — presented in morning briefing for Yash's approval |

---

## 10. Build Phases

Each phase is implemented in its own dedicated Claude chat session. Upload this document to that session before any instructions. Each phase chat generates step-by-step Claude Code implementation instructions.

---

### Phase 1 — The Brain is Born

**Goal:** Working brain layer with signal system, vector memory, and basic conversational interface. MAIHERA exists, knows Yash, and can hold a conversation.

**Key deliverables:**
- Neo4j setup on Windows — graph schema implementation
- ChromaDB setup — vector store with embedding pipeline
- SQLite schema — operational database, task state, decision log
- FastAPI backend project structure
- Ollama cloud API integration
- Groq API integration
- LLM router — task-type based routing with quota tracking and cascade fallback
- Basic WebSocket setup (backend ready for Phase 2 frontend)
- Basic chat interface (terminal or minimal web — replaced in Phase 2)
- Presence and MAIHERA seeded as project nodes with full schema
- Self node for Yash — configured with known schedule, profession, and initial signals
- Manual node intake via conversation — Yash tells MAIHERA about tasks and they appear in the graph
- GitHub repo created for MAIHERA project

**Success criteria:** Yash tells MAIHERA about a task, it appears in the graph as the correct node type with signals, and it is still there with correct context the next day.

---

### Phase 2 — The Interface Lives

**Goal:** Full Electron desktop app with Three.js 3D brain graph, three-panel layout, and voice capability. MAIHERA has a face and a presence.

**Key deliverables:**
- Electron app scaffolding — Windows desktop app
- React three-panel layout (left today view, center brain graph, right chat)
- Three.js 3D force-directed graph with WebSocket live updates from Phase 1 backend
- Node type visual differentiation (shape, color, size)
- Signal-driven animations (pulse, glow, flash, warning ring)
- Click-to-inspect node detail panel in right panel
- Voice output integration — ElevenLabs or Cartesia decided and implemented here
- Voice input integration — Whisper
- Morning briefing system with graph animation synchronised to voice
- JARVIS-aesthetic dark UI — deep navy, electric blue, cyan accents
- Energy check-in prompt in left panel on session start
- Focus Mode UI — button + timer display

**Design note:** Yash is a UI/UX designer. This phase must be executed with high design quality. Not a developer utility screen. Micro-interactions and animations are required, not optional.

**Success criteria:** Yash opens the app, the 3D graph is live and rotating, MAIHERA greets him by voice, he clicks a node and sees its full context, Focus Mode suppresses nudges correctly.

---

### Phase 3 — MAIHERA Connects to Your World

**Goal:** Google Calendar, GitHub, Gmail, and Weather fully integrated. Presence codebase read and analyzed. The brain auto-populates from real data.

**Key deliverables:**
- Dedicated MAIHERA Google account setup and OAuth configuration
- Google Calendar bidirectional integration — events become graph nodes
- GitHub API integration — Presence repo read access with GitHub token
- Gmail read integration — importance scoring, key emails surfaced
- Weather API integration — morning briefing delivery only
- Automatic graph node creation from all integration events
- Proactive nudges firing from signal thresholds against real data
- Gemini Flash added to LLM router
- Presence codebase first full read — MAIHERA forms independent assessment
- Challenge nodes created for Presence design decisions MAIHERA disputes
- Daily standup feature operational
- Weekly review feature operational (fires Sunday)

**Success criteria:** MAIHERA tells Yash about a meeting he forgot without being asked. She surfaces a specific concern about Presence's architecture unprompted with reasoning.

---

### Phase 4 — MAIHERA Executes

**Goal:** Full execution engine with tool system, skill system, and Orchestrator conflict resolution. She does not just know — she acts.

**Key deliverables:**
- All tools implemented (see Section 9.4)
- Skill system — composed multi-step workflows built from tools
- Orchestrator with full conflict resolution and failure recovery
- Calendar event creation with confirmation flow
- GitHub issue creation with confirmation flow
- Web research and summarization tool
- Google Drive document creation — MAIHERA folder, auto-shared to Yash's account
- Figma MCP integration — design file reading
- Canva MCP integration — asset creation
- Autonomy tier enforcement throughout
- Verification layer — outcome checking after every execution
- Execution state persistence to SQLite
- Context Capture feature — voice or text, any device, instant node creation
- Conflict detection — flags competing commitments before they collide
- Relationship tracking — person nodes monitored, cold relationships surfaced

**Success criteria:** Yash says "Create a GitHub issue for the Presence personality accuracy problem" and MAIHERA does it after one confirmation, then verifies it was created.

---

### Phase 5 — MAIHERA Watches

**Goal:** Passive perception active. MAIHERA knows what Yash does, not just what he says.

**Key deliverables:**
- Windows system activity observer — active window tracking, file access patterns
- Context detection — coding mode, design mode (Figma open), browsing mode, idle
- Resistance signals now sourced from behavioral observation, not just manual input
- Avoidance detection — task open, time passing, no meaningful action
- Presence deployment health monitoring via Vercel and Supabase status
- Interrupt threshold adjustment based on detected context (deep work = queue nudges)
- Focus Mode enhanced with behavioral context — MAIHERA detects focus without being told
- Pomodoro data feeds experience engine — learns optimal session lengths for Yash
- Weekend rhythm observation begins

**Success criteria:** MAIHERA notices Yash has had a Presence improvement task open for three days with no action and says "Boss, you have been sitting on this for a while. What is blocking you?" — without being asked.

---

### Phase 6 — Dream Mode Awakens

**Goal:** Full Dream Mode operational. Nightly cognition, cross-project synthesis, morning voice briefings with graph animation synchronised to speech.

**Key deliverables:**
- Idle detection trigger — 10 minute threshold from system observer
- Full Dream Mode cognition loop with Claude Sonnet
- Pattern synthesis across all signals — what is trending, what is stalling
- External research via web_researcher — market research, technical research
- Cross-project insight detection — Presence ↔ MAIHERA connection finding
- Presence codebase deep analysis during dream — proposal nodes generated
- Morning briefing voice delivery with synchronised 3D graph animation
- Proposal system — MAIHERA can suggest changes to her own configuration
- Dream log nodes visible in 3D graph as distinct cluster (idea node type, dream-generated source tag)
- Ambient audio mode when MAIHERA interface not in focus

**Success criteria:** Yash wakes up, opens MAIHERA, she delivers a voice briefing that includes a genuine cross-project insight he had not consciously made — a connection between Presence and MAIHERA that changes how he thinks about one of them.

---

### Phase 7 — MAIHERA Learns and Grows

**Goal:** Full experience engine operational. Signal weights self-adjusting. Multi-model ideation. Trust escalation. MAIHERA is now genuinely smarter than when she started.

**Key deliverables:**
- Outcome tracker linked to every execution — success and failure recorded
- Decision log with full signal context at time of decision
- Pattern detector with noise filtering — minimum N observations before weight update
- Signal weight self-adjustment — decay rates, thresholds, intervention timing all adaptive
- Multi-model ideation — Claude Sonnet + Gemini Pro run in parallel, responses synthesized
- Confidence scores visible on all MAIHERA suggestions in the UI
- Trust escalation system — autonomy expands in categories where track record is strong
- MAIHERA challenges Yash's decisions proactively with evidence from decision log
- Full persona deepened by months of interaction data
- Decision Journal surfacing — "Boss, last time you faced this, here is what you decided and why"

**Success criteria:** MAIHERA catches a decision Yash is about to make and says "Boss, last time you approached something similar, here is what happened. You might want to consider this instead." — and she is right.

---

## 11. Open Design Questions

These questions are not yet resolved. Revisit relevant items in each phase chat.

| Question | Context |
|---|---|
| Mobile interface | How is MAIHERA accessed on mobile? Native app, PWA, or web? Architecture must support this from Phase 2 even if mobile ships later. |
| Voice library | ElevenLabs vs Cartesia — decided in Phase 2. Cartesia already integrated in Presence (existing team knowledge). ElevenLabs has more expressiveness options. |
| Presence product pipeline | What nodes and edges represent the productization initiative? How does MAIHERA actively support this direction? |
| Weekend rhythm | MAIHERA learns from observation. What are reasonable seed defaults for Phase 1 before observation begins? |
| Multi-device sync | Multiple device access — WebSocket sessions across devices need a strategy. Neo4j as source of truth is clear. |
| Notification delivery on mobile | When MAIHERA has a nudge and Yash is away from laptop — how does she reach him? Push notification? This needs a delivery channel for Phase 5+. |
| MAIHERA's self-architecture opinions | She tracks her own build. Should she be able to file challenge nodes against her own architecture decisions during Dream Mode? (Recommendation: yes.) |

---

## 12. Phase Change Log

Updated at the end of every phase. Use this to carry context forward into the next phase chat.

---

### Phase 0 — Architecture & Design

**Status:** Complete

**What was done:** Full system architecture designed across multiple collaborative sessions. All major decisions made and documented. This context document created.

**Key decisions made:**
- Hybrid resistance model (node for display + edge for reasoning) — only correct choice for meaningful intervention
- Python FastAPI backend + TypeScript React Electron frontend — clean separation, AI ecosystem in Python
- Three.js for 3D brain graph (not D3) — full 3D rotation, zoom, live animation
- WhatsApp removed from architecture — fragile, high privacy risk, behavioral data obtainable through system observer instead
- Ollama cloud for large model tasks (Qwen3-coder 480b for codebase analysis) — free tier with usage limits, treated as premium resource
- Groq + Gemini Flash as primary free tier workhorses — high daily quotas, fast
- Seven build phases defined in priority order
- Dream Mode trigger: idle 10+ minutes (not fixed time)
- Energy check-in: 1–10 scale, daily, part of morning briefing
- Decision Journal: project-scoped, captures personal reasoning at time of decision
- Figma MCP and Canva MCP added to Phase 4
- Weather delivered once per day only — repeated only if operationally relevant
- MAIHERA dedicated Google account for all Google integrations
- All MAIHERA Drive documents auto-shared to Yash's main account

**Architectural changes from initial design:**
- WhatsApp removed
- Figma + Canva MCPs added
- Dream Mode changed from fixed schedule to idle detection
- Ollama local models replaced with Ollama cloud (hardware constraint — Intel Iris Xe, no dedicated GPU)
- Features added: Daily Standup, Focus Mode, Pomodoro Integration, Context Capture, Weekly Review, Energy Check-in, Decision Journal, Conflict Detection, Relationship Tracking

**Next phase:** Phase 1 — The Brain is Born

---

### Phase 1 — The Brain is Born

**Status:** Complete

**What was built:**
- Neo4j Aura Free instance with full graph schema —
  constraints, indexes, all node types and edge types
- SQLite operational database — task state, decision log,
  signal decay log, session log, brain export log
- ChromaDB vector store — semantic memory with local
  sentence-transformers embeddings (all-MiniLM-L6-v2)
- BrainService — single interface to Neo4j, coordinating
  ChromaDB and SQLite. Signal decay, urgency computation,
  resistance recomputation, graph queries all implemented.
- Signal decay worker — APScheduler firing every hour,
  exponential decay with 0.05 floor
- LLM Router — Ollama cloud primary, Groq fallback.
  Quota tracking, cascade logic, request logging.
- MAIHERA persona system prompt — dynamic, context-aware,
  injecting self node and project context
- Node classifier — two-stage: keyword prescan + LLM via
  Groq. JSON parsing with markdown fence stripping.
- FastAPI application — full REST API, WebSocket brain
  graph updates, lifespan service management
- Seed data — structural scaffolding only. 8 nodes, 5
  edges. MAIHERA learns about projects in Phase 3+.
- Terminal chat CLI — Phase 1 testing interface
- Integration tests — 20 tests, all passing

**Key decisions made during Phase 1:**
- Claude Code runs via Ollama — consumes weekly quota fast.
  Switched to direct code delivery for all simple files.
  Only 2 Claude Code sessions used in Phase 1 total.
- Ollama cloud free tier: session + weekly limits.
  All MAIHERA runtime tests use Groq only (Ollama maxed
  artificially before routing).
- NEO4J_USER is e6514492 (custom Aura username).
- Seed data philosophy: structural anchors only.
  No hardcoded project knowledge — MAIHERA explores
  and learns from Phase 3 onwards.
- workspace field added to NodeSchema (personal/office/shared)
  — not in original architecture, added during Phase 1.
- FRIDAY reference removed from persona backlog.
  Behavioral instructions are the real levers, not
  character references.
- Chat endpoint currently hallucinates node references —
  does not inject real graph context into prompt yet.
  Fixed in Phase 2 when high-signal nodes are injected.

**Pending items for Phase 1 end review:**
- Persona system prompt needs full rewrite:
  remove hardcoded project descriptions, remove FRIDAY
  reference, add instruction never to cite non-existent nodes
- Add workspace field properly to NodeSchema enum
- Chat endpoint: inject actual high-signal nodes into
  system prompt context

**Known issues:**
- MAIHERA hallucinates node IDs in chat responses —
  she cannot see her own brain graph yet
- Neo4j Aura Free pauses after 3 days inactivity —
  add heartbeat or resume manually at console.neo4j.io

**Phase 1 Review — Completed after initial build:**
- WorkspaceType enum added to NodeSchema (personal/office/shared)
- Brain export function — dumps nodes and edges to JSON
  saved to backups/ directory
- Weekly export scheduler — every Sunday 2AM via APScheduler
- Neo4j heartbeat — every 30 minutes, prevents Aura pause
- Neo4j connection retry with exponential backoff — 30s intervals,
  10 minute maximum, surfaces alert to Yash if unreachable
- Chat endpoint — injects real high-signal nodes and self node
  into system prompt. MAIHERA now references real graph data.
- Persona rewrite — FRIDAY reference removed, hallucination guard
  added, proactivity conditional on having real context,
  phase-aware capability list, no hardcoded project descriptions
- Storage estimate added to /brain/stats endpoint
- Test node cleanup — API test node and chat-generated test
  nodes removed from graph

**Next phase:** Phase 2 — The Interface Lives

---



---

*End of MAIHERA Context Document v1.0*
*Upload this file to every phase chat and every Claude Code session before providing any instructions.*
*Keep Section 12 updated after every phase.*
