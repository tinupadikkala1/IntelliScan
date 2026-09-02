# IntelliVault — Batch 4 Complete Implementation Plan

**Target:** IntelliVault / IntelliScan  
**Batch:** Batch 4 — Conversational + Multi-Document Intelligence  
**Baseline:** Post-Batch-3 audit dated 2026-08-11  
**Status:** Implementation-ready plan  
**Scope:** Persistent Conversations, Folder Chat, Workspace Chat, Multi-Document Reasoning, Knowledge Graphs, Agentic Workflows

---

## 1. Batch 4 Objective

Batch 4 transforms IntelliVault from a multimodal semantic-search system into a persistent conversational knowledge assistant.

Batch 3 answers:

> Where is the information relevant to my query?

Batch 4 should answer:

> What do my files collectively say, and can I continue a conversation about that information?

The six roadmap features are:

1. Persistent Conversations
2. Folder Chat
3. Workspace Chat
4. Multi-Document Reasoning
5. Knowledge Graphs
6. Agentic Workflows

The post-Batch-3 audit confirms that the supporting substrate already exists: `RetrievalEngine`, `RAGEngine.ask(...)` with scoped retrieval, `EngineDBStore`, database migrations, `TaskManager`, plugin infrastructure, and evidence persistence/hydration. fileciteturn9file0

---

## 2. Current-State Baseline

The audit reports:

- Foundation complete.
- Batch 1 complete.
- Batch 2 complete.
- Batch 3 implemented.
- 212/212 tests pass.
- Evidence persistence and FAISS hydration were verified through restart testing.
- `RAGEngine.ask()` already supports scoped retrieval/file filtering internally.
- Current Ask AI UI uses `ask_file_direct()` instead of retrieval-based RAG.
- Semantic Search is workspace-wide in the UI.
- Folder scope exists in the engine but is not exposed.
- Persistent conversations do not yet exist.
- Knowledge Graph infrastructure does not yet exist.
- Agentic workflow infrastructure does not yet exist.
- Filesystem changes do not automatically reconcile AI evidence/FAISS.
- `vector_map` is written but not currently the hydration authority.
- PPTX/DOCX evidence navigation is incomplete.
- Retrieval ranking is imperfect.
- `EngineDBStore` can silently swallow persistence failures.
- First-access hydration can occur on the GUI thread.
- AI workloads can contend heavily on the constrained CPU/RAM system. fileciteturn9file0

---

# 3. Batch 4 Scope

| ID | Feature | Goal |
|---|---|---|
| B4-01 | Persistent Conversations | Persist conversations/messages/citations across application restarts. |
| B4-02 | Folder Chat | Conversational Q&A restricted to a selected folder and its descendants. |
| B4-03 | Workspace Chat | Conversational Q&A across the complete indexed workspace. |
| B4-04 | Multi-Document Reasoning | Combine evidence from multiple files and produce grounded synthesis/comparison. |
| B4-05 | Knowledge Graphs | Represent entities, relationships, files, concepts and their evidence links. |
| B4-06 | Agentic Workflows | Provide bounded, read-only AI workflows using explicit retrieval/graph/reasoning tools. |

These are the Batch-4 candidates identified by the project roadmap and confirmed by the current audit. fileciteturn9file0

---

# 4. Architecture Principle

**Do not rewrite Batch 3.**

Reuse:

```text
ContentEngine
      ↓
EvidenceEngine
      ↓
EmbeddingEngine
      ↓
VectorEngine / FAISS
      ↓
RetrievalEngine
      ↓
RAGEngine
```

Batch 4 adds layers above the retrieval foundation:

```text
Conversation Layer
Knowledge Graph Layer
Agent Layer
```

The target architecture is:

```text
                         IntelliVault
                              │
              ┌───────────────┴───────────────┐
              │                               │
         File System                     Conversation
              │                               │
              ▼                               ▼
         AI Indexing                   Conversation Manager
              │                               │
              ▼                               ▼
          Evidence                      Context Manager
              │                               │
        ┌─────┴─────┐                         │
        ▼           ▼                         │
      SQLite       FAISS                      │
        │           │                         │
        └─────┬─────┘                         │
              ▼                               │
        RetrievalEngine ◄─────────────────────┘
              │
       ┌──────┴────────┐
       ▼               ▼
Knowledge Graph     RAGEngine
       │               │
       └──────┬────────┘
              ▼
            Qwen
              │
              ▼
          Answer + Citations

Agent Engine sits above these services and orchestrates
explicit read-only tools.
```

---

# 5. Critical Preconditions — M0 Stabilization

The audit identifies several issues that should be addressed before serious Batch-4 development. fileciteturn9file0

## M0-01 — Empty AI Index UX

Current live state after the audit:

```text
evidence = 0
vector_map = 0
FAISS = 0
```

