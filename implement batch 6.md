# IntelliVault — Batch 6 Complete Implementation Plan
## Completing the Five Partially Implemented Features

**Baseline:** Post-Batch-5 Current-State Audit (`batch6_audit_report.md`)  
**Scope:** Exactly the 5 features classified as PARTIAL by the latest audit  
**Next step after Batch 6:** Fresh current-state audit, followed by Batch 7 planning for the remaining NOT IMPLEMENTED features

---

# 1. Batch 6 Objective

Batch 6 completes the five IntelliVault features that already have meaningful backend or related functionality but are not yet complete end-to-end.

The five features are:

1. **#7 — Image Caption Generation**
2. **#16 — AI Folder Classification**
3. **#18 — Natural Language Search Filters**
4. **#25 — Smart Duplicate Removal Suggestions**
5. **#29 — Automatic Folder Organization**

The goal is not merely to add code. Each feature must become a complete, user-facing capability with:

- backend implementation
- UI integration
- persistence where required
- synchronization with existing file/index state
- background processing where appropriate
- error handling
- unit tests
- integration tests
- regression verification

The existing IntelliVault architecture must be extended rather than duplicated.

---

# 2. Source-of-Truth Baseline

The latest audit reports:

- 15 / 31 features fully implemented
- 5 / 31 features partially implemented
- 11 / 31 features not implemented
- 0 broken
- 0 unverified
- 324 / 324 tests passing
- SQLite schema version 8
- 89 indexed files in the live database
- Batch 5 persistence is verified
- Batch 5 organization infrastructure is already present

The audit identifies the five partial features and their existing infrastructure as follows:

| Feature | Existing capability | Missing completion |
|---|---|---|
| Image Caption Generation | `VisionEngine.caption_image()` / `caption_frame()` | Standalone user-facing caption workflow, persistence/display, tests |
| AI Folder Classification | File-level `classification_engine` | Folder-level aggregation/classification and UI |
| Natural Language Search Filters | Semantic search + modality/type/scope filtering | Natural-language parsing into structured filters |
| Smart Duplicate Removal Suggestions | Duplicate detection + `suggestion_engine` | Safe removal recommendations and UI workflow |
| Automatic Folder Organization | Organization suggestions | Actual approved move-to-folder workflow |

Do not replace these existing systems with parallel implementations.

---

# 3. Mandatory Development Rules

## 3.1 Do not break existing functionality

The following must continue working:

- folder navigation
- file selection
- preview
- metadata
- extracted text
- indexing
- file watcher
- AI analysis
- semantic search
- Ask AI
- conversations
- folder/workspace chat
- knowledge graph
- agentic workflows
- classification
- tagging
- smart collections
- duplicate detection
- near-duplicate detection
- related files
- file relationships
- organization suggestions
- saved searches
- dashboard

## 3.2 Preserve existing architecture

Reuse:

- `VisionEngine`
- `classification_engine`
- `RetrievalEngine`
- existing semantic-search dialog
- `DuplicateEngine`
- `file_similarity`
- `suggestion_engine`
- `Batch5Store`
- `file_cleanup`
- `file_identity`
- `SignalBus`
- DI `Container`
- existing worker/task infrastructure

Do not create duplicate engines for capabilities that already exist.

## 3.3 Preserve SHA-256 identity

File identity is based on SHA-256.

Any feature that moves, renames, or removes files must preserve or correctly update all associated state.

## 3.4 Do not automatically delete or move files without explicit user approval

Batch 6 introduces file-operation capabilities.

The safe rule is:

**AI recommends → user reviews → user explicitly approves → operation executes → system synchronizes indexes.**

No silent destructive operations.

## 3.5 Preserve the 324/324 test baseline

Before implementation:

- run the existing suite
- record the baseline

After every milestone:

- run relevant tests
- run the complete regression suite

The final Batch 6 target is:

**all existing tests + all new Batch 6 tests passing.**

---

# 4. Batch 6 Architecture Strategy

Batch 6 extends existing architecture rather than introducing a new AI stack.

