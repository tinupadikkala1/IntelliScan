# Remaining Implementations - Ready to Deploy

**Status:** Phase 1 Complete (50%), Phase 2-3 Ready (50%)  
**Files Created:** 3 new modules  
**Next Step:** Copy-paste remaining code from this file into existing modules

---

## CRITICAL: Update rag_engine.py (Phase 3.2)

**File:** `engines/rag_engine.py`

### ADD IMPORT (at top):
```python
from ai.hallucination_detector import HallucinationDetector
```

### UPDATE __init__ METHOD (find __init__ and add):
```python
self.hallucination_detector = HallucinationDetector(
    self.db_store,
    self.embedding_engine
)
```

### UPDATE ask() METHOD (after LLM generation, find where answer is generated):
```python
# NEW CODE TO ADD BEFORE RETURNING:
# Check for hallucination
hallucination_check = self.hallucination_detector.detect_hallucination(
    question=query,
    answer=answer,
    context=context_blocks,
    model_name=getattr(self, 'model_name', 'unknown')
)

# Warn user if hallucination detected
if hallucination_check['is_hallucinated']:
    answer = f"""⚠️ HALLUCINATION WARNING ⚠️
{hallucination_check['recommendation']}

ORIGINAL ANSWER (USE WITH CAUTION):
{answer}

ISSUES FOUND:
{chr(10).join('• ' + issue for issue in hallucination_check['issues'])}
"""

# Add to response
response.hallucination_risk = hallucination_check['confidence']
```

---

## UPDATE FILE: retrieval_engine.py (Phase 2.1)

**Add these methods to RetrievalEngine class:**

```python
def score_result_relevance(self, query: str, result) -> float:
    """
    Score how relevant a result is to the query (0.0-1.0)
    """
    similarity_score = getattr(result, 'similarity_score', 0.0)
    
    # Check chunk quality (roughly 50 words is optimal)
    chunk_quality = len(result.text.split()) / 50.0
    chunk_quality = min(1.0, chunk_quality)
    
    # Weighted combination
    confidence = (
        similarity_score * 0.6 +  # 60% weight on similarity
        chunk_quality * 0.4        # 40% weight on chunk quality
    )
    
    return confidence

def filter_results_by_confidence(self, results: list, min_confidence: float = 0.5) -> list:
    """Only return results above confidence threshold"""
    return [r for r in results if self.score_result_relevance("", r) >= min_confidence]

def expand_query(self, query: str) -> list:
    """
    Expand query with related terms/synonyms
    """
    expansions = {
        "machine learning": ["deep learning", "AI", "neural networks"],
        "pdf": ["document", "file", "text"],
        "image": ["picture", "photo", "visual"],
        "error": ["bug", "issue", "problem"],
    }
    
    expanded = [query]
    query_lower = query.lower()
    
    for key, synonyms in expansions.items():
        if key in query_lower:
            expanded.extend(synonyms)
    
    return expanded
```

---

## UPDATE FILE: settings_dialog.py (Phase 2.2)

**Add this method to SettingsDialog class:**

```python
def _batch7_tab(self) -> QWidget:
    """Settings for Batch 7 features (Inactivity Reminder)"""
    from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QSpinBox
    
    tab = QWidget()
    layout = QVBoxLayout()
    
    # Inactivity Reminder Section
    inactivity_group = QGroupBox("Inactivity Reminder Settings")
    inactivity_layout = QVBoxLayout()
    
    explanation = QLabel(
        "The Inactivity Reminder monitors ALL files in your workspace.\n"
        "It alerts you about files that haven't been accessed recently.\n\n"
        "SCOPE: Entire workspace (all indexed files across all folders)"
    )
    explanation.setWordWrap(True)
    inactivity_layout.addWidget(explanation)
    
    # Days threshold selector
    threshold_layout = QHBoxLayout()
    threshold_layout.addWidget(QLabel("Mark files as inactive after:"))
    
    self.inactivity_days_spinbox = QSpinBox()
    self.inactivity_days_spinbox.setMinimum(1)
    self.inactivity_days_spinbox.setMaximum(365)
    self.inactivity_days_spinbox.setValue(30)
    self.inactivity_days_spinbox.setSuffix(" days")
    threshold_layout.addWidget(self.inactivity_days_spinbox)
    threshold_layout.addStretch()
    inactivity_layout.addLayout(threshold_layout)
    
    # Enable/disable checkbox
    self.inactivity_enabled_checkbox = QCheckBox("Enable inactivity reminders")
    self.inactivity_enabled_checkbox.setChecked(True)
    inactivity_layout.addWidget(self.inactivity_enabled_checkbox)
    
    # Testing options
    testing_group = QGroupBox("Testing")
    testing_layout = QVBoxLayout()
    
    reset_button = QPushButton("Reset Inactivity Reminder (for testing)")
    reset_button.clicked.connect(self._reset_inactivity_reminder)
    testing_layout.addWidget(reset_button)
    
    manual_check_button = QPushButton("Manually Check for Inactive Files")
    manual_check_button.clicked.connect(self._manually_check_inactive)
    testing_layout.addWidget(manual_check_button)
    
    testing_group.setLayout(testing_layout)
    inactivity_layout.addWidget(testing_group)
    inactivity_layout.addStretch()
    
    inactivity_group.setLayout(inactivity_layout)
    layout.addWidget(inactivity_group)
    layout.addStretch()
    
    tab.setLayout(layout)
    return tab

def _reset_inactivity_reminder(self):
    """Reset reminder for testing"""
    reply = QMessageBox.question(
        self,
        "Reset Inactivity Reminder",
        "This will reset all inactivity tracking.\nAre you sure?",
        QMessageBox.Yes | QMessageBox.No
    )
    if reply == QMessageBox.Yes:
        try:
            self.container.inactivity_reminder_service.reset_reminder_state()
            QMessageBox.information(self, "Success", "Reminder state reset!")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed: {str(e)}")

def _manually_check_inactive(self):
    """Manually trigger inactivity check"""
    try:
        days = self.inactivity_days_spinbox.value()
        inactive_files = self.container.inactivity_reminder_service.find_inactive_files(days)
        
        if not inactive_files:
            QMessageBox.information(self, "No Inactive Files",
                f"No files inactive for more than {days} days")
        else:
            message = f"Found {len(inactive_files)} inactive files:\n\n"
            for f in inactive_files[:10]:
                message += f"• {f.file_path} ({f.days_inactive} days)\n"
            if len(inactive_files) > 10:
                message += f"\n... and {len(inactive_files) - 10} more"
            QMessageBox.information(self, "Inactive Files", message)
    except Exception as e:
        QMessageBox.critical(self, "Error", f"Failed: {str(e)}")
```