This occurred because orphaned FAISS vectors were removed by the existing hydration mechanism.

The persistence mechanism itself was verified to work after fresh indexing.

### Required behavior

If a user opens Semantic Search or Chat without an AI index:

```text
No AI index is available for this workspace.

Index your files to enable AI search and chat.

[ Index for AI ]
[ Cancel ]
```

Never silently present a searchable UI that cannot retrieve anything.

### Tests

- Empty index.
- Existing index.
- Cancel indexing.
- Failed indexing.
- Restart after indexing.

---

# 6. M0-02 — AI Filesystem Synchronization

Current watcher behavior updates the Batch-1 index but does not reconcile AI evidence/FAISS. This can produce stale answers. fileciteturn9file0

Implement:

```text
File System Event
      ↓
Change Detection
      ↓
AI Evidence Reconciliation
      ↓
Vector Map Reconciliation
      ↓
FAISS Reconciliation
      ↓
Graph Reconciliation
      ↓
Search/Chat sees current data
```

### New file

- Update `indexed_files`.
- If AI indexing is enabled for the scope, index the file.
- Persist evidence.
- Generate embeddings.
- Add vectors.
- Update graph if enabled.

### Modified file

- Detect checksum/mtime change.
- Remove old evidence.
- Remove old vector mappings.
- Remove old FAISS vectors.
- Remove old graph evidence links.
- Re-index new content.

### Deleted file

- Remove `indexed_files`.
- Remove evidence.
- Remove vector mappings.
- Remove FAISS vectors.
- Remove graph evidence links.
- Remove orphan graph relationships/entities where appropriate.

### Renamed/moved file

Preserve content identity when possible and update paths without leaving stale records.

### Tests

- New file.
- Modified file.
- Deleted file.
- Rename.
- Move.
- Restart.
- Search after synchronization.
- Chat after synchronization.

---

# 7. M0-03 — Vector Mapping Integrity

The audit found that `vector_map` is written but is not currently the authority used by hydration. fileciteturn9file0

Define an authoritative mapping.

Required invariant:

```text
Every active FAISS vector
        ↓
valid chunk_id
        ↓
valid evidence row
        ↓
valid indexed file
```

Implement an integrity checker:

```python
validate_vector_evidence_integrity()
```

Use it after:

- indexing
- deleting
- modifying
- moving
- restarting
- rebuilding the index

### Tests

- Valid mapping.
- Missing evidence.
- Orphan FAISS vector.
- Orphan vector_map.
- Deleted file.
- Restart hydration.

---

# 8. M0-04 — Retrieval Quality

The audit found that pure cosine ranking can rank weaker evidence above a near-verbatim answer. fileciteturn9file0

Use:

```text
Query
 ↓
Query embedding
 ↓
FAISS candidates
 ↓
Scope/filter
 ↓
Deduplicate
 ↓
Candidate diversity
 ↓
Optional rerank
 ↓
Context selection
```

Avoid allowing one file to consume the entire context.

### Required controls

- top-k.
- similarity threshold.
- per-file maximum chunks.
- evidence diversity.
- optional LLM reranking.
- deterministic fallback when reranking is unavailable.

### Tests

- Relevant result ranking.
- Multiple relevant files.
- Duplicate chunks.
- Irrelevant chunks.
- Folder filtering.
- Workspace filtering.
- Rerank unavailable.

---

# 9. M0-05 — Evidence Navigation

Complete the existing gaps before exposing citations throughout Batch 4.

Required:

| Modality | Required behavior |
|---|---|
| PDF | Exact page |
| PPTX | Exact slide |
| DOCX | Relevant section/heading |
| Image | Preview |
| Audio | Timestamp |
| Video | Timestamp/keyframe |

Ask AI and Chat citations must carry actual location metadata.

Create a shared `EvidenceLocation` contract instead of modality-specific ad-hoc behavior.

Tests must verify actual navigation, not just that a callback fires.

---

# 10. M0-06 — Persistence Error Handling

`EngineDBStore` must not silently turn failed database writes into apparently successful operations.

Required:

```text
DB operation
   ↓
success
   OR
structured PersistenceError
   ↓
Task/UI notification
```

A message must never appear saved when persistence failed.

Tests:

- DB unavailable.
- DB locked.
- message insert failure.
- citation insert failure.
- migration failure.
- recovery.

---

# 11. M0-07 — Background Execution

All heavy Batch-4 operations must remain outside the GUI thread.

Use:

```text
UI
 ↓
TaskManager
 ↓
QThreadPool
 ↓
Conversation/RAG/Graph/Agent service
 ↓
Qt signals
 ↓
UI
```

Worker operations include:

- retrieval
- reranking
- context construction
- LLM generation
- graph extraction
- graph queries
- agent tool execution

---

# 12. M0-08 — AI Concurrency Control

Hardware from the audit:

- Intel i3-N305
- ~6.9 GiB RAM
- CPU-only
- limited disk
- Whisper/CLIP/Qwen can contend heavily. fileciteturn9file0

Implement an `AIResourceManager` or equivalent.

At minimum:

```text
AI Resource Manager
 ├── LLM slot
 ├── Embedding slot
 ├── Vision slot
 ├── Speech slot
 └── global concurrency limit
```

Prevent unsafe simultaneous heavy workloads.

Provide queue state and cancellation.

---

# 13. Conversation Subsystem

Create a dedicated conversation package rather than adding conversation logic to `MainWindow`.

Suggested:

```text
conversation/
├── models.py
├── conversation_manager.py
├── conversation_service.py
├── conversation_store.py
├── context_builder.py
├── citation_builder.py
└── scope_manager.py
```

---

# 14. Conversation Database Schema

Add a versioned migration.

## `conversations`

```text
id
title
scope_type
scope_path
created_at
updated_at
status
model_name
metadata_json
```

## `conversation_messages`

```text
id
conversation_id
role
content
created_at
sequence_number
metadata_json
```

## `message_citations`

```text
id
message_id
chunk_id
file_path
source_label
source_index
char_start
char_end
timestamp_start
timestamp_end
citation_order
metadata_json
```

Recommended indexes:

```text
conversations.updated_at
conversation_messages.conversation_id
conversation_messages.sequence_number
message_citations.message_id
message_citations.chunk_id
```

Use foreign keys and deliberate cascade behavior.

---

# 15. B4-01 — Persistent Conversations

## Backend

Implement:

```python
create_conversation(scope)
list_conversations()
get_conversation(conversation_id)
rename_conversation(conversation_id, title)
delete_conversation(conversation_id)
append_message(...)
get_messages(conversation_id)
store_citations(...)
```

## UX

Conversation history should provide:

```text
New Conversation
----------------
Today
  ML Project Chat
  Research Notes

Yesterday
  Semester Report
```

Actions:

- New.
- Rename.
- Delete.
- Open.
- Continue.

## Persistence test

```text
Create conversation
 ↓
Send message
 ↓
Close application
 ↓
Restart
 ↓
Open conversation
 ↓
Messages + citations restored
```

---

# 16. Conversation Context Manager

Do not send unlimited conversation history to the LLM.

Create:

```text
ConversationContextBuilder
```

Input:

```text
conversation history
current question
retrieved evidence
scope
```

Output:

```text
bounded LLM context
```

Priority:

1. Current question.
2. Relevant retrieved evidence.
3. Recent conversation turns.
4. Relevant older conversation context.
5. System instructions.

Keep a bounded context budget.

---

# 17. Conversation-Aware Retrieval

Example:

```text
User:
Which algorithms are discussed?

AI:
Random Forest, SVM and CNN.

User:
Which one performs best?
```

Pipeline:

```text
Current question
      ↓
Conversation context
      ↓
Resolved retrieval query
      ↓
Retrieval
      ↓
RAG
```

Retain the original question. If a resolved query is generated, store it in metadata for debugging.

Tests:

- pronoun follow-up.
- omitted subject.
- "that document".
- "the second one".
- comparison follow-up.
- unrelated topic reset.

---

# 18. Reusable Chat UI

Create a reusable chat component for:

- Folder Chat.
- Workspace Chat.
- Future File Chat.
- Agent chat.

Suggested:

```text
ChatView
├── ScopeHeader
├── ConversationHistory
├── MessageList
├── CitationList
├── InputBox
├── SendButton
├── StopButton
└── StatusIndicator
```

Do not duplicate separate chat implementations.

---

# 19. Chat UX States

Required states:

```text
Ready
Retrieving evidence...
Generating answer...
Completed
Failed
Cancelled
```

Do not fake percentage progress for LLM generation.

If streaming is compatible with the current Ollama integration, it may be added. Otherwise use a clear busy state.

---

# 20. B4-02 — Folder Chat

## User entry

Recommended:

```text
Right-click folder
 ↓
AI
 ↓
Chat with this Folder
```

Header:

```text
Chat Scope: 📁 /Projects/ML
```

## Backend

Use the existing retrieval scope machinery:

```text
RetrievalScope.FOLDER
```

with a canonical normalized folder path.

Do not manually load every file in the folder.

Use retrieval filtering.

## Tests

- Folder-only retrieval.
- Nested folders.
- Outside-folder exclusion.
- Empty folder.
- Unindexed folder.
- Deleted file.
- Modified file.
- Ollama unavailable.
- Citation navigation.

---

# 21. B4-03 — Workspace Chat

Use the same ChatView and ConversationManager.

Scope:

```text
WORKSPACE
```

Entry:

```text
Toolbar
 ↓
AI
 ↓
Workspace Chat
```

Header:

```text
Chat Scope: 🌐 Workspace
```

Tests:

- Multiple folders.
- Cross-folder question.
- Large workspace.
- Empty AI index.
- Citation navigation.
- Restart persistence.

Do not create a separate WorkspaceChatEngine.

---

# 22. Citation Architecture

Every grounded response should contain citations linked to actual evidence.

Example:

```text
The project uses Random Forest for classification.

[1] ML Notes.pdf — Page 12
[2] Project Report.docx — Section: Algorithms
```

Citation click must invoke the shared evidence navigator.

Citation records must persist.

Never fabricate a page number, slide, timestamp or section.

---

# 23. B4-04 — Multi-Document Reasoning

Create:

```text
MultiDocumentContextBuilder
```

Pipeline:

```text
Question
 ↓
Conversation resolution
 ↓
Scoped retrieval
 ↓
Candidate evidence
 ↓
Group by file
 ↓
Deduplicate
 ↓
Rerank
 ↓
Evidence diversity selection
 ↓
Cross-document context
 ↓
LLM
 ↓
Answer + citations
```

Preserve provenance for every evidence block.

---

# 24. Cross-Document Comparison

Support:

```text
Compare Report A and Report B.
```

```text
What concepts appear in both documents?
```

```text
Which report provides the stronger explanation?
```

The context builder should explicitly identify source documents.

Tests:

- 2-document comparison.
- 3-document synthesis.
- Same fact in multiple files.
- Irrelevant document.
- Conflicting evidence.
- Citation correctness.

---

# 25. Contradiction Handling

When documents conflict:

```text
Report A: 2024
Report B: 2025
```

The system must not silently choose one.

Tell the LLM that retrieved evidence may contain conflicting claims and require source attribution.

Tests:

- conflicting dates.
- conflicting values.
- conflicting definitions.
- missing information.

---

# 26. Knowledge Graph Subsystem

Create:

```text
graph/
├── graph_models.py
├── graph_store.py
├── graph_engine.py
├── entity_extractor.py
├── relationship_extractor.py
└── graph_query_service.py
```

Start with SQLite-backed graph storage unless project requirements explicitly demand an external graph database.

---

# 27. Knowledge Graph Schema

## `graph_entities`

```text
id
canonical_name
entity_type
normalized_name
metadata_json
created_at
updated_at
```

## `graph_relationships`

```text
id
source_entity_id
target_entity_id
relationship_type
confidence
metadata_json
created_at
```

## `graph_evidence_links`

```text
id
relationship_id
chunk_id
file_path
source_label
source_index
char_start
char_end
metadata_json
```

Every important relationship must be traceable to source evidence.

---

# 28. Entity Extraction

Input:

```text
EvidenceChunk
```

Output:

```json
{
  "entities": [
    {
      "name": "Random Forest",
      "type": "ALGORITHM"
    }
  ]
}
```

Validate all model output before persistence.

Initial entity types should remain controlled:

```text
PERSON
ORGANIZATION
LOCATION
PROJECT
CONCEPT
TECHNOLOGY
DOCUMENT
ALGORITHM
PRODUCT
TOPIC
```

Do not allow arbitrary uncontrolled types.

---

# 29. Relationship Extraction

Store:

```text
source
relationship
target
confidence
evidence
```

Example:

```text
Random Forest
   └── discussed_in
          └── ML Notes.pdf
```

Tests:

- Valid extraction.
- Invalid JSON.
- Duplicate relationship.
- Conflicting relationship.
- Missing evidence.
- Low-confidence relationship.

---

# 30. Entity Normalization

Avoid duplicate nodes:

```text
Python
python
PYTHON
```

Implement:

```python
normalize_entity_name()
```

and alias support.

Do not use uncontrolled fuzzy merging.

Tests:

- case.
- whitespace.
- punctuation.
- aliases.
- similar but different names.

---

# 31. Graph Indexing

Integrate graph generation with AI indexing:

```text
AI Indexing
 ↓
ContentBlocks
 ↓
Evidence
 ↓
Entity extraction
 ↓
Relationship extraction
 ↓
Graph persistence
```

For a modified file:

```text
remove old file-derived graph evidence
 ↓
re-extract
 ↓
merge entities
 ↓
create new relationships
```

For deletion:

```text
remove file-derived links
 ↓
remove orphan relationships
 ↓
remove orphan entities where safe
```

---

# 32. Knowledge Graph UI

Add a user-facing entry point:

```text
Tools
 ↓
Knowledge Graph
```

or:

```text
Right-click file/folder
 ↓
AI
 ↓
Explore Knowledge Graph
```

Initial UI:

```text
Graph Canvas
Entity Search
Node Details
Relationship Details
Evidence Panel
Related Files
```

Do not implement graph editing in the first version.

---

# 33. Graph Node Details

Selecting an entity should show:

```text
Entity:
Random Forest

Type:
Algorithm

Related files:
- ML Notes.pdf
- Project Report.docx

Relationships:
- discussed_in → ML Notes.pdf
- used_by → Project A

Evidence:
Page 12...
```

Double-clicking evidence invokes `EvidenceNavigator`.

---

# 34. Graph Search

Initial capabilities:

- Search entity.
- Show connected entities.
- Show connected files.
- Open supporting evidence.

Do not implement a graph query language in the first Batch-4 version.

---

# 35. B4-06 — Agentic Workflows

Agentic functionality is the final Batch-4 layer.

Do not give the agent unrestricted system access.

Initial read-only tools:

```text
search
retrieve_evidence
list_related_files
get_file_metadata
query_knowledge_graph
open_evidence
summarize_evidence
compare_documents
```

Every tool needs:

- name.
- description.
- validated input schema.
- output schema.
- timeout.
- cancellation.
- policy.

---

# 36. Agent Architecture

Create:

```text
agent/
├── agent_engine.py
├── agent_state.py
├── planner.py
├── tool_registry.py
├── tool_executor.py
├── policies.py
└── schemas.py
```

Pipeline:

```text
User Request
 ↓
Planner
 ↓
Tool selection
 ↓
Tool execution
 ↓
Observation
 ↓
State update
 ↓
Next tool
 ↓
Final synthesis
```

---

# 37. Agent Guardrails

Required:

- maximum step count.
- maximum execution time.
- maximum retrieved evidence.
- cancellation.
- structured tool inputs.
- structured tool outputs.
- no shell execution.
- no arbitrary Python execution.
- no unrestricted file modification.
- no unrestricted file deletion.
- read-only first release.

Recommended initial:

```text
MAX_AGENT_STEPS = 8
```

---

# 38. Agent UI

Entry:

```text
AI
 ↓
Agent Mode
```

Display concise action status:

```text
✓ Searched workspace
✓ Found 4 relevant documents
✓ Queried knowledge graph
✓ Compared documents
✓ Generated answer
```

Do not expose hidden chain-of-thought.

Show only user-relevant actions.

---

# 39. Agent Cancellation

The Stop button must:

- stop scheduling new tools.
- cancel pending tasks where possible.
- mark the agent task cancelled.
- preserve the conversation safely.

Tests:

- cancel before first tool.
- cancel between tools.
- timeout.
- tool failure.
- max-step termination.
- LLM unavailable.

---

# 40. Conversation + Knowledge Graph

Example:

```text
User:
What technologies are related to Project Apollo?
```

Pipeline:

```text
Conversation context
       ↓
Graph query + retrieval
       ↓
Evidence
       ↓
Qwen
       ↓
Grounded answer
       ↓
Citations
```

The graph supplements semantic retrieval; it does not replace it.

---

# 41. Agent + Knowledge Graph

Example:

```text
Agent
 ↓
query_knowledge_graph("Project Apollo")
 ↓
retrieve_evidence(...)
 ↓
compare_documents(...)
 ↓
Final synthesis
```

This provides a meaningful Batch-4 agent demonstration without unrestricted system control.

---

# 42. Settings

Only expose settings that are genuinely supported.

Recommended:

## Conversations

- Default scope.
- Context/history limit.
- Auto-save.

## Retrieval

- Top-k.
- Similarity threshold.
- Reranking enabled.

## Knowledge Graph

- Entity extraction enabled.
- Relationship extraction enabled.

## Agent

- Maximum steps.
- Timeout.
- Enable/disable agent mode.

Avoid exposing unnecessary low-level model parameters.

---

# 43. MainWindow Refactoring

The audit identifies `MainWindow` as a large orchestration class. fileciteturn9file0

Extract controllers/services:

```text
AIController
SearchController
ConversationController
IndexController
NavigationController
```

Keep `MainWindow` responsible primarily for:

- composing UI.
- connecting signals.
- high-level navigation.

Do not move all logic into one new giant service.

---

# 44. Suggested Project Structure

```text
conversation/
    models.py
    conversation_manager.py
    conversation_service.py
    conversation_store.py
    context_builder.py
    citation_builder.py
    scope_manager.py

graph/
    graph_models.py
    graph_store.py
    graph_engine.py
    entity_extractor.py
    relationship_extractor.py
    graph_query_service.py

agent/
    agent_engine.py
    agent_state.py
    planner.py
    tool_registry.py
    tool_executor.py
    policies.py
    schemas.py

ui/
    dialogs/
        chat_dialog.py
        conversation_history_dialog.py
        knowledge_graph_dialog.py
        agent_dialog.py

widgets/
    chat_view.py
    message_bubble.py
    citation_widget.py
    graph_view.py
```

Adapt names to the project's existing conventions.

---

# 45. Implementation Milestones

## M0 — Stabilization

