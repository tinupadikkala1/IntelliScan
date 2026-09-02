# IntelliVault — Batch 5 Complete Implementation Plan
## Intelligent Organization & Knowledge Management

**Source of truth:** `batch5_audit_report.md` (Post-Batch-4 audit, 2026-08-11).
**Scope:** Frozen Batch 5 — 10 features.

---

# 1. Batch 5 Scope

Batch 5 is frozen to exactly these ten user-facing features:

1. **B5-01 — Intelligent File Classification**
2. **B5-02 — AI-Based Auto-Tagging**
3. **B5-03 — Smart Collections**
4. **B5-04 — Exact Duplicate Detection**
5. **B5-05 — Near-Duplicate Detection**
6. **B5-06 — Related File Discovery**
7. **B5-07 — File-to-File Relationship Analysis**
8. **B5-08 — AI Organization Suggestions**
9. **B5-09 — Saved Semantic Searches**
10. **B5-10 — Workspace Knowledge Dashboard**

No future-scope functionality should be added to this batch.

---

# 2. Current-System Baseline

The post-Batch-4 audit reports:

- Batch 1–4 functionality is implemented.
- The full test suite passes: **261 passed, 0 failed, 0 skipped**.
- `indexed_files` contains 89 records, all with SHA-256 checksums.
- Exact duplicate data already exists in the live database.
- `RetrievalEngine.retrieve_similar()` already provides the core primitive needed for near-duplicate and related-file functionality.
- AI category/tags/keywords already exist in `ai_analysis`, but only 3 of 89 files have AI analysis.
- The Knowledge Graph is an **ENTITY → ENTITY** graph; it does not currently support FILE → FILE relationships.
- `search_history` exists but is only a search log, not a saved-search system.
- No collection subsystem exists.
- No duplicate UI or relationship UI exists.
- Dashboard aggregates are available as raw queries but there is no DashboardService/UI.
- The AI/FAISS index is currently empty at audit time, so Batch-5 testing must include a seeded test workspace.
- Deleted files currently remain as stale rows in `indexed_files`.

Source baseline: `batch5_audit_report.md`.

---

# 3. Mandatory Pre-Batch-5 Stabilization

These are prerequisites, not optional Batch-5 features.

## 3.1 Fix deleted-file reconciliation

### Problem

Deleted files remain in `indexed_files`.

This can corrupt:

- exact duplicate counts
- near-duplicate counts
- related-file results
- collection membership
- organization suggestions
- dashboard statistics

### Required implementation

Extend the existing file-watcher/incremental reindex path so that a confirmed deletion:

1. Removes the `indexed_files` row.
2. Removes associated AI-derived state where appropriate.
3. Removes evidence/vector data through the existing AI-sync path.
4. Removes graph state through `GraphStore.remove_file()`.
5. Cleans file relationships.
6. Invalidates collection membership.
7. Invalidates or marks stale saved-search/dashboard data if necessary.

Do not duplicate cleanup logic in every Batch-5 engine. Create/use one file-removal orchestration path.

### Tests

- Delete indexed file → database row removed.
- Delete indexed AI file → evidence removed.
- Delete file → FAISS vectors removed.
- Delete file → graph evidence/relationships removed.
- Delete file → file relationships removed.
- Delete file → collection membership removed/marked stale.
- Restart after deletion → no phantom file appears.

---

## 3.2 Add checksum index

Add:

```sql
CREATE INDEX ix_indexed_files_checksum
ON indexed_files(checksum);
```

This is required for scalable exact duplicate grouping.

---

## 3.3 Consolidate SHA-256 computation

The audit identified multiple SHA-256 implementations.

Create a single reusable file-identity helper, for example:

```text
services/file_identity.py
```

Responsibilities:

- `calculate_sha256(path)`
- optional identity validation
- consistent error behavior
- consistent empty-file handling

Update existing callers without changing their external behavior.

Tests must prove identical hashes across old/new callers.

---

## 3.4 Define empty-file duplicate policy

There are currently 13 empty files sharing the SHA-256 of an empty file.

Recommended behavior:

- Empty files remain valid indexed files.
- Exact duplicate detection should show them as an explicit duplicate group.
- UI should label the group as **Empty-content duplicates**.
- Do not silently discard them.

If the implementation team chooses another policy, document it and test it consistently.

---

## 3.5 Batch-5 settings consistency