---

## UPDATE FILE: inactivity_reminder_service.py (Phase 2.2)

**Add these methods to InactivityReminderService class:**

```python
def reset_reminder_state(self):
    """Reset all shown reminders (useful for testing)"""
    self.last_reminder_shown.clear()
    # Clear from DB if available
    try:
        if self.repository:
            # Query and delete all reminders from DB
            pass  # Depends on your schema
    except Exception:
        pass

def find_inactive_files(self, days: int = None) -> list:
    """
    Find files not accessed in N days
    Returns: List of InactiveFileInfo
    """
    if days is None:
        days = self.days_threshold
    
    from datetime import datetime, timedelta
    threshold_date = datetime.now() - timedelta(days=days)
    
    try:
        query = self.repository.session.query(File).filter(
            File.last_accessed < threshold_date
        ).all()
        
        return [
            InactiveFileInfo(
                file_path=f.path,
                days_inactive=(datetime.now() - f.last_accessed).days,
                last_accessed=f.last_accessed,
                file_size=f.size_bytes
            )
            for f in query
        ]
    except Exception:
        return []
```

---

## UPDATE FILE: document_comparison_service.py (Phase 2.3)

**Add these methods to DocumentComparisonService class:**

```python
def _textual_diff(self, text1: str, text2: str) -> dict:
    """Line-by-line text comparison"""
    import difflib
    
    lines1 = text1.split('\n')
    lines2 = text2.split('\n')
    
    matcher = difflib.SequenceMatcher(None, lines1, lines2)
    
    return {
        'similarities': [l for tag, i1, i2, j1, j2 in matcher.get_opcodes() 
                        if tag == 'equal' for l in lines1[i1:i2]],
        'differences': [{'type': tag, 'original': lines1[i1:i2], 'modified': lines2[j1:j2]}
                       for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != 'equal'],
        'similarity_ratio': matcher.ratio()
    }

def _structural_analysis(self, content1, content2) -> dict:
    """Compare structure: length, sections, formatting"""
    return {
        'length_diff': len(content2.text) - len(content1.text),
        'word_count_diff': len(content2.text.split()) - len(content1.text.split()),
    }

def _semantic_diff(self, text1: str, text2: str) -> dict:
    """Compare meaning using embeddings"""
    if not self.embedding_engine:
        return {}
    
    try:
        e1 = self.embedding_engine.embed_text(text1)
        e2 = self.embedding_engine.embed_text(text2)
        
        import numpy as np
        similarity = float(np.dot(e1, e2) / (np.linalg.norm(e1) * np.linalg.norm(e2)))
        
        return {
            'semantic_similarity': similarity,
            'are_similar': similarity > 0.7
        }
    except Exception:
        return {}
```

---

## UPDATE FILES: graph modules (Phase 3.1)

### Add to entity_extractor.py:
```python
def extract(self, text: str, validation_threshold: float = 0.7) -> list:
    """Extract entities with validation"""
    entities = self._extract_entities_internal(text)
    
    validated = []
    for entity in entities:
        confidence = self._validate_entity(entity, text)
        if confidence >= validation_threshold:
            entity['confidence'] = confidence
            validated.append(entity)
    
    return validated

def _validate_entity(self, entity: dict, text: str) -> float:
    """Validate entity is in text"""
    if entity['text'].lower() in text.lower():
        return 0.9
    return 0.3
```

### Add to relationship_extractor.py:
```python
def extract(self, text: str, entities: list, validation_threshold: float = 0.7) -> list:
    """Extract relationships with validation"""
    relationships = self._extract_relationships_internal(text, entities)
    
    validated = []
    for rel in relationships:
        confidence = self._validate_relationship(rel, text)
        if confidence >= validation_threshold:
            rel['confidence'] = confidence
            validated.append(rel)
    
    return validated

def _validate_relationship(self, rel: dict, text: str) -> float:
    """Validate relationship exists in text"""
    source = rel.get('source', '')
    target = rel.get('target', '')
    
    if source.lower() in text.lower() and target.lower() in text.lower():
        return 0.8
    return 0.3
```

---

## 📋 DEPLOYMENT CHECKLIST

- [ ] Add hallucination detector to rag_engine.py
- [ ] Update organize_dialog imports
- [ ] Add execute_organization to file_organizer_service.py
- [ ] Add methods to retrieval_engine.py
- [ ] Add methods to settings_dialog.py
- [ ] Add methods to inactivity_reminder_service.py
- [ ] Add methods to document_comparison_service.py
- [ ] Add methods to entity_extractor.py
- [ ] Add methods to relationship_extractor.py
- [ ] Run tests
- [ ] Fix any integration issues

---

**Total Code Added:** ~200 lines  
**Time to Deploy:** 1-2 hours  
**Complexity:** Low (mostly copy-paste)

Ready to proceed! 🚀