```text
Existing IntelliVault
        |
        +----------------------+
        |                      |
        v                      v
 Existing AI / Search      Existing Organization
        |                      |
        v                      v
 Batch 6 completion      Batch 6 completion
        |                      |
        +----------+-----------+
                   |
                   v
            Existing SQLite
                   |
                   v
             Existing Sync
                   |
                   v
              Existing UI
```

The five features should share existing services wherever possible.

---

# 5. Milestone 0 — Baseline Verification

Before changing code, run:

```bash
python -m pytest -q
```

or the repository's established test command.

Record:

- total tests
- passed
- failed
- skipped
- errors
- warnings

Expected baseline from the audit:

```text
324 passed
0 failed
0 skipped
0 errors
```

Also verify:

- application starts
- MainWindow constructs
- database opens
- existing Batch 5 actions are available
- semantic search dialog opens
- duplicate dialog opens
- organization suggestion dialog opens

Do not proceed if the baseline unexpectedly regresses.

---

# 6. Milestone 1 — Image Caption Generation

## 6.1 Current State

The audit confirms:

- `vision/vision_engine.py`
- `VisionEngine.caption_image()`
- `VisionEngine.caption_frame()`

already exist.

Captioning is currently used during AI indexing for embedded images/PDF pages and video keyframes.

The missing capability is a dedicated user-facing action for captioning an image directly.

---

## 6.2 Target User Experience

User selects an image.

```text
File
  ↓
AI
  ↓
Caption Image
```

The system:

```text
Selected Image
      ↓
VisionEngine.caption_image()
      ↓
Generated Caption
      ↓
Persist
      ↓
Display
```

The caption should be visible without requiring the user to run the complete AI indexing pipeline.

---

## 6.3 UI Requirements

Add a context-menu action:

**File → AI → Caption Image**

Only enable it for supported image files.

Possible result presentation:

- caption text
- image preview
- processing state
- error state
- regenerate option

Do not redesign the existing preview UI.

Prefer extending the existing AI/result presentation patterns.

---

## 6.4 Backend Requirements

Reuse:

```text
VisionEngine.caption_image()
```

Do not implement a second image-captioning engine.

Add a thin orchestration/service layer if needed to:

1. validate image
2. call VisionEngine
3. associate result with file identity
4. persist result
5. notify UI

---

## 6.5 Persistence

The caption should be associated with the file.

Preferred approach:

- reuse existing AI/content/evidence storage where semantically appropriate
- avoid creating a new table if an existing model can represent the caption cleanly

The implementation must define:

- file identity
- caption text
- model/version if required
- generated timestamp
- replacement/regeneration behavior

The same caption should remain associated with the same content identity after rename/move.

---

## 6.6 Error Handling

Handle:

- unsupported image
- unreadable image
- missing vision model
- Ollama unavailable
- model timeout
- empty model response
- malformed model response

The UI must show a useful failure message and leave existing metadata untouched.

---

## 6.7 Background Processing

Caption generation may involve LLM inference.

Do not block the main GUI thread.

Use the existing background task/resource-management architecture.

---

## 6.8 Tests

### Unit tests

- valid image → caption
- invalid image
- missing model
- Ollama failure
- empty caption response
- caption persistence
- caption regeneration

### Integration tests

- UI action → service → VisionEngine → persistence
- rename image → caption remains associated
- re-caption replaces prior result correctly

### Regression

Run complete suite.

---

# 7. Milestone 2 — AI Folder Classification

## 7.1 Current State

File-level classification already exists.

Existing infrastructure:

```text
classification_engine
normalized_category
classification_version
classified_at
ai_analysis
```

The missing capability is folder-level classification.

---

## 7.2 Definition

Folder classification should summarize the content composition of a folder rather than independently classifying every file again.

Example:

```text
MCA Project/

Documents:     62%
Presentations: 18%
Code:          15%
Images:         5%

Dominant Category:
Document
```

The system should reuse existing file classifications.

---

## 7.3 Classification Strategy

Do not call the LLM for every file again.

Use:

```text
Folder
  ↓
Indexed files
  ↓
Existing file classifications
  ↓
Aggregate categories
  ↓
Determine dominant category
  ↓
Generate folder classification metadata
```

Optional AI reasoning can be used only where necessary.

---