Add a Batch-5 settings section following the Batch-4 settings pattern.

At minimum support configurable:

- duplicate threshold
- near-duplicate threshold
- maximum related-file results
- classification batch size
- organization suggestion confidence threshold
- empty-file duplicate visibility
- dashboard refresh behavior

Persist settings consistently with the existing settings architecture.

---

# 4. Architecture Principles

Batch 5 must preserve the current architecture:

```text
UI
 ↓
Signal / controller
 ↓
TaskManager
 ↓
Batch-5 service/engine
 ↓
Existing engines / stores
 ↓
SQLite / FAISS / AI
 ↓
Result model
 ↓
UI
```

Heavy operations must never run on the GUI thread.

Use:

- `TaskManager`
- `ThreadManager`
- `QThreadPool`
- `AIResourceManager`
- existing DI `Container`
- `SignalBus`
- existing database migration mechanism

Do not create a second AI orchestration system.

---

# 5. Recommended Implementation Order

Implement in this order:

```text
Phase 0 — Stabilization
        ↓
B5-04 Exact Duplicates
        ↓
B5-05 Near Duplicates
        ↓
B5-06 Related Files
        ↓
B5-07 File Relationships
        ↓
B5-01 Classification
        ↓
B5-02 Auto-Tagging
        ↓
B5-09 Saved Semantic Searches
        ↓
B5-03 Smart Collections
        ↓
B5-08 Organization Suggestions
        ↓
B5-10 Knowledge Dashboard
        ↓
Full regression + E2E
```

This order follows the dependency structure found in the audit.

---

# 6. Phase 0 — Foundation and Migration

## 6.1 Database migration

Current schema version is 7.

Batch 5 should introduce **migration 8**.

Migration 8 should add only the objects actually required.

Recommended tables:

### `collections`

Suggested fields:

```text
id
name
description
criteria_json
is_smart
created_at
updated_at
```

### `collection_items`

```text
id
collection_id
file_path
added_at
source
```

Add uniqueness/indexes appropriate for collection membership.

### `saved_searches`

```text
id
name
query
scope
scope_path
modality
filters_json
created_at
updated_at
last_run
```

### `file_relationships`

```text
id
source_path
target_path
relationship_type
confidence
evidence_json
created_at
updated_at
```

Add a uniqueness constraint for the logical edge.

Controlled relationship types:

```text
related_to
duplicate_of
similar_to
references
derived_from
belongs_to_project
```

### `organization_suggestions`

```text
id
file_path
suggested_target
target_type
reason
confidence
status
created_at
updated_at
```

Recommended status values:

```text
pending
accepted
dismissed
expired
```

### Optional duplicate persistence

Do not create `duplicate_groups` unless persistent group identity is genuinely required.

Exact duplicate groups can initially be computed using:

```sql
GROUP BY checksum
HAVING COUNT(*) > 1
```

This avoids unnecessary state.

---

# 7. B5-04 — Exact Duplicate Detection

## Goal

Allow the user to discover files with identical content.

## Backend

Create:

```text
engines/duplicate_engine.py
```

or equivalent service under the existing architecture.

### Exact algorithm

1. Query indexed files.
2. Exclude invalid/empty checksum values.
3. Group by SHA-256.
4. Keep groups with count > 1.
5. Return structured duplicate groups.

Example result:

```python
DuplicateGroup(
    checksum="...",
    files=[...],
    total_files=3,
    total_size=...
)
```

### API

Provide operations such as:

```text
find_exact_duplicates()
find_exact_duplicates_for_file(path)
get_duplicate_group(checksum)
```

### UI

Add:

```text
Tools → Duplicate Files
```

and:

```text
File → AI → Find Duplicates
```

For a selected file, show:

```text
Exact Duplicates

file_a.pdf
file_b.pdf
file_c.pdf

Same SHA-256
Total copies: 3
```

Actions:

- Open
- Show in folder
- Copy path

Do not add deletion automation in this batch.

### Tests

Unit:

- same content → same group
- different content → different groups
- one file → no duplicate
- empty files → correct policy
- invalid checksum → excluded
- renamed identical file → still duplicate

Integration:

- database grouping
- watcher update
- deletion update

UI:

- dialog opens
- group displayed
- file selection works
- empty state works

---

# 8. B5-05 — Near-Duplicate Detection

## Goal