- Empty-index UX.
- AI filesystem synchronization.
- Vector-map integrity.
- Evidence navigation.
- Retrieval quality.
- DB error propagation.
- Background hydration.
- AI concurrency control.

## M1 — Conversation Database

- migrations.
- conversation model.
- message model.
- citation model.
- CRUD.
- persistence tests.

## M2 — Conversation Service

- conversation manager.
- context builder.
- citation builder.
- scope manager.
- follow-up resolution.

## M3 — Reusable Chat UI

- ChatView.
- message rendering.
- citation widgets.
- history.
- send/stop.
- status states.

## M4 — Folder Chat

- folder scope.
- UI entry point.
- RAG integration.
- citations.
- tests.

## M5 — Workspace Chat

- workspace scope.
- UI entry point.
- cross-folder retrieval.
- tests.

## M6 — Multi-Document Reasoning

- evidence aggregation.
- per-file grouping.
- reranking.
- comparison.
- contradiction handling.
- citations.
- tests.

## M7 — Knowledge Graph Backend

- schema.
- entity extraction.
- relationship extraction.
- normalization.
- evidence links.
- graph queries.
- tests.

## M8 — Knowledge Graph UI

- graph canvas.
- entity search.
- node details.
- relationship details.
- evidence navigation.
- tests.

## M9 — Agent Tool System

- tool schemas.
- registry.
- validation.
- executor.
- policies.
- tests.

## M10 — Agent Engine

- planner.
- state.
- bounded execution.
- cancellation.
- timeout.
- final synthesis.
- tests.

## M11 — Agent UI

- Agent Mode.
- action/status display.
- stop/cancel.
- error states.
- tests.

## M12 — Full Integration

- conversation + retrieval.
- conversation + graph.
- multimodal citations.
- agent + retrieval.
- agent + graph.
- restart testing.
- regression testing.

---

# 46. Testing Strategy

Use four layers.

## Layer 1 — Unit Tests

Cover:

- conversation models.
- conversation store.
- context builder.
- scope manager.
- citation builder.
- entity normalization.
- relationship normalization.
- graph store.
- graph query service.
- tool registry.
- agent state.
- planner validation.
- cancellation.

## Layer 2 — Integration Tests

Test:

```text
Conversation
 → Retrieval
 → Evidence
 → RAG
 → Citation
 → Persistence
```

and:

```text
Evidence
 → Entity extraction
 → Graph
 → Query
```

and:

```text
Agent
 → Tool
 → Retrieval
 → Graph
 → Final answer
```

## Layer 3 — UI Tests

Using pytest-qt:

- create conversation.
- switch conversation.
- send message.
- stop generation.
- open citation.
- open folder chat.
- open workspace chat.
- graph node selection.
- agent cancellation.

## Layer 4 — Runtime E2E

At minimum:

```text
Index files
 ↓
Restart
 ↓
Folder Chat
 ↓
Multi-turn question
 ↓
Multi-document reasoning
 ↓
Open citation
 ↓
Knowledge Graph
 ↓
Select entity
 ↓
Open evidence
 ↓
Agent task
 ↓
Verify grounded answer
```

---

# 47. Required Test Matrix

| Test Area | Required |
|---|---:|
| Conversation CRUD | Yes |
| Message persistence | Yes |
| Citation persistence | Yes |
| Restart conversation | Yes |
| Folder scope | Yes |
| Workspace scope | Yes |
| Multi-document retrieval | Yes |
| Cross-document comparison | Yes |
| Contradiction handling | Yes |
| PDF citation | Yes |
| PPTX citation | Yes |
| DOCX citation | Yes |
| Image citation | Yes |
| Audio citation | Yes |
| Video citation | Yes |
| Entity extraction | Yes |
| Entity normalization | Yes |
| Relationship extraction | Yes |
| Graph persistence | Yes |
| Graph evidence links | Yes |
| Graph deletion cleanup | Yes |
| Graph search | Yes |
| Agent tool validation | Yes |
| Agent cancellation | Yes |
| Agent timeout | Yes |
| Agent max steps | Yes |
| Ollama unavailable | Yes |
| Database failure | Yes |
| File modified during chat | Yes |
| File deleted during chat | Yes |
| Restart after indexing | Yes |
| Full regression suite | Yes |

---

# 48. Failure and Recovery Tests

## Ollama unavailable

Expected:

- Chat fails gracefully.
- Existing conversations remain accessible.
- User messages are not silently lost.

## Database unavailable

Expected:

- Clear persistence error.
- No false "saved" state.

## File deleted

Expected:

- Stale evidence removed.
- Citation fails gracefully if previously generated.
- Graph links cleaned.

## File modified

Expected:

- Old vectors removed.
- New evidence indexed.
- Future chat uses new content.

## Agent tool failure

Expected:

- Structured tool error.
- Agent can recover or stop.
- No fabricated tool result.