## 7.4 Folder-Level Data Model

Define a stable representation for:

- folder path
- dominant category
- category distribution
- classified file count
- unclassified file count
- classification version
- generated timestamp

Prefer extending an existing folder metadata mechanism if one is appropriate.

If a new persistence structure is required, add it through a migration.

---

## 7.5 UI

Add folder-level information to the existing folder properties/statistics area.

Possible display:

```text
Folder Intelligence

Primary Category: Academic Documents

Category Distribution:
Documents      62%
Presentations  18%
Code           15%
Images          5%

Files Analyzed: 89
```

Do not create a completely separate dashboard unless required.

---

## 7.6 Refresh Behavior

When files are:

- added
- removed
- renamed
- moved
- reclassified

folder classification must update or be marked stale.

Use existing SignalBus/file synchronization mechanisms.

---

## 7.7 Tests

### Unit

- empty folder
- one-category folder
- mixed-category folder
- unclassified files
- category aggregation
- dominant category selection

### Integration

- index folder → classification
- add file → classification updates
- delete file → classification updates
- move file → source and destination folder classifications update
- restart → classification persists

---

# 8. Milestone 3 — Natural Language Search Filters

## 8.1 Current State

Semantic Search already supports:

- semantic query
- modality/type filtering
- scope selection

The missing capability is interpreting natural-language constraints.

Example:

> Find PDF files about machine learning modified this month larger than 5 MB.

---

## 8.2 Target Architecture

```text
Natural Language Query
          ↓
Filter Parser
          ↓
Structured Search Query
          ↓
Existing Semantic Search
          ↓
Existing RetrievalEngine
          ↓
Results
```

Do not replace the existing semantic retrieval engine.

The filter layer should preprocess the query and pass structured constraints to existing search functionality.

---

## 8.3 Supported Filter Vocabulary

Initial Batch 6 implementation should support a controlled set of filters:

### File type

Examples:

- PDF
- DOCX
- PPTX
- image
- audio
- video

### Extension

Examples:

- `.pdf`
- `.docx`
- `.png`

### Date

Examples:

- today
- yesterday
- this week
- this month
- this year
- after DATE
- before DATE

### Size

Examples:

- larger than 5 MB
- smaller than 10 MB
- between 1 MB and 5 MB

### Location/scope

Examples:

- in this folder
- in this workspace

### Semantic content

The remaining natural-language text remains the semantic query.

---

## 8.4 Parsing Strategy

Prefer deterministic parsing for simple filters.

Example:

```text
"PDF files about machine learning modified this month"
```

becomes:

```json
{
  "semantic_query": "machine learning",
  "extension": ["pdf"],
  "modified_after": "...",
  "modified_before": "...",
  "scope": "current"
}
```

Use an LLM only if needed for ambiguous or complex natural-language parsing.

Do not send the entire document collection to an LLM.

---

## 8.5 Search Execution

The filter layer should:

1. parse query
2. validate filters
3. execute metadata filtering
4. perform semantic retrieval over the appropriate candidate set
5. rank results
6. display parsed filters to the user

The final search must continue using the existing retrieval architecture.

---

## 8.6 UI

Extend the existing Semantic Search dialog.

Display parsed constraints, for example:

```text
Query:
machine learning

Filters:
Type: PDF
Modified: This Month
Size: > 5 MB
```

Allow the user to remove/edit filters if practical.

Do not redesign the dialog.

---

## 8.7 Ambiguity Handling

If the system cannot confidently parse a constraint:

- do not silently apply a wrong filter
- preserve the text as part of the semantic query
- optionally show the interpreted filters
- allow user correction

---

## 8.8 Tests

### Unit

Test parsing:

- PDF
- DOCX
- images
- date ranges
- relative dates
- size constraints
- multiple filters
- invalid sizes
- ambiguous phrases

### Integration

- natural-language query → filters → semantic retrieval
- scope + filter
- modality + filter
- saved-search compatibility

### Regression

Existing semantic search behavior must remain unchanged for ordinary queries.

---

# 9. Milestone 4 — Smart Duplicate Removal Suggestions

## 9.1 Current State

Duplicate detection is already implemented:

- exact duplicates via SHA-256
- near duplicates via similarity
- `file_relationships`
- Duplicate Files dialog

The missing feature is a recommendation layer that identifies which redundant file is safer to remove.

---

## 9.2 Safety Principle

This feature must NOT automatically delete files.

Target workflow:

```text
Duplicate Group
      ↓
Analyze candidates
      ↓
Recommend removable copy
      ↓
Explain recommendation
      ↓
User reviews
      ↓
User explicitly approves
      ↓
Safe removal
```

---

## 9.3 Recommendation Factors

For exact duplicates, possible factors include:

- same SHA-256
- filename quality
- path
- modification time
- file size
- extension
- whether one copy appears to be a temporary/duplicate naming variant

For near duplicates:

- similarity score
- content completeness
- modification time
- path
- filename

Do not claim that usage history is available unless the current codebase actually records reliable usage data.

---

## 9.4 Suggestion Model

Extend the existing `suggestion_engine`.

A duplicate-removal suggestion should contain:

- source file
- recommended action
- keep/remove candidate
- reason
- confidence
- duplicate type
- similarity/checksum evidence
- status
- created/updated time

Statuses should include at minimum:

```text
PENDING
ACCEPTED
DISMISSED
```

If the system executes removal, add an execution state if necessary.

---

## 9.5 UI

Extend the existing Duplicate Files dialog.

Example:

```text
Duplicate Group

Keep:
report_final.pdf

Suggested removal:
report_final_copy.pdf

Reason:
• Identical SHA-256
• Same file size
• Copy-style filename

Confidence:
98%

[Review] [Accept Suggestion] [Dismiss]
```

For safety, the final removal action should require explicit confirmation.

---

## 9.6 Removal Mechanism

Do not directly delete files from arbitrary code.

Use a centralized safe file-operation path.

Preferred behavior:

```text
Approve
  ↓
Move to Trash / reversible location
  ↓
File watcher detects change
  ↓
file_cleanup
  ↓
SQLite/relationships/collections/suggestions synchronized
```

If a true Trash implementation is not available in the current architecture, implement the safest reversible mechanism supported by the platform rather than permanent deletion.

---

## 9.7 Tests

### Unit

- exact duplicate recommendation
- near duplicate recommendation
- no duplicate
- ambiguous duplicate
- confidence calculation
- accept/dismiss state

### Integration

- duplicate detection → suggestion
- accept → safe file operation
- operation → cleanup
- cleanup → relationships updated
- cleanup → collections updated
- restart → no stale file

### Safety tests

- reject suggestion → no file operation
- invalid target → no deletion
- missing file → graceful handling
- source/target same path → reject
- permission error → safe failure

---

# 10. Milestone 5 — Automatic Folder Organization

## 10.1 Current State

Batch 5 already provides organization suggestions.

Current behavior:

```text
File
 ↓
SuggestionEngine
 ↓
Suggested target
```

It does not move files.

Batch 6 adds the execution layer.

---

## 10.2 Safety Principle

Automatic organization must be user-approved.

Target:

```text
Analyze
  ↓
Suggest
  ↓
Preview changes
  ↓
User approves
  ↓
Move
  ↓
Synchronize
```

Do not silently move files merely because an AI suggestion has high confidence.

---

## 10.3 Target Selection

Reuse the existing organization suggestion logic.

Do not invent arbitrary directories without a clear rule.

Potential targets may be:

- existing folders
- existing organization destinations
- user-approved folders
- explicitly configured destination structures

The user must be able to see the target before execution.

---

## 10.4 Organization Preview

Provide a preview such as:

```text
Organization Preview

document1.pdf
  Current:
    /Downloads/

  Target:
    /Documents/Academic/

image1.png
  Current:
    /Downloads/

  Target:
    /Pictures/Research/

[Approve All]
[Approve Selected]
[Cancel]
```

---

## 10.5 Move Execution

Create or reuse a centralized file-operation service.

Responsibilities:

1. validate source
2. validate destination
3. prevent collisions
4. preserve file content
5. perform move
6. report success/failure
7. trigger synchronization

---

## 10.6 Collision Handling

Handle:

- destination already contains same filename
- destination does not exist
- permission denied
- source disappeared
- source modified between suggestion and execution

Never overwrite silently.

Possible policies:

- skip
- rename destination safely
- ask user

---

## 10.7 Synchronization

After a successful move:

```text
File Move
   ↓
Watcher / explicit sync
   ↓
indexed_files update
   ↓
SHA-256 identity preserved
   ↓
AI metadata preserved
   ↓
evidence/vector mappings updated
   ↓
file relationships updated
   ↓
collections updated
   ↓
organization suggestions updated
   ↓
dashboard refreshed
```

Reuse the existing file synchronization and cleanup infrastructure.

---

## 10.8 Tests

### Unit

- valid move
- invalid source
- invalid destination
- collision
- permission error
- same source/destination
- missing source

### Integration

- suggestion → preview → approval → move
- move → database synchronization
- move → relationship synchronization
- move → collection synchronization
- move → AI metadata remains associated
- move → restart

### Safety

- cancellation causes no move
- rejected suggestion causes no move
- failed move does not corrupt DB
- partial batch failure leaves remaining items actionable

---

# 11. Cross-Feature Synchronization Requirements

Because Batch 6 modifies or analyzes files at a higher level, all five features must respect the existing synchronization architecture.

The system must correctly handle:

- create
- modify
- rename
- move
- delete

For affected features, verify:

```text
indexed_files
ai_analysis
evidence
vector_map
FAISS
file_relationships
collections
organization_suggestions
folder classification
captions
```

Do not duplicate cleanup logic.

Use the existing `file_cleanup` orchestration where applicable.

---

# 12. Database / Migration Strategy

Before adding any table or column:

1. inspect existing schema
2. determine whether an existing model can store the data
3. avoid redundant tables
4. add a migration only when necessary
5. preserve backward compatibility

The current schema is version 8.

If Batch 6 requires schema changes:

```text
v8 → v9
```

with:

- idempotent migration
- safe upgrade
- existing data preserved
- rollback/recovery strategy where practical
- migration test

Do not change schema merely for convenience.

---

# 13. UI Integration Strategy

Use existing UI extension points:

- File → AI submenu
- Tools menu
- Semantic Search dialog
- Duplicate dialog
- Organization Suggestion dialog
- Preview panel
- Folder properties/statistics
- existing dialogs and progress patterns

Avoid creating multiple competing entry points for the same feature.

---

# 14. Background Processing

Potentially expensive operations:

- image caption generation
- large-folder classification
- natural-language filter parsing if an LLM is used
- large duplicate recommendation scans
- bulk organization

must not unnecessarily block the GUI.

Reuse:

- `ThreadManager`
- `TaskManager`
- `AIResourceManager`
- existing worker patterns
- cancellation/progress signals

Heavy local AI operations should continue to respect the existing resource manager so multiple large models do not load concurrently on constrained hardware.

---

# 15. Error Handling Requirements

Every Batch 6 feature must handle:

- missing file
- inaccessible file
- corrupted file
- unsupported format
- missing AI model
- Ollama unavailable
- timeout
- malformed LLM output
- invalid filter
- database failure
- file operation failure
- destination collision
- cancellation
- stale suggestion

Errors must:

- not crash the application
- not silently corrupt state
- provide useful UI feedback
- log enough diagnostic information
- leave the system recoverable

---

# 16. Testing Strategy

## 16.1 Unit Tests

Create focused tests for each feature.

Suggested files:

```text
tests/test_batch6_captioning.py
tests/test_batch6_folder_classification.py
tests/test_batch6_nl_filters.py
tests/test_batch6_duplicate_suggestions.py
tests/test_batch6_folder_organization.py
```

Names may be adapted to the existing test organization.

---

## 16.2 Integration Tests

Test complete flows:

```text
UI
 ↓
Service
 ↓
Engine
 ↓
Database
 ↓
Result
```

---

## 16.3 Persistence Tests

Verify after restart:

- captions
- folder classifications
- saved/parsed search state if persisted
- duplicate suggestions
- organization suggestion state
- file-operation results

---

## 16.4 File Synchronization Tests

For any affected file:

```text
Create
Modify
Rename
Move
Delete
Re-index
Restart
```