Detect highly similar files even when their SHA-256 hashes differ.

## Reuse

Use:

```text
RetrievalEngine.retrieve_similar()
VectorEngine
FAISS
existing evidence vectors
```

Do not re-embed files unnecessarily.

## File-level similarity

Current primitive:

```text
file
 ↓
average its chunk vectors
 ↓
FAISS search
 ↓
candidate chunks
 ↓
aggregate by target file
```

Turn this into a first-class file similarity API.

Suggested result:

```python
SimilarFileResult(
    file_path=...,
    score=...,
    matched_chunks=...,
    reason=...
)
```

## Thresholds

Add configurable thresholds.

Do not reuse the semantic-search High/Medium/Low labels as a duplicate threshold without calibration.

Recommended initial configurable values:

```text
near_duplicate_threshold = 0.90
similar_file_threshold = 0.75
```

These are starting defaults, not scientific constants. They must be validated using test fixtures.

## Scaling

Do NOT implement naïve all-pairs re-embedding.

Use:

- existing stored vectors
- FAISS candidate retrieval
- per-file aggregation
- top-N candidates
- configurable limits

## UI

Selected file:

```text
Find Similar Files
```

Display:

```text
Very Similar
Report_v2.pdf       94%
Report_final.pdf    91%

Related
ML_notes.pdf        81%
```

Clearly distinguish:

- Exact duplicate
- Near duplicate
- Related file

## Tests

- slightly modified text → high similarity
- unrelated documents → low similarity
- same file excluded
- threshold behavior
- multiple chunks
- multiple modalities where supported
- empty AI index → informative empty state
- large candidate set → bounded execution
- cancellation
- worker-thread execution

---

# 9. B5-06 — Related File Discovery

## Goal

Give the user a direct way to discover semantically related files.

## Backend

Build a thin `RelatedFileService` or extend `RetrievalEngine`.

Combine:

1. `retrieve_similar()`
2. semantic retrieval
3. graph `related_files()`
4. metadata/context where useful

Do not merge unrelated scoring systems blindly.

Return:

```text
file
score
relationship_reason
source
```

Example:

```text
CNN Research.pdf
Similarity: 0.91
Reason: Similar document content

Neural Networks Notes.pdf
Similarity: 0.84
Reason: Shared topics/entities
```

## UI

Add:

```text
File → AI → Find Related Files
```

Results should be clickable.

Use existing preview/open behavior.

## Tests

- related files returned
- source file excluded
- score ordering
- graph relation inclusion
- no duplicate result entries
- empty state
- deleted file excluded
- UI navigation

---

# 10. B5-07 — File-to-File Relationship Analysis

## Important architectural decision

The current Knowledge Graph has:

```text
ENTITY → ENTITY
```

It cannot directly represent:

```text
FILE → FILE
```

Do NOT modify the existing entity graph schema unnecessarily.

Recommended approach:

```text
Knowledge Graph
    ENTITY → ENTITY

File Relationship Layer
    FILE → FILE
```

Use a dedicated:

```text
file_relationships
```

table.

This keeps Batch-4 graph behavior stable.

## Relationship generation

Generate relationships from:

### Exact duplicates

```text
A --duplicate_of--> B
```

### Near duplicates

```text
A --similar_to--> B
```

### Related semantic content

```text
A --related_to--> B
```

### Shared graph entities

If two files strongly share entities/topics, create:

```text
A --related_to--> B
```

with evidence.

### Project membership

Use classification/graph information to infer:

```text
A --belongs_to_project--> Project-related-file
```

Only create this relationship when evidence is sufficient.

Do not fabricate references or derivation relationships.

## Evidence

Store enough provenance to explain why a relationship exists.

Example:

```text
Relationship:
A → similar_to → B

Confidence:
0.93

Reason:
12 highly similar evidence chunks

Evidence:
chunk IDs / source labels
```

## UI

Extend the existing Graph UI or add a focused file relationship view.

For a file:

```text
File Relationships

duplicate_of
    report_copy.pdf

similar_to
    report_v2.pdf

related_to
    machine_learning_notes.pdf
```

Clicking a relationship should open the target file.

## Synchronization

On file deletion:

```text
remove source relationships
remove target relationships
```

On reindex:

```text
recompute relationships where necessary
```

Do not leave stale edges.

## Tests