---

# 49. Performance Requirements

The current hardware requires bounded workloads.

Do not:

- load duplicate Whisper models.
- run unlimited AI tasks.
- load entire workspaces into RAM.
- concatenate complete workspaces into LLM prompts.
- rebuild the entire graph unnecessarily.
- allow unlimited agent steps.

Use:

- retrieval limits.
- context limits.
- task queueing.
- lazy graph queries.
- cached transcription.
- cached embeddings.
- bounded agent execution.
- bounded conversation history.

---

# 50. Caching Improvements

Reuse existing persisted evidence.

Potential path:

```text
file hash
 ↓
transcription/content
 ↓
Evidence
 ↓
embeddings
```

Do not re-run Whisper for Ask AI when current persisted evidence already contains the transcript.

Graph extraction should also be invalidated by file identity/version rather than repeated blindly.

---

# 51. Security and Safety

The Batch-4 agent is a **read-only knowledge agent**.

It must not have unrestricted:

- shell execution.
- Python execution.
- file deletion.
- file modification.
- network access.

All tools must be explicitly registered and validated.

---

# 52. Observability

Log structured events for:

- conversation creation.
- message generation.
- retrieval latency.
- evidence count.
- reranking latency.
- graph extraction.
- graph query.
- agent tool execution.
- cancellation.
- failures.

Avoid logging complete document contents unnecessarily.

Prefer IDs, paths where appropriate, counts and timing metadata.

---

# 53. Definition of Done — Persistent Conversations

Complete only when:

- conversations persist.
- messages persist.
- citations persist.
- restart restores conversations.
- conversations can be renamed/deleted.
- persistence failures are visible.
- UI remains responsive.
- tests pass.

---

# 54. Definition of Done — Folder Chat

Complete only when:

- folder can be selected.
- folder scope is enforced.
- nested files are included.
- unrelated files are excluded.
- multi-turn conversation works.
- citations work.
- restart works.
- tests pass.

---

# 55. Definition of Done — Workspace Chat

Complete only when:

- workspace scope works.
- cross-folder retrieval works.
- conversations persist.
- citations work.
- retrieval remains bounded.
- tests pass.

---

# 56. Definition of Done — Multi-Document Reasoning

Complete only when:

- multiple files can contribute evidence.
- evidence is grouped by source.
- retrieval quality is acceptable.
- conflicting evidence is identified.
- citations identify source files.
- tests cover two- and three-document cases.

---

# 57. Definition of Done — Knowledge Graph

Complete only when:

- entities persist.
- relationships persist.
- relationships have evidence.
- duplicate entities are normalized.
- file changes update graph data.
- graph search works.
- graph UI works.
- evidence navigation works.
- tests pass.

---

# 58. Definition of Done — Agentic Workflows

Complete only when:

- tools are explicitly registered.
- tool inputs are validated.
- agent steps are bounded.
- cancellation works.
- timeout works.
- arbitrary code execution is impossible.
- retrieval works.
- graph queries work.
- final answers remain evidence-grounded.
- tests pass.

---

# 59. Full Batch 4 Definition of Done

Batch 4 is complete only when:

```text
Persistent Conversations
        +
Folder Chat
        +
Workspace Chat
        +
Multi-Document Reasoning
        +
Knowledge Graphs
        +
Agentic Workflows
        +
Filesystem Synchronization
        +
Evidence Navigation
        +
Retrieval Quality
        +
Persistence Integrity
        +
Background Processing
        +
Regression Safety
```

are implemented and tested.

The final test count must be reported from the actual test run rather than predetermined.

---

# 60. Recommended Final Architecture

```text
                     USER
                       │
                       ▼
               Conversation UI
                       │
                       ▼
             Conversation Manager
                       │
                ┌──────┴──────┐
                │             │
                ▼             ▼
         Conversation DB   Scope Manager
                                │
                     ┌──────────┼──────────┐
                     ▼          ▼          ▼
                   FILE       FOLDER    WORKSPACE
                     │          │          │
                     └──────────┼──────────┘
                                ▼
                         RetrievalEngine
                                │
                       ┌────────┴────────┐
                       ▼                 ▼
                  Vector Search     Knowledge Graph
                       │                 │
                       └────────┬────────┘
                                ▼
                         Evidence Context
                                │
                                ▼
                            RAGEngine
                                │
                                ▼
                              Qwen
                                │
                                ▼
                         Answer + Citations

                     ▲
                     │
                Agent Engine
                     │
          ┌──────────┼──────────┐
          ▼          ▼          ▼
       Search      Graph     Compare
        Tool        Tool       Tool
```

The agent is an orchestration layer above the existing knowledge infrastructure, not a replacement for it.

---

# 61. Implementation Rules