Verify no stale records.

---

## 16.5 Regression Suite

After every milestone:

```bash
python -m pytest -q
```

Final requirement:

```text
0 failed
0 errors
0 unexpected skips
```

No previously passing feature may regress.

---

# 17. Implementation Order

The recommended order is:

## Phase 0
Baseline and stabilization

## Phase 1
Image Caption Generation

## Phase 2
AI Folder Classification

## Phase 3
Natural Language Search Filters

## Phase 4
Smart Duplicate Removal Suggestions

## Phase 5
Automatic Folder Organization

## Phase 6
Cross-feature synchronization verification

## Phase 7
Complete regression and acceptance testing

This order minimizes dependency risk.

---

# 18. Detailed Milestone Checklist

## Milestone 0 — Baseline

- [ ] Run full test suite
- [ ] Confirm 324/324 baseline
- [ ] Confirm application boots
- [ ] Confirm database opens
- [ ] Confirm Batch 5 UI works
- [ ] Record environment/dependency state

## Milestone 1 — Captioning

- [ ] Add Caption Image action
- [ ] Reuse VisionEngine
- [ ] Add background execution
- [ ] Persist caption
- [ ] Display caption
- [ ] Regeneration
- [ ] Error handling
- [ ] Unit tests
- [ ] Integration tests

## Milestone 2 — Folder Classification

- [ ] Reuse file classification
- [ ] Aggregate folder categories
- [ ] Define folder classification model
- [ ] Add persistence if required
- [ ] Add folder UI
- [ ] Refresh on file changes
- [ ] Restart test
- [ ] Unit tests
- [ ] Integration tests

## Milestone 3 — NL Filters

- [ ] Define filter schema
- [ ] Implement deterministic parser
- [ ] Support type/extension
- [ ] Support date
- [ ] Support size
- [ ] Support scope
- [ ] Preserve semantic query
- [ ] Integrate with RetrievalEngine
- [ ] Display parsed filters
- [ ] Test ambiguous input
- [ ] Test saved searches
- [ ] Regression tests

## Milestone 4 — Duplicate Removal Suggestions

- [ ] Extend suggestion engine
- [ ] Define recommendation model
- [ ] Define confidence
- [ ] Generate reasons
- [ ] Extend Duplicate dialog
- [ ] Accept/dismiss
- [ ] Safe removal mechanism
- [ ] Synchronization
- [ ] Persistence
- [ ] Safety tests
- [ ] Regression tests

## Milestone 5 — Folder Organization

- [ ] Extend organization suggestions
- [ ] Define approved move workflow
- [ ] Add organization preview
- [ ] Add explicit approval
- [ ] Implement safe move service/path
- [ ] Collision handling
- [ ] Permission handling
- [ ] Synchronization
- [ ] Persistence
- [ ] Batch operation handling
- [ ] Unit tests
- [ ] Integration tests

## Milestone 6 — Cross-Feature Verification

- [ ] Rename tests
- [ ] Move tests
- [ ] Delete tests
- [ ] Reindex tests
- [ ] Restart tests
- [ ] AI metadata preservation
- [ ] Evidence/vector consistency
- [ ] Relationship consistency
- [ ] Collection consistency
- [ ] Dashboard refresh
- [ ] Folder classification refresh

## Milestone 7 — Final Acceptance

- [ ] Full pytest suite
- [ ] No regressions
- [ ] UI smoke test
- [ ] Persistence test
- [ ] Failure/recovery test
- [ ] Performance sanity check
- [ ] Verify all five features
- [ ] Verify no unapproved file operation
- [ ] Record final test count
- [ ] Produce Batch 6 completion report

---

# 19. Definition of Done

Batch 6 is COMPLETE only when all five features satisfy the following:

### #7 Image Caption Generation

- [ ] Standalone user-facing caption action
- [ ] Existing VisionEngine reused
- [ ] Caption persisted
- [ ] Caption displayed
- [ ] Regeneration supported
- [ ] Errors handled
- [ ] Tests pass

### #16 AI Folder Classification