- exact duplicate creates `duplicate_of`
- near duplicate creates `similar_to`
- related file creates `related_to`
- invalid relationship rejected
- duplicate edge prevented
- deletion removes edges
- rename/move behavior
- confidence persisted
- evidence persisted
- restart persistence

---

# 11. B5-01 — Intelligent File Classification

## Goal

Give every analyzed file a consistent, searchable category.

## Current problem

`ai_analysis.category` is free-form:

```text
technical
Technical
```

This must be normalized.

## Controlled taxonomy

Define a project-level controlled taxonomy.

Example:

```text
document
code
image
audio
video
presentation
spreadsheet
research
education
project
business
personal
archive
other
```

The final taxonomy should be kept small and deterministic.

Do not let the LLM invent arbitrary categories.

## Classification pipeline

Reuse:

```text
AIService
AnalysisManager
prompt_builder
AICacheManager
```

Add a controlled classification layer.

Pipeline:

```text
File
 ↓
Existing AI analysis
 ↓
Classification prompt / deterministic rules
 ↓
Normalized category
 ↓
Persist
```

Where possible, avoid an additional LLM call if existing metadata is sufficient.

## Batch classification

Support:

```text
Classify File
Classify Folder
Classify Unclassified Files
```

Use:

- TaskManager
- progress
- cancellation
- AIResourceManager

Do not reprocess files whose content hash and classification version are unchanged.

## UI

Display category in:

- file preview
- indexed file list where practical
- classification dialog

Allow filtering by category.

## Tests

- taxonomy normalization
- technical/Technical → one category
- unsupported model output → `other`
- batch classification
- cancellation
- caching
- modified file reclassification
- deleted file cleanup

---

# 12. B5-02 — AI-Based Auto-Tagging

## Goal

Create consistent semantic tags.

## Current problem

Tags already exist but are:

- free-form
- not searchable
- only populated for 3 files
- not consolidated

## Tag architecture

Use:

```text
canonical tag
display name
normalized form
```

Normalization:

```text
Machine Learning
machine-learning
machine_learning
```

should resolve to one canonical tag where appropriate.

Avoid aggressive fuzzy merging that could destroy meaning.

## Backend

Extend AI analysis rather than creating a separate LLM stack.

Add:

```text
TaggingEngine
```

or integrate with ClassificationEngine.

Support:

```text
generate_tags(file)
normalize_tags(tags)
merge_tags(...)
remove_tag(...)
```

## User-facing behavior

Provide:

```text
AI → Auto-Tag File
AI → Auto-Tag Folder
```

Display tags as chips.

If user editing is included, it should be limited to:

- add
- remove
- rename/merge

No automatic destructive tag deletion.

## Tests

- tag generation
- normalization
- duplicate tag elimination
- tag persistence
- regeneration
- manual add/remove if implemented
- search/filter by tag
- modified-file behavior

---

# 13. B5-09 — Saved Semantic Searches

Implement before Smart Collections because Smart Collections can reuse saved-search criteria.

## Backend

Create:

```text
services/saved_search_manager.py
```

Responsibilities:

- create
- list
- get
- rename
- update
- delete
- execute

Persist:

```text
name
query
scope
scope_path
modality
filters
timestamps
```

Keep `search_history` as an activity log.

Do not convert history into saved searches.

## Re-run

When a saved search is executed:

```text
saved query
 ↓
current FAISS/evidence state
 ↓
current results
```

Do not persist stale result lists as the source of truth.

## UI

Extend `SemanticSearchDialog`:

```text
[Search]

[Save Search]
[Saved Searches]
```

Saved searches panel:

```text
⭐ Machine Learning Papers
⭐ MCA Project Files
⭐ Recent AI Research
```

Actions:

- Run
- Rename
- Delete

## Tests

- create
- persistence
- rename
- delete
- rerun
- current index reflected
- scope persistence
- modality persistence
- invalid saved query
- restart persistence

---

# 14. B5-03 — Smart Collections

## Goal

Create virtual collections without moving files.

## Collection types

### Static collection

User manually adds files.

### Smart collection

Membership is derived from criteria.

Example:

```text
Collection:
Machine Learning

Criteria:
category = research
AND
tag contains machine-learning
```

Another:

```text
MCA Project

Criteria:
semantic query = "files related to IntelliVault project"
```

## Backend

Create:

```text
CollectionEngine
```

Responsibilities:

- CRUD
- add/remove static member
- evaluate smart criteria
- validate membership
- refresh
- synchronize deleted files

## UI

Add:

```text
Tools → Collections
```

Recommended dock:

```text
Collections
────────────
⭐ Favorites
📁 MCA Project
🧠 Machine Learning
📚 Research Papers
```

Create collection dialog:

```text
Name
Description
Type:
  Static
  Smart

Criteria...
```

## Important

Collections are virtual.

Do not:

- copy files
- move files
- rename files

unless a later scope explicitly introduces physical file operations.

## Tests

- create/delete/rename
- static membership
- smart criteria
- duplicate membership prevention
- deleted file cleanup
- rename/move handling
- persistence
- empty collection
- UI refresh

---

# 15. B5-08 — AI Organization Suggestions

## Goal

Recommend logical organization without performing file operations.

## Inputs

Use:

- classification
- tags
- related files
- file relationships
- metadata
- existing folder distribution
- collections

## Suggestion algorithm

Prefer deterministic evidence before LLM reasoning.

Example:

```text
Selected file
 ↓
Find related files
 ↓
Find dominant folders/collections
 ↓
Determine category/topic
 ↓
Generate candidate targets
 ↓
Score candidates
 ↓
Optional LLM explanation
 ↓
Suggestion
```

Example result:

```text
Suggested organization

machine_learning_notes.pdf

Suggested collection:
Machine Learning

Confidence:
91%

Reason:
8 related files belong to this collection.
The file shares topics: neural networks, ML, Python.
```

## Safety

The LLM must not be allowed to invent arbitrary paths.

Suggestions should be based on existing indexed folders/collections.

## UI

```text
AI Organization Suggestions

File:
machine_learning_notes.pdf

Suggested:
📁 Machine Learning

Reason:
...

Confidence:
91%

[Accept]
[Dismiss]
```

Accepting a suggestion should update the virtual organization layer where possible.

It should NOT automatically move physical files.

## Tests

- suggestion generated
- confidence calculation
- grounded reason
- invalid target rejected
- accept
- dismiss
- persistence
- stale suggestion invalidation
- deleted file
- hallucination-resistant prompt behavior

---

# 16. B5-10 — Workspace Knowledge Dashboard

Implement last because it depends on all other Batch-5 subsystems.

## Backend

Create:

```text
services/dashboard_service.py
```

Compose existing queries rather than adding unnecessary database tables.

## Dashboard metrics

### File statistics

- total indexed files
- files by extension
- files by MIME/type
- recent files

### AI statistics

- analyzed files
- un-analyzed files
- categories
- tags
- keywords

### Semantic statistics

- AI indexed files
- evidence chunks
- vectors
- recent searches

### Duplicate statistics

- exact duplicate groups
- duplicate files
- near-duplicate groups where available

### Relationship statistics

- file relationships
- relationship types
- related-file count

### Collections

- total collections
- static collections
- smart collections
- membership count

### Graph

- entities
- relationships
- evidence links

### System status

- indexing state
- AI availability
- vector index integrity
- watcher status

## UI

Add:

```text
Tools → Knowledge Dashboard
```

Recommended layout:

```text
┌─────────────────────────────────────────────┐
│ Knowledge Dashboard                         │
├─────────────────────────────────────────────┤
│ Files      AI Analyzed     Duplicates       │
│ 89         32              5 groups         │
├─────────────────────────────────────────────┤
│ Categories                                  │
│ Research  24 | Code 18 | Documents 31 ...  │
├─────────────────────────────────────────────┤
│ Top Tags                                    │
│ Python | AI | Research | MCA ...            │
├─────────────────────────────────────────────┤
│ Relationships       Collections             │
│ 127                   8                     │
├─────────────────────────────────────────────┤
│ Recent Activity                             │
└─────────────────────────────────────────────┘
```

## Empty states

If AI index is empty:

```text
AI indexing has not been performed yet.

Run "Index for AI" to populate semantic statistics.
```

Never display misleading zeros as if the system has no knowledge.

## Tests

- aggregation accuracy
- category counts
- tag counts
- duplicate counts
- relationship counts
- collection counts
- graph counts
- empty state
- stale-file exclusion
- performance
- UI rendering

---

# 17. UI Integration Plan

## Tools menu

Add:

```text
Tools
 ├── Workspace Chat
 ├── Knowledge Graph
 ├── Conversation History
 ├── Agent Mode
 ├── Collections
 ├── Duplicate Files
 ├── Saved Searches
 ├── Knowledge Dashboard
 └── Settings
```

Do not disrupt existing menu actions.

## Explorer AI submenu

Add:

```text
AI
 ├── Analyze File
 ├── View Analysis
 ├── Regenerate Analysis
 ├── Semantic Search
 ├── Ask AI about this File
 ├── Chat with this Folder
 ├── Classify File
 ├── Auto-Tag File
 ├── Find Duplicates
 └── Find Related Files
```

Use separators if needed for readability.

## Preview panel

Add:

```text
Category
Tags
Related Files
Duplicate Status
```

Only display data when available.

---

# 18. DI Container Integration

Extend `app/container.py`.

Recommended lazy services:

```text
duplicate_engine
related_file_service
relationship_engine
classification_engine
tagging_engine
collection_engine
saved_search_manager
suggestion_engine
dashboard_service
```

Use lazy initialization.

Do not instantiate all AI-heavy services during application startup.

---

# 19. SignalBus Integration

Add narrowly scoped signals such as:

```text
classification_updated
tags_updated
duplicates_updated
relationships_updated
collection_updated
saved_search_updated
organization_suggestion_updated
dashboard_refresh_requested
```

Do not create redundant signals where existing file/index signals can be reused.

---

# 20. Error Handling Requirements

Every Batch-5 subsystem must handle:

- missing file
- deleted file
- permission error
- corrupt file
- empty file
- missing AI index
- FAISS unavailable
- Ollama unavailable
- invalid LLM JSON
- database failure
- cancellation
- timeout
- stale relationship
- stale collection membership

UI should show user-actionable messages.

Avoid silently converting serious failures into empty success results.

---

# 21. Performance Requirements

Target machine:

```text
Intel i3-N305
~6.9 GiB RAM
CPU-only
```

Rules:

1. No heavy operation on GUI thread.
2. Reuse existing embeddings.
3. Do not re-embed unchanged files.
4. Batch LLM calls where practical.
5. Use `AIResourceManager`.
6. Use progress reporting for long operations.
7. Support cancellation.
8. Avoid O(n²) comparisons where FAISS candidate search can be used.
9. Dashboard queries must not scan the unbounded `tasks` table.
10. Do not load entire large collections into widgets at once.

---

# 22. Testing Strategy

Batch 5 should add tests without weakening the existing 261-test baseline.

Target:

```text
Existing:
261

New Batch-5 tests:
~100+ recommended

Final:
All existing + all Batch-5 tests pass
```

Exact test count may vary; behavior coverage matters more than the number.

---

# 23. Unit-Test Plan

## File identity

- SHA-256
- empty file
- missing file
- read failure

## DuplicateEngine

- grouping
- no duplicates
- empty duplicate policy
- checksum filtering

## Similarity

- score calculation
- threshold
- candidate aggregation
- source exclusion

## Classification

- taxonomy
- normalization
- fallback category

## Tagging

- normalization
- consolidation
- duplicate removal

## Relationships

- allowed relationship types
- confidence
- duplicate edge prevention
- evidence serialization

## Collections

- CRUD
- membership
- criteria evaluation

## Saved searches

- CRUD
- serialization
- re-run configuration

## Suggestions

- candidate generation
- scoring
- validation
- accept/dismiss

## Dashboard

- every aggregate
- empty state
- stale-file exclusion

---

# 24. Integration-Test Plan

## Exact duplicates

```text
create files
 ↓
index
 ↓
detect duplicates
 ↓
modify/delete
 ↓
detect again
```

Expected: results remain synchronized.

## Near duplicates

```text
index documents
 ↓
modify one
 ↓
re-index
 ↓
similarity search
```

Expected: correct score and target.

## Relationships

```text
duplicate/similar/related files
 ↓
build relationship
 ↓
persist
 ↓
restart
 ↓
query
```

Expected: relationship survives restart.

## Classification + tags

```text
file
 ↓
AI analysis
 ↓
classification
 ↓
tagging
 ↓
persist
 ↓
restart
```

## Collections

```text
create smart collection
 ↓
index matching file
 ↓
collection membership changes
```

## Saved search

```text
save query
 ↓
add new matching file
 ↓
rerun
```

Expected: new file appears.

## Suggestions