1. Do not rewrite Batch 3.
2. Reuse `RetrievalEngine`.
3. Reuse `RAGEngine`.
4. Reuse `EngineDBStore` where appropriate, but create a dedicated conversation store.
5. Use versioned database migrations.
6. Keep heavy operations off the GUI thread.
7. Preserve evidence provenance.
8. Never fabricate citations.
9. Never silently discard persistence failures.
10. Never allow unrestricted agent execution.
11. Keep AI workloads bounded for the current hardware.
12. Every user-facing feature needs appropriate unit, integration and UI coverage.
13. Every Batch-4 feature must have an explicit user entry point.
14. Do not implement future-scope features unless explicitly promoted into Batch 4.
15. Preserve all Batch-1, Batch-2 and Batch-3 behavior.

---

# 62. Recommended Development Order

```text
M0  Stabilize Batch 3
 ↓
M1  Conversation Database
 ↓
M2  Conversation Service + Context
 ↓
M3  Reusable Chat UI
 ↓
M4  Folder Chat
 ↓
M5  Workspace Chat
 ↓
M6  Multi-Document Reasoning
 ↓
M7  Knowledge Graph Backend
 ↓
M8  Knowledge Graph UI
 ↓
M9  Agent Tool System
 ↓
M10 Agent Engine
 ↓
M11 Agent UI
 ↓
M12 Full Integration
 ↓
M13 Regression + Performance Audit
 ↓
BATCH 4 COMPLETE
```

This order minimizes architectural rework because each later capability consumes infrastructure created by the previous milestone.

---

# 63. Expected User Experience

After Batch 4:

```text
User opens IntelliVault
        ↓
Selects workspace
        ↓
Indexes content for AI
        ↓
Opens Folder Chat
        ↓
"What algorithms are discussed?"
        ↓
Answer + citations
        ↓
"Which one performs best?"
        ↓
Conversation-aware retrieval
        ↓
"Compare it with the other report."
        ↓
Multi-document reasoning
        ↓
Answer + multiple citations
        ↓
Open Knowledge Graph
        ↓
Select Random Forest
        ↓
See related concepts/files
        ↓
Ask Agent:
"Find all documents related to this project
and compare their conclusions."
        ↓
Agent searches
        ↓
Queries graph
        ↓
Retrieves evidence
        ↓
Compares documents
        ↓
Grounded final answer
```

The intended transformation is:

> **From semantic file search → persistent conversational knowledge intelligence.**

---

# 64. Batch 4 Completion Checklist

## Stabilization

- [ ] Empty-index UX
- [ ] AI filesystem synchronization
- [ ] Vector-map authority
- [ ] PPTX navigation
- [ ] DOCX navigation
- [ ] Retrieval reranking
- [ ] DB error propagation
- [ ] Background hydration
- [ ] AI concurrency guard
- [ ] Whisper cache unification

## Conversations

- [ ] Conversation migration
- [ ] Message migration
- [ ] Citation migration
- [ ] ConversationStore
- [ ] ConversationManager
- [ ] ContextBuilder
- [ ] CitationBuilder
- [ ] Conversation history
- [ ] Restart persistence
- [ ] Delete/rename

## Chat

- [ ] ChatView
- [ ] Message UI
- [ ] Folder Chat
- [ ] Workspace Chat
- [ ] Follow-up questions
- [ ] Stop/cancel
- [ ] Citation navigation

## Multi-document reasoning

- [ ] Evidence aggregation
- [ ] Per-file grouping
- [ ] Reranking
- [ ] Comparison prompts
- [ ] Contradiction handling
- [ ] Multi-document citations

## Knowledge Graph

- [ ] Entity schema
- [ ] Relationship schema
- [ ] Evidence links
- [ ] Entity extraction
- [ ] Relationship extraction
- [ ] Entity normalization
- [ ] Graph queries
- [ ] Graph UI
- [ ] Change synchronization

## Agent

- [ ] Tool schemas
- [ ] Tool registry
- [ ] Tool executor
- [ ] Planner
- [ ] State
- [ ] Step limits
- [ ] Timeout
- [ ] Cancellation
- [ ] Read-only guardrails
- [ ] Agent UI
- [ ] Retrieval tool
- [ ] Graph tool
- [ ] Compare tool

## Testing

- [ ] Unit tests
- [ ] Database tests
- [ ] Retrieval tests
- [ ] Conversation integration tests
- [ ] Graph integration tests
- [ ] Agent integration tests
- [ ] UI tests
- [ ] Restart tests
- [ ] Failure/recovery tests
- [ ] Performance tests
- [ ] Full regression suite

---

## Source Baseline

This plan is grounded in the uploaded **POST-BATCH-3 CURRENT-STATE AUDIT**, including its verified architecture, database state, Batch-4 roadmap, dependencies, blockers, test results and readiness assessment. fileciteturn9file0

**End of Batch 4 Implementation Plan**