- [ ] Folder-level classification exists
- [ ] Uses existing file classifications
- [ ] Folder statistics/category distribution available
- [ ] Persisted where required
- [ ] Updates after file changes
- [ ] UI integrated
- [ ] Tests pass

### #18 Natural Language Search Filters

- [ ] Natural-language constraints recognized
- [ ] Structured filters generated
- [ ] Existing RetrievalEngine reused
- [ ] Type/extension filters
- [ ] Date filters
- [ ] Size filters
- [ ] Scope filters
- [ ] Semantic query preserved
- [ ] Parsed filters visible
- [ ] Tests pass

### #25 Smart Duplicate Removal Suggestions

- [ ] Duplicate groups analyzed
- [ ] Safe candidate recommendation generated
- [ ] Explanation provided
- [ ] Confidence provided
- [ ] UI integrated
- [ ] Accept/dismiss supported
- [ ] No automatic deletion
- [ ] Safe removal implemented
- [ ] Synchronization verified
- [ ] Tests pass

### #29 Automatic Folder Organization

- [ ] Organization recommendations reused
- [ ] Target folder displayed
- [ ] Preview available
- [ ] Explicit user approval required
- [ ] File move implemented
- [ ] Collision handling
- [ ] Permission handling
- [ ] Synchronization verified
- [ ] SHA-256 identity preserved
- [ ] Tests pass

---

# 20. Batch 6 Final Audit Requirement

Do NOT immediately begin Batch 7 after implementation.

First perform a fresh audit of the actual codebase.

The audit must determine:

- whether all five partial features are now fully implemented
- whether any became broken
- whether any remain partial
- whether the implementation introduced regressions
- current test count
- database/schema state
- persistence
- synchronization
- UI integration
- technical debt introduced by Batch 6

The audit must use the actual codebase as the source of truth.

---

# 21. Batch 7 Gate

Only after the Batch 6 audit confirms the five partial features are complete should Batch 7 be planned.

Batch 7 will address the features that remain **NOT IMPLEMENTED**.

Do not mix Batch 7 implementation into Batch 6.

The latest audit currently lists 11 not-implemented features, but their exact status must be rechecked after Batch 6 because the post-Batch-6 audit is the new source of truth.

---

# 22. Final Development Flow

```text
POST-BATCH-5 AUDIT
        |
        v
     BATCH 6
        |
        +--> Image Caption Generation
        |
        +--> AI Folder Classification
        |
        +--> Natural Language Search Filters
        |
        +--> Smart Duplicate Removal Suggestions
        |
        +--> Automatic Folder Organization
        |
        v
BATCH 6 COMPLETE
        |
        v
POST-BATCH-6 AUDIT
        |
        v
VERIFY PARTIAL FEATURES = COMPLETE
        |
        v
IDENTIFY REMAINING NOT-IMPLEMENTED FEATURES
        |
        v
     BATCH 7 PLAN
        |
        v
BATCH 7 IMPLEMENTATION
```

---

# 23. Important Constraints for the Coding AI

When implementing this plan:

1. Inspect the current code before changing anything.
2. Reuse existing engines and services.
3. Do not duplicate functionality.
4. Do not redesign the application UI.
5. Do not silently move or delete user files.
6. Preserve SHA-256 identity.
7. Preserve existing persistence.
8. Preserve FAISS/evidence consistency.
9. Use migrations for schema changes.
10. Use background processing for heavy operations.
11. Keep the GUI responsive.
12. Add tests with every feature.
13. Run the full regression suite.
14. Do not implement Batch 7 features during Batch 6.
15. Do not declare a feature complete based only on the presence of backend code.
16. A feature is complete only when backend + UI + persistence + integration + runtime behavior + tests are all satisfactory.

---

# 24. Expected Batch 6 Outcome

At the end of Batch 6, the target is:

```text
Before Batch 6

15 IMPLEMENTED
5 PARTIAL
11 NOT IMPLEMENTED
0 BROKEN

             ↓

Complete the 5 PARTIAL features

             ↓

After successful Batch 6

20 IMPLEMENTED
0 PARTIAL
11 NOT IMPLEMENTED
0 BROKEN
```

This target is provisional until the post-Batch-6 audit verifies the actual implementation.

The next development decision must be based on that audit rather than assumption.