```text
classification
+ related files
+ collections
 ↓
suggestion
 ↓
accept/dismiss
 ↓
restart
```

## Dashboard

Verify every count against direct database queries.

---

# 25. UI Test Plan

Test:

- Tools menu entries
- context-menu entries
- dialogs opening
- loading state
- progress state
- cancellation
- empty state
- error state
- result selection
- file opening
- navigation
- restart persistence
- no GUI freeze

Existing Batch-4 UI behavior must remain intact.

---

# 26. End-to-End Test Scenarios

## E2E-01 — Duplicate workflow

```text
Create two identical files
 ↓
Index
 ↓
Tools → Duplicate Files
 ↓
Open duplicate group
 ↓
Open file
```

## E2E-02 — Related-file workflow

```text
Select file
 ↓
AI → Find Related Files
 ↓
Select result
 ↓
Preview target
```

## E2E-03 — Classification workflow

```text
Select file
 ↓
AI → Classify
 ↓
Category appears
 ↓
Restart
 ↓
Category remains
```

## E2E-04 — Smart collection

```text
Create smart collection
 ↓
Define criteria
 ↓
Run
 ↓
Matching files appear
 ↓
Add another matching file
 ↓
Refresh
 ↓
New file appears
```

## E2E-05 — Saved semantic search

```text
Search
 ↓
Save Search
 ↓
Restart
 ↓
Run Saved Search
 ↓
Current results returned
```

## E2E-06 — Organization suggestion

```text
Select file
 ↓
Generate suggestion
 ↓
Inspect reason/confidence
 ↓
Accept
 ↓
Collection membership changes
```

## E2E-07 — Dashboard

```text
Index workspace
 ↓
Open Dashboard
 ↓
Verify counts
 ↓
Modify/delete file
 ↓
Refresh
 ↓
Counts update
```

---

# 27. Regression Requirements

After every milestone:

```bash
pytest -q
```

The baseline must remain:

```text
0 failures
0 errors
0 skipped
```

No Batch-5 implementation is complete if existing Batch-1–4 tests regress.

---

# 28. Recommended Milestone Structure

## Milestone 0 — Stabilization

Deliver:

- deletion reconciliation
- checksum index
- SHA-256 helper
- empty-file policy
- migration 8 foundation
- regression tests

Definition of Done:

- old tests pass
- deletion produces no stale indexed row

---

## Milestone 1 — Exact Duplicates

Deliver:

- DuplicateEngine
- database index
- exact duplicate query
- UI
- tests

---

## Milestone 2 — Near Duplicates

Deliver:

- file-level similarity API
- threshold configuration
- aggregation
- UI
- tests

---

## Milestone 3 — Related Files

Deliver:

- RelatedFileService/API
- per-file UI
- graph-assisted explanations
- tests

---

## Milestone 4 — File Relationships

Deliver:

- `file_relationships`
- RelationshipEngine
- synchronization
- relationship UI
- evidence
- tests

---

## Milestone 5 — Classification

Deliver:

- controlled taxonomy
- batch classification
- normalized category
- UI
- tests

---

## Milestone 6 — Auto-Tagging

Deliver:

- normalized tags
- batch tagging
- tag UI/filter
- tests

---

## Milestone 7 — Saved Searches

Deliver:

- saved search persistence
- manager
- SemanticSearchDialog integration
- tests

---

## Milestone 8 — Smart Collections

Deliver:

- CollectionEngine
- static collections
- smart criteria
- Collections UI
- synchronization
- tests

---

## Milestone 9 — Organization Suggestions

Deliver:

- SuggestionEngine
- evidence-grounded scoring
- accept/dismiss
- persistence
- tests

---

## Milestone 10 — Dashboard

Deliver:

- DashboardService
- aggregation
- Dashboard UI
- empty states
- tests

---

## Milestone 11 — Final Integration

Run:

- full unit tests
- integration tests
- UI tests
- E2E tests
- regression tests
- startup test
- persistence/restart test
- deletion/reconciliation test
- performance smoke tests

---

# 29. Definition of Done — Individual Feature

A Batch-5 feature is complete only when all are true:

- backend implemented
- database persistence implemented where required
- DI integration completed
- TaskManager integration completed
- UI entry point exists
- loading state exists
- empty state exists
- error state exists
- cancellation exists for long operations
- unit tests pass
- integration tests pass
- UI tests pass where applicable
- restart persistence verified where applicable
- file deletion synchronization verified
- no existing Batch-1–4 regression

---

# 30. Definition of Done — Batch 5

Batch 5 is complete only when:

### Functionality

All 10 frozen features are implemented and directly usable.

### Architecture

- no duplicate AI stack
- no duplicate vector-search stack
- existing Batch-3/4 engines reused
- DI integration complete
- worker architecture preserved

### Data

- migration 8 applied
- all Batch-5 tables indexed appropriately
- stale-file cleanup works
- relationship cleanup works
- collection cleanup works

### UI

All 10 features have clear user-visible entry points.

### Reliability

- cancellation works
- errors are surfaced
- no GUI freezes
- no stale duplicate/relationship/collection data

### Performance

- no naïve O(n²) embedding pipeline
- no repeated embedding of unchanged files
- AI concurrency respects `AIResourceManager`

### Tests

All previous tests + Batch-5 tests pass.

Target:

```text
0 failed
0 errors
0 skipped
```

### Persistence

Restarting IntelliVault must preserve:

- classifications
- tags
- collections
- saved searches
- file relationships
- organization suggestions
- dashboard-derived state where persistent
- duplicate/relationship data where persisted

---

# 31. Final Architecture After Batch 5

```text
                         IntelliVault
                              │
                    ┌─────────┴─────────┐
                    │                   │
                   UI                SignalBus
                    │                   │
                    └─────────┬─────────┘
                              │
                         TaskManager
                              │
              ┌───────────────┼────────────────┐
              │               │                │
        Organization      Retrieval        Dashboard
          Layer             Layer            Layer
              │               │                │
      ┌───────┼───────┐       │        ┌───────┼──────┐
      │       │       │       │        │       │      │
Classification Tags Collections   FAISS    DB     Graph
      │       │       │       │        │       │      │
      └───────┴───────┴───────┴────────┴───────┴──────┘
                              │
                       Existing Batch 1–4
                              │
                ┌─────────────┼─────────────┐
                │             │             │
             Scanner       AI/RAG        Knowledge
             Metadata      Retrieval        Graph
             Extraction    Conversations     Agent
```

The key architectural distinction is:

```text
Knowledge Graph:
ENTITY → ENTITY

File Relationship Layer:
FILE → FILE
```

This avoids destabilizing the Batch-4 graph implementation.

---

# 32. Final Implementation Checklist

## Foundation

- [ ] Migration 8
- [ ] deleted-file reconciliation
- [ ] checksum index
- [ ] SHA-256 helper
- [ ] empty-file policy
- [ ] Batch-5 settings

## B5-04

- [ ] DuplicateEngine
- [ ] exact duplicate query
- [ ] duplicate UI
- [ ] tests

## B5-05

- [ ] file similarity API
- [ ] threshold
- [ ] aggregation
- [ ] near-duplicate UI
- [ ] tests

## B5-06

- [ ] RelatedFileService
- [ ] per-file entry point
- [ ] ranking/reason
- [ ] tests

## B5-07

- [ ] file_relationships schema
- [ ] RelationshipEngine
- [ ] evidence/provenance
- [ ] synchronization
- [ ] UI
- [ ] tests

## B5-01

- [ ] taxonomy
- [ ] classification engine
- [ ] batch operation
- [ ] UI
- [ ] tests

## B5-02

- [ ] tag normalization
- [ ] TaggingEngine
- [ ] batch operation
- [ ] UI
- [ ] tests

## B5-09

- [ ] saved_searches
- [ ] SavedSearchManager
- [ ] UI
- [ ] rerun
- [ ] tests

## B5-03

- [ ] collections
- [ ] CollectionEngine
- [ ] static collections
- [ ] smart collections
- [ ] UI
- [ ] synchronization
- [ ] tests

## B5-08

- [ ] SuggestionEngine
- [ ] evidence-grounded candidates
- [ ] confidence
- [ ] accept/dismiss
- [ ] UI
- [ ] tests

## B5-10

- [ ] DashboardService
- [ ] aggregate queries
- [ ] dashboard UI
- [ ] empty states
- [ ] tests

## Final

- [ ] full regression
- [ ] E2E
- [ ] restart persistence
- [ ] deletion reconciliation
- [ ] performance smoke test
- [ ] final Batch-5 audit
- [ ] verify all 10 features are directly usable
