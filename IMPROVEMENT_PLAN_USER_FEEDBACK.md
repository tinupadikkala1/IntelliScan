# IntelliScan - User Feedback & Improvement Plan
**University Project - Feature Enhancement Focus**

---

## 1. Improve Logical Reasoning & Answer Quality

### Problem Statement
- Main search results sometimes correct, but supporting files are wrong
- Semantic search returns relevant results but context building may be inaccurate
- Workplace search results lack confidence/relevance indicators

### Root Cause Analysis
1. **Reranking Issues:**
   - RetrievalEngine retrieves top-k results but doesn't properly score context relevance
   - Supporting files selected arbitrarily without semantic validation
   
2. **Context Building Problems:**
   - RAGEngine builds context from top chunks but doesn't verify chunk quality
   - No relevance threshold before including supporting evidence

3. **Query Understanding:**
   - Query embeddings may not capture user intent accurately
   - No query expansion for related terms

### Improvement Solutions

#### Solution 1.1: Add Confidence Scoring
**File:** `engines/retrieval_engine.py`
```python
# Add confidence scoring method
def score_result_relevance(self, query: str, result: RetrievalResult) -> float:
    """
    Score how relevant a result is to the query
    Returns: 0.0-1.0 confidence score
    """
    # Factors to consider:
    # 1. Similarity score (existing)
    similarity_score = result.similarity_score
    
    # 2. Chunk quality (is it a complete sentence/paragraph?)
    chunk_quality = len(result.text.split()) / 50  # normalized to ~50 word chunks
    chunk_quality = min(1.0, chunk_quality)
    
    # 3. Recency of file
    days_old = (datetime.now() - result.file_mtime).days
    recency_score = 1.0 - (days_old / 365)  # Recent files scored higher
    
    # 4. File credibility (has been accessed before?)
    access_count = self.db_store.get_file_access_count(result.file_id)
    credibility = min(1.0, access_count / 10)  # More accesses = more credible
    
    # Weighted combination
    confidence = (
        similarity_score * 0.5 +      # 50% weight on similarity
        chunk_quality * 0.2 +          # 20% weight on chunk quality
        recency_score * 0.15 +         # 15% weight on recency
        credibility * 0.15             # 15% weight on credibility
    )
    
    return confidence

def filter_results_by_confidence(self, results: list[RetrievalResult], 
                                  min_confidence: float = 0.5) -> list[RetrievalResult]:
    """Only return results above confidence threshold"""
    scored = [(r, self.score_result_relevance(query, r)) for r in results]
    return [r for r, score in scored if score >= min_confidence]
```

#### Solution 1.2: Improve Context Building in RAG
**File:** `engines/rag_engine.py`
```python
def _build_rag_prompt(self, query: str, context_blocks: list[str]) -> str:
    """
    Build prompt with quality checks on context
    """
    # Only use high-confidence context
    quality_contexts = []
    for block in context_blocks:
        if self._is_high_quality_context(block, query):
            quality_contexts.append(block)
    
    # Limit to top 3-5 most relevant contexts
    if len(quality_contexts) > 5:
        quality_contexts = quality_contexts[:5]
    
    # Build structured prompt
    prompt = f"""You are a helpful assistant analyzing documents.

QUERY: {query}

CONTEXT FROM FILES (only use if relevant):
"""
    
    for i, context in enumerate(quality_contexts, 1):
        prompt += f"\n[Context {i}]:\n{context}\n"
    
    prompt += """
INSTRUCTIONS:
1. Answer based on the provided context
2. If context doesn't contain the answer, say "Not found in provided files"
3. Cite which context files support your answer
4. Do NOT hallucinate or make up information

ANSWER:"""
    
    return prompt

def _is_high_quality_context(self, context: str, query: str) -> bool:
    """Check if context is actually relevant to query"""
    # Simple keyword matching (can improve with semantic similarity)
    query_words = set(query.lower().split())
    context_words = set(context.lower().split())
    
    # If at least 20% of query words in context, it's relevant
    overlap = len(query_words & context_words) / len(query_words)
    return overlap >= 0.2
```

#### Solution 1.3: Add Query Expansion
**File:** `engines/retrieval_engine.py`
```python
def expand_query(self, query: str) -> list[str]:
    """
    Expand query with related terms/synonyms
    Example: "machine learning" → ["machine learning", "deep learning", "AI", "neural networks"]
    """
    # Simple expansion dictionary (can improve with WordNet/NLTK)
    expansions = {
        "machine learning": ["deep learning", "AI", "neural networks", "algorithms"],
        "pdf": ["document", "file", "text"],
        "image": ["picture", "photo", "visual"],
        "error": ["bug", "issue", "problem", "failure"],
        "fast": ["quick", "speedy", "rapid", "efficient"],
    }
    
    expanded_queries = [query]
    query_lower = query.lower()
    
    for key, synonyms in expansions.items():
        if key in query_lower:
            expanded_queries.extend(synonyms)
    
    return expanded_queries

def smart_retrieve(self, query: str, scope: ChatScope) -> RetrievalResponse:
    """
    Use expanded queries for better results
    """
    all_results = []
    
    # Search with original and expanded queries
    expanded = self.expand_query(query)
    for expanded_query in expanded:
        query_vec = self.embedding_engine.embed_text(expanded_query)
        results = self.retrieve(query_vec, scope=scope)
        all_results.extend(results.results)
    
    # Deduplicate and rank
    unique_results = self._deduplicate_by_file(all_results)
    
    # Filter by confidence
    confident_results = self.filter_results_by_confidence(
        unique_results, 
        min_confidence=0.5
    )
    
    return RetrievalResponse(results=confident_results, scope=scope)
```

#### Solution 1.4: Add Answer Validation
**File:** `engines/rag_engine.py`
```python
def validate_answer(self, question: str, answer: str, context: list[str]) -> dict:
    """
    Check if LLM answer actually matches the provided context
    Returns: {"is_valid": bool, "confidence": float, "issues": []}
    """
    issues = []
    
    # Check 1: Is the answer too long compared to context?
    answer_words = len(answer.split())
    context_words = sum(len(c.split()) for c in context)
    if answer_words > context_words * 2:
        issues.append("Answer longer than 2x context (possible hallucination)")
    
    # Check 2: Does answer contain any facts not in context?
    answer_words_set = set(answer.lower().split())
    context_words_set = set(' '.join(context).lower().split())
    
    # Numbers and dates not in context are suspicious
    import re
    answer_numbers = re.findall(r'\d+', answer)
    context_numbers = re.findall(r'\d+', ' '.join(context))
    
    for num in answer_numbers:
        if num not in context_numbers:
            issues.append(f"Number '{num}' not found in context")
    
    # Check 3: Key question words are addressed
    question_keywords = set(q for q in question.lower().split() if len(q) > 3)
    if len(question_keywords & answer_words_set) < 2:
        issues.append("Answer may not address the question properly")
    
    confidence = 1.0 - (len(issues) * 0.25)  # Each issue reduces confidence
    confidence = max(0.0, min(1.0, confidence))
    
    return {
        "is_valid": len(issues) == 0,
        "confidence": confidence,
        "issues": issues,
        "recommendation": "Use this answer with caution" if issues else "High confidence answer"
    }
```

---

## 2. Fix "Organize Files into Folders" Feature

### Current Issues
- Two buttons with different colors are misleading
- Takes long time without progress indication
- Program crashes during operation
- User doesn't know what's happening

### Improvements

#### Fix 2.1: Redesign UI (Remove Misleading Buttons)
**File:** `ui/dialogs/organize_dialog.py`
```python
class OrganizeDialog(QDialog):
    def _setup_ui(self):
        # BEFORE: Two buttons (confusing)
        # self.organize_button = QPushButton("Organize")
        # self.auto_organize_button = QPushButton("Auto Organize")
        
        # AFTER: Single unified button + checkbox
        layout = QVBoxLayout()
        
        # Folder selection
        self.folder_path_label = QLabel("Select Folder to Organize:")
        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self._browse_folder)
        
        # Organization options
        options_group = QGroupBox("Organization Options")
        options_layout = QVBoxLayout()
        
        self.auto_cluster_checkbox = QCheckBox("Auto-cluster by category")
        self.auto_cluster_checkbox.setChecked(True)
        self.manual_mode_checkbox = QCheckBox("Manual mode (preview first)")
        self.manual_mode_checkbox.setChecked(False)
        
        options_layout.addWidget(self.auto_cluster_checkbox)
        options_layout.addWidget(self.manual_mode_checkbox)
        options_group.setLayout(options_layout)
        
        # Progress section (initially hidden)
        self.progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout()
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.status_label = QLabel("")
        self.status_label.setVisible(False)
        
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(self.status_label)
        self.progress_group.setLayout(progress_layout)
        
        # Main action button (SINGLE, CLEAR PURPOSE)
        self.start_button = QPushButton("Start Organization")
        self.start_button.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                font-weight: bold;
                padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
            QPushButton:pressed {
                background-color: #005a9e;
            }
        """)
        self.start_button.clicked.connect(self._on_start_organization)
        self.start_button.setEnabled(False)
        
        # Cancel button (for during operation)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self._on_cancel)
        
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.cancel_button)
        
        # Assemble
        layout.addWidget(self.folder_path_label)
        layout.addWidget(self.browse_button)
        layout.addWidget(options_group)
        layout.addWidget(self.progress_group)
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
```

#### Fix 2.2: Add Real-time Progress Updates
**File:** `services/file_organizer_service.py`
```python
def execute_organization(self, folder_path: str, auto_cluster: bool = True, 
                        progress_callback=None, cancel_flag=None):
    """
    Execute file organization with progress updates
    
    Args:
        progress_callback: Called with (current, total, status_message)
        cancel_flag: threading.Event to signal cancellation
    """
    total_files = self._count_files(folder_path)
    processed = 0
    
    try:
        # Step 1: Discover files
        if progress_callback:
            progress_callback(0, total_files, "Discovering files...")
        
        candidates = self.find_candidates(folder_path)
        
        # Step 2: Generate organization plan
        if progress_callback:
            progress_callback(20, total_files, "Generating organization plan...")
        
        clusters = self.auto_cluster_folder(folder_path) if auto_cluster else self._manual_clusters(folder_path)
        
        total_moves = sum(c.files_count for c in clusters)
        
        # Step 3: Create folders and move files
        if progress_callback:
            progress_callback(30, total_files, "Creating folders...")
        
        for cluster in clusters:
            # Check for cancellation
            if cancel_flag and cancel_flag.is_set():
                if progress_callback:
                    progress_callback(processed, total_files, "Organization cancelled")
                return MoveResult(total=total_moves, successful=processed, failed=0, cancelled=True)
            
            # Create target folder
            os.makedirs(cluster.target_folder, exist_ok=True)
            
            # Move files in this cluster
            cluster_progress_start = 30 + (processed / total_moves * 60)
            
            for file_path in cluster.files:
                if cancel_flag and cancel_flag.is_set():
                    break
                
                try:
                    # Move file
                    self.file_mover.move_file(
                        file_path, 
                        os.path.join(cluster.target_folder, os.path.basename(file_path))
                    )
                    processed += 1
                    
                    if progress_callback:
                        pct = 30 + (processed / total_moves * 60)
                        progress_callback(
                            int(pct), 
                            total_files, 
                            f"Moving files: {processed}/{total_moves}"
                        )
                
                except Exception as e:
                    print(f"Error moving {file_path}: {e}")
                    continue
        
        # Final step
        if progress_callback:
            progress_callback(95, total_files, "Finalizing...")
        
        if progress_callback:
            progress_callback(100, total_files, "Organization complete!")
        
        return MoveResult(total=total_moves, successful=processed, failed=0)
    
    except Exception as e:
        if progress_callback:
            progress_callback(0, total_files, f"Error: {str(e)}")
        raise
```

#### Fix 2.3: Prevent Crashes with Error Handling
**File:** `ui/dialogs/organize_dialog.py`
```python
def _on_start_organization(self):
    """Start organization with error handling"""
    if not self.folder_path:
        QMessageBox.warning(self, "Error", "Please select a folder first")
        return
    
    try:
        # Disable UI elements
        self.start_button.setEnabled(False)
        self.browse_button.setEnabled(False)
        self.cancel_button.setVisible(True)
        self.progress_bar.setVisible(True)
        self.status_label.setVisible(True)
        
        # Validate folder
        if not os.path.isdir(self.folder_path):
            raise ValueError("Folder not accessible")
        
        file_count = sum(1 for _ in os.walk(self.folder_path) for _ in _ if _.is_file())
        if file_count == 0:
            QMessageBox.information(self, "Empty Folder", "No files to organize")
            return
        
        # Create cancel flag for this operation
        self.cancel_event = threading.Event()
        
        # Run in background thread
        self.thread = QThread()
        self.worker = OrganizeWorker(
            self.organizer_service,
            self.folder_path,
            self.auto_cluster_checkbox.isChecked(),
            self.cancel_event
        )
        
        self.worker.moveToThread(self.thread)
        
        # Connect signals
        self.worker.progress.connect(self._update_progress)
        self.worker.finished.connect(self._on_organization_complete)
        self.worker.error.connect(self._on_organization_error)
        
        self.thread.started.connect(self.worker.run)
        self.thread.start()
    
    except Exception as e:
        QMessageBox.critical(self, "Error", f"Failed to start organization: {str(e)}")
        self.start_button.setEnabled(True)
        self.cancel_button.setVisible(False)

def _on_cancel(self):
    """Cancel ongoing operation"""
    if hasattr(self, 'cancel_event'):
        self.cancel_event.set()
        self.status_label.setText("Cancelling...")

def _update_progress(self, current: int, total: int, message: str):
    """Update progress bar"""
    self.progress_bar.setValue(int((current / max(1, total)) * 100))
    self.status_label.setText(f"{message} ({current}/{total})")

def _on_organization_complete(self, result: MoveResult):
    """Handle completion"""
    self.progress_bar.setVisible(False)
    self.status_label.setText(
        f"Complete! Moved {result.successful}/{result.total} files"
    )
    self.thread.quit()
    self.start_button.setEnabled(True)
    self.cancel_button.setVisible(False)
    
    if result.successful > 0:
        QMessageBox.information(
            self, 
            "Success", 
            f"Successfully organized {result.successful} files"
        )

def _on_organization_error(self, error: str):
    """Handle errors gracefully"""
    QMessageBox.critical(self, "Error During Organization", error)
    self.progress_bar.setVisible(False)
    self.thread.quit()
    self.start_button.setEnabled(True)
    self.cancel_button.setVisible(False)


class OrganizeWorker(QObject):
    """Worker for organization in background thread"""
    progress = Signal(int, int, str)
    finished = Signal(object)
    error = Signal(str)
    
    def __init__(self, organizer_service, folder_path, auto_cluster, cancel_event):
        super().__init__()
        self.organizer_service = organizer_service
        self.folder_path = folder_path
        self.auto_cluster = auto_cluster
        self.cancel_event = cancel_event
    
    def run(self):
        try:
            result = self.organizer_service.execute_organization(
                self.folder_path,
                auto_cluster=self.auto_cluster,
                progress_callback=self._on_progress,
                cancel_flag=self.cancel_event
            )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))
    
    def _on_progress(self, current, total, message):
        self.progress.emit(current, total, message)
```

---

## 3. Improve "Check Inactive Files" Feature

### Current Issues
- User confused: is it for current directory or all files?
- No way to set day limit threshold
- No way to reset/stop reminders for testing

### Improvements

#### Fix 3.1: Add Clear Documentation & Configuration
**File:** `services/inactivity_reminder_service.py`
```python
class InactivityReminderService:
    """
    Tracks files that haven't been accessed recently
    
    SCOPE: Entire workspace (all indexed files)
    Configure via Settings dialog or config file
    """
    
    def __init__(self, repository, days_threshold: int = 30):
        self.repository = repository
        self.days_threshold = days_threshold  # Configurable
        self.last_reminder_shown = {}  # Track shown reminders
    
    def find_inactive_files(self, days: int = None) -> list[InactiveFileInfo]:
        """
        Find files not accessed in N days
        
        Args:
            days: Days of inactivity (uses default if None)
        
        Returns:
            List of inactive files with their info
        """
        if days is None:
            days = self.days_threshold
        
        threshold_date = datetime.now() - timedelta(days=days)
        
        query = self.repository.session.query(File).filter(
            File.last_accessed < threshold_date,
            File.path.isnot(None)  # Only indexed files
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
    
    def reset_reminder_state(self):
        """Reset all shown reminders (useful for testing)"""
        self.last_reminder_shown.clear()
        self.repository.delete_all_inactivity_reminders()
    
    def mark_file_accessed(self, file_path: str):
        """Mark a file as recently accessed"""
        file_record = self.repository.get_file_by_path(file_path)
        if file_record:
            file_record.last_accessed = datetime.now()
            self.repository.session.commit()
```

#### Fix 3.2: Add Settings Dialog Configuration
**File:** `ui/settings_dialog.py`
```python
def _batch7_tab(self) -> QWidget:
    """Settings for inactivity reminder"""
    tab = QWidget()
    layout = QVBoxLayout()
    
    # Inactivity Reminder Section
    inactivity_group = QGroupBox("Inactivity Reminder Settings")
    inactivity_layout = QVBoxLayout()
    
    # Explanation
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
        "This will reset all inactivity tracking for testing.\n"
        "Are you sure?",
        QMessageBox.Yes | QMessageBox.No
    )
    
    if reply == QMessageBox.Yes:
        try:
            self.container.inactivity_reminder_service.reset_reminder_state()
            QMessageBox.information(
                self,
                "Success",
                "Inactivity reminder state has been reset.\n"
                "You can now test the feature again."
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to reset: {str(e)}")

def _manually_check_inactive(self):
    """Manually trigger inactivity check"""
    try:
        days = self.inactivity_days_spinbox.value()
        inactive_files = self.container.inactivity_reminder_service.find_inactive_files(days)
        
        if not inactive_files:
            QMessageBox.information(
                self,
                "No Inactive Files",
                f"No files found inactive for more than {days} days"
            )
        else:
            message = f"Found {len(inactive_files)} inactive files:\n\n"
            for f in inactive_files[:10]:  # Show first 10
                message += f"• {f.file_path} ({f.days_inactive} days)\n"
            if len(inactive_files) > 10:
                message += f"\n... and {len(inactive_files) - 10} more"
            
            QMessageBox.information(self, "Inactive Files", message)
    
    except Exception as e:
        QMessageBox.critical(self, "Error", f"Failed to check: {str(e)}")
```

---

## 4. Add Progress Bar to "Duplicate Files" Feature

### Problem
User doesn't know what's happening during duplicate scan

### Solution

**File:** `engines/duplicate_engine.py`
```python
def find_exact_duplicates(self, progress_callback=None) -> dict:
    """
    Find exact duplicates with progress tracking
    
    Args:
        progress_callback: Called with (current, total, status_message)
    """
    all_files = self.repository.list_all_files()
    total_files = len(all_files)
    
    checksum_map = {}
    duplicates = {}
    
    for i, file_record in enumerate(all_files):
        try:
            # Update progress
            if progress_callback:
                progress_callback(
                    i, total_files,
                    f"Hashing files: {i}/{total_files}"
                )
            
            # Calculate checksum
            checksum = self.file_checksum(file_record.path)
            
            # Group by checksum
            if checksum not in checksum_map:
                checksum_map[checksum] = []
            checksum_map[checksum].append(file_record.path)
        
        except Exception as e:
            print(f"Error processing {file_record.path}: {e}")
            continue
    
    # Find groups with > 1 file
    duplicates = {k: v for k, v in checksum_map.items() if len(v) > 1}
    
    if progress_callback:
        progress_callback(total_files, total_files, "Finding duplicates complete!")
    
    return duplicates

def find_near_duplicates(self, progress_callback=None) -> dict:
    """
    Find near-duplicates with progress tracking
    """
    all_files = self.repository.list_all_files()
    total_files = len(all_files)
    
    near_duplicates = {}
    
    for i, file1 in enumerate(all_files):
        if progress_callback:
            progress_callback(
                i, total_files,
                f"Comparing files: {i}/{total_files}"
            )
        
        for j, file2 in enumerate(all_files[i+1:], i+1):
            if self._is_near_duplicate(file1, file2):
                key = (file1.path, file2.path)
                near_duplicates[key] = self._similarity_score(file1, file2)
    
    if progress_callback:
        progress_callback(total_files, total_files, "Near-duplicate detection complete!")
    
    return near_duplicates
```

**File:** `ui/dialogs/duplicate_dialog.py`
```python
class DuplicateDialog(QDialog):
    def _setup_ui(self):
        # ... existing UI ...
        
        # Progress section
        self.progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout()
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        
        self.status_label = QLabel("")
        self.status_label.setVisible(False)
        
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(self.status_label)
        self.progress_group.setLayout(progress_layout)
    
    def _on_scan_clicked(self):
        """Scan for duplicates with progress"""
        try:
            self.progress_bar.setVisible(True)
            self.status_label.setVisible(True)
            self.scan_button.setEnabled(False)
            
            # Scan in thread
            self.thread = QThread()
            self.worker = DuplicateScanWorker(self.duplicate_engine)
            
            self.worker.progress.connect(self._update_progress)
            self.worker.finished.connect(self._on_scan_finished)
            self.worker.error.connect(self._on_scan_error)
            
            self.worker.moveToThread(self.thread)
            self.thread.started.connect(self.worker.run)
            self.thread.start()
        
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            self.scan_button.setEnabled(True)
    
    def _update_progress(self, current: int, total: int, message: str):
        """Update progress display"""
        if total > 0:
            self.progress_bar.setValue(int((current / total) * 100))
        self.status_label.setText(message)


class DuplicateScanWorker(QObject):
    progress = Signal(int, int, str)
    finished = Signal(dict)
    error = Signal(str)
    
    def __init__(self, duplicate_engine):
        super().__init__()
        self.duplicate_engine = duplicate_engine
    
    def run(self):
        try:
            # Find exact duplicates
            exact_dupes = self.duplicate_engine.find_exact_duplicates(
                progress_callback=self._on_progress
            )
            
            # Find near-duplicates
            near_dupes = self.duplicate_engine.find_near_duplicates(
                progress_callback=self._on_progress
            )
            
            result = {
                "exact": exact_dupes,
                "near": near_dupes
            }
            self.finished.emit(result)
        
        except Exception as e:
            self.error.emit(str(e))
    
    def _on_progress(self, current, total, message):
        self.progress.emit(current, total, message)
```

---

## 5. Ensure "Compare Documents" Provides Accurate Answers

### Problem
Comparisons may be inaccurate or miss important differences

### Solution

**File:** `services/document_comparison_service.py`
```python
def compare(self, file1_path: str, file2_path: str) -> ComparisonResult:
    """
    Comprehensive document comparison with multiple methods
    """
    
    # Extract content from both files
    content1 = self._extract_content(file1_path)
    content2 = self._extract_content(file2_path)
    
    # Comparison methods (triangulation for accuracy)
    results = []
    
    # Method 1: Textual Diff (line-by-line)
    textual = self._textual_diff(content1.text, content2.text)
    results.append(("Textual Analysis", textual))
    
    # Method 2: Structural Analysis (format, length, sections)
    structural = self._structural_analysis(content1, content2)
    results.append(("Structural Analysis", structural))
    
    # Method 3: Semantic Analysis (meaning-based)
    semantic = self._semantic_diff(content1.text, content2.text)
    results.append(("Semantic Analysis", semantic))
    
    # Consolidate findings
    comparison = self._consolidate_results(results, content1, content2)
    
    return ComparisonResult(
        file1=file1_path,
        file2=file2_path,
        similarities=comparison['similarities'],
        differences=comparison['differences'],
        confidence=self._calculate_confidence(results),
        detailed_analysis=comparison['detailed']
    )

def _textual_diff(self, text1: str, text2: str) -> dict:
    """Line-by-line text comparison"""
    import difflib
    
    lines1 = text1.split('\n')
    lines2 = text2.split('\n')
    
    matcher = difflib.SequenceMatcher(None, lines1, lines2)
    
    similarities = []
    differences = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            similarities.extend(lines1[i1:i2])
        elif tag in ('replace', 'delete', 'insert'):
            differences.append({
                'type': tag,
                'original': lines1[i1:i2],
                'modified': lines2[j1:j2]
            })
    
    return {
        'similarities': similarities,
        'differences': differences,
        'similarity_ratio': matcher.ratio()
    }

def _structural_analysis(self, content1, content2) -> dict:
    """Compare structure: length, sections, formatting"""
    return {
        'length_diff': len(content2.text) - len(content1.text),
        'word_count_diff': len(content2.text.split()) - len(content1.text.split()),
        'sections_in_1': self._extract_sections(content1.text),
        'sections_in_2': self._extract_sections(content2.text),
        'formatting_changes': self._detect_formatting_changes(content1, content2)
    }

def _semantic_diff(self, text1: str, text2: str) -> dict:
    """Compare meaning using embeddings"""
    # Split into meaningful chunks
    chunks1 = self._chunk_text(text1)
    chunks2 = self._chunk_text(text2)
    
    # Embed chunks
    embeddings1 = [self.embedding_engine.embed_text(c) for c in chunks1]
    embeddings2 = [self.embedding_engine.embed_text(c) for c in chunks2]
    
    # Find similar chunks
    similarities = []
    for e1, c1 in zip(embeddings1, chunks1):
        for e2, c2 in zip(embeddings2, chunks2):
            similarity = self._cosine_similarity(e1, e2)
            if similarity > 0.7:
                similarities.append({
                    'chunk1': c1,
                    'chunk2': c2,
                    'similarity': similarity
                })
    
    return {
        'similar_concepts': similarities,
        'unique_to_file1': [c for c in chunks1 if not self._has_similar(c, embeddings2)],
        'unique_to_file2': [c for c in chunks2 if not self._has_similar(c, embeddings1)]
    }

def _consolidate_results(self, results: list[tuple], content1, content2) -> dict:
    """Combine all analysis methods"""
    consolidated = {
        'similarities': [],
        'differences': [],
        'detailed': {}
    }
    
    for method_name, analysis in results:
        consolidated['detailed'][method_name] = analysis
        
        # Extract key findings
        if 'similarities' in analysis:
            consolidated['similarities'].extend(analysis['similarities'][:5])  # Top 5
        
        if 'differences' in analysis:
            consolidated['differences'].extend(analysis['differences'][:5])  # Top 5
    
    # Remove duplicates
    consolidated['similarities'] = list(set(consolidated['similarities']))
    
    return consolidated

def _calculate_confidence(self, results: list) -> float:
    """Calculate confidence based on agreement between methods"""
    if len(results) < 2:
        return 0.7  # Medium confidence if only one method
    
    # Check if methods agree
    agreements = 0
    total_pairs = len(results) * (len(results) - 1) / 2
    
    for i, (name1, result1) in enumerate(results):
        for name2, result2 in results[i+1:]:
            # Simple check: do they find same number of differences?
            diffs1 = len(result1.get('differences', []))
            diffs2 = len(result2.get('differences', []))
            
            if abs(diffs1 - diffs2) <= 2:  # Within 2 differences
                agreements += 1
    
    confidence = 0.5 + (agreements / total_pairs) * 0.5  # Range: 0.5-1.0
    return min(1.0, confidence)
```

---

## 6. Ensure All AI Features Provide Good Answers (Anti-Hallucination)

### Core Strategy: Multi-Level Validation

**File:** `ai/hallucination_detector.py` (NEW)
```python
from typing import dict, list
import re

class HallucinationDetector:
    """
    Multi-layer hallucination detection to prevent incorrect answers
    """
    
    def __init__(self, db_store, embedding_engine):
        self.db_store = db_store
        self.embedding_engine = embedding_engine
    
    def detect_hallucination(self, 
                            question: str, 
                            answer: str, 
                            context: list[str],
                            model_name: str = "unknown") -> dict:
        """
        Check if answer is hallucinated (not grounded in context)
        
        Returns:
            {
                'is_hallucinated': bool,
                'confidence': 0.0-1.0,
                'issues': [list of specific issues],
                'recommendation': str
            }
        """
        
        issues = []
        scores = []
        
        # Check 1: Factual consistency
        factual_score = self._check_factual_consistency(answer, context)
        scores.append(factual_score)
        if factual_score < 0.5:
            issues.append("Answer contains facts not in provided context")
        
        # Check 2: Semantic alignment
        semantic_score = self._check_semantic_alignment(question, answer, context)
        scores.append(semantic_score)
        if semantic_score < 0.5:
            issues.append("Answer doesn't semantically align with question")
        
        # Check 3: Length plausibility
        length_score = self._check_length_plausibility(answer, context)
        scores.append(length_score)
        if length_score < 0.5:
            issues.append("Answer length implausible given context size")
        
        # Check 4: Citation presence
        citation_score = self._check_citation_score(answer, context)
        scores.append(citation_score)
        if citation_score < 0.3:
            issues.append("Answer lacks proper citations to source material")
        
        # Check 5: Confidence markers
        confidence_markers = self._detect_confidence_markers(answer)
        if confidence_markers['uncertain'] > 0.3:
            issues.append("Answer contains many uncertain phrases ('might', 'possibly', etc.)")
        
        # Calculate overall hallucination probability
        avg_score = sum(scores) / len(scores)
        hallucination_confidence = 1.0 - avg_score
        
        recommendation = self._recommend_action(
            hallucination_confidence, 
            issues,
            model_name
        )
        
        return {
            'is_hallucinated': hallucination_confidence > 0.6,
            'confidence': hallucination_confidence,
            'issues': issues,
            'recommendation': recommendation,
            'scores': {
                'factual': factual_score,
                'semantic': semantic_score,
                'length': length_score,
                'citation': citation_score
            }
        }
    
    def _check_factual_consistency(self, answer: str, context: list[str]) -> float:
        """Check if answer facts are in context"""
        # Extract key entities and facts from answer
        answer_facts = self._extract_facts(answer)
        context_facts = set()
        
        for c in context:
            context_facts.update(self._extract_facts(c))
        
        # Calculate overlap
        if not answer_facts:
            return 0.5  # No facts, neutral
        
        overlap = len(answer_facts & context_facts) / len(answer_facts)
        return overlap
    
    def _check_semantic_alignment(self, question: str, answer: str, 
                                  context: list[str]) -> float:
        """Check if answer addresses the question using context"""
        q_embedding = self.embedding_engine.embed_text(question)
        a_embedding = self.embedding_engine.embed_text(answer)
        c_embeddings = [self.embedding_engine.embed_text(c) for c in context]
        
        # Is the answer semantically similar to question?
        q_a_sim = self._cosine_similarity(q_embedding, a_embedding)
        
        # Is the context relevant to question?
        c_q_sims = [self._cosine_similarity(c_emb, q_embedding) 
                    for c_emb in c_embeddings]
        avg_c_q_sim = sum(c_q_sims) / len(c_q_sims) if c_q_sims else 0
        
        # Average
        return (q_a_sim + avg_c_q_sim) / 2
    
    def _check_length_plausibility(self, answer: str, context: list[str]) -> float:
        """Check if answer length is reasonable given context"""
        answer_words = len(answer.split())
        context_words = sum(len(c.split()) for c in context)
        
        # Answer should be 5-30% of context size
        ratio = answer_words / max(context_words, 100)  # Avoid division by zero
        
        if 0.05 <= ratio <= 0.3:
            return 1.0
        elif 0.02 <= ratio <= 0.5:
            return 0.7
        else:
            return 0.3  # Too short or too long
    
    def _check_citation_score(self, answer: str, context: list[str]) -> float:
        """Check if answer properly cites sources"""
        # Look for citation patterns: [Source], (Source), "quote"
        citation_patterns = [
            r'\[.*?\]',  # [Source]
            r'\(.*?\)',   # (Source)
            r'".*?"',     # "quote"
            r'According to',
            r'As stated in',
        ]
        
        citations_found = 0
        for pattern in citation_patterns:
            citations_found += len(re.findall(pattern, answer))
        
        # Should have at least 1 citation per 100 words
        answer_words = len(answer.split())
        expected_citations = max(1, answer_words / 100)
        
        citation_ratio = citations_found / expected_citations
        return min(1.0, citation_ratio)
    
    def _detect_confidence_markers(self, answer: str) -> dict:
        """Detect words indicating uncertainty"""
        uncertain_words = {
            'might': 0.2, 'possibly': 0.2, 'maybe': 0.3,
            'could': 0.15, 'may': 0.15, 'approximately': 0.1,
            'possibly': 0.25, 'likely': 0.15, 'seems': 0.2
        }
        
        answer_lower = answer.lower()
        total_uncertainty = 0
        for word, weight in uncertain_words.items():
            total_uncertainty += answer_lower.count(word) * weight
        
        answer_words = len(answer.split())
        return {
            'uncertain': total_uncertainty / max(answer_words, 1),
            'certain_markers': len(re.findall(r'confirmed|verified|proven|clearly', answer_lower))
        }
    
    def _recommend_action(self, confidence: float, issues: list, 
                         model_name: str) -> str:
        """Recommend user action based on hallucination risk"""
        if confidence > 0.8:
            return f"⚠️ HIGH RISK HALLUCINATION: Do NOT trust this answer. The model may have made up information. {len(issues)} issues detected."
        elif confidence > 0.6:
            return f"⚠️ MODERATE RISK: Use with caution. Verify key facts independently. {len(issues)} potential issues found."
        elif confidence > 0.4:
            return f"✓ PARTIAL CONFIDENCE: Probably accurate but has some uncertainties. Verify important claims."
        else:
            return f"✓ HIGH CONFIDENCE: Answer appears well-grounded in provided context."
    
    def _extract_facts(self, text: str) -> set:
        """Extract key facts/entities from text"""
        # Simple approach: nouns and important phrases
        # In production, use NER (Named Entity Recognition)
        import re
        
        # Extract numbers, dates, proper nouns
        facts = set()
        
        # Numbers
        numbers = re.findall(r'\b\d+(?:\.\d+)?\b', text)
        facts.update(numbers)
        
        # Dates
        dates = re.findall(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b', text)
        facts.update(dates)
        
        # Words starting with capital (likely proper nouns)
        proper_nouns = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text)
        facts.update(proper_nouns)
        
        return facts
    
    @staticmethod
    def _cosine_similarity(vec1, vec2) -> float:
        """Calculate cosine similarity between vectors"""
        import numpy as np
        vec1 = np.array(vec1)
        vec2 = np.array(vec2)
        return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2) + 1e-8)
```

**Integration in RAG Engine:**

**File:** `engines/rag_engine.py`
```python
from ai.hallucination_detector import HallucinationDetector

class RAGEngine:
    def __init__(self, ...):
        # ... existing init ...
        self.hallucination_detector = HallucinationDetector(
            self.db_store, 
            self.embedding_engine
        )
    
    def ask(self, query: str, file_paths: list = None) -> RAGResponse:
        """Ask question with hallucination detection"""
        
        # Build context as usual
        context_blocks = self._build_context(query, file_paths)
        
        # Generate answer
        prompt = self._build_rag_prompt(query, context_blocks)
        answer = self._generate_answer(prompt)
        
        # CRITICAL: Check for hallucination
        hallucination_check = self.hallucination_detector.detect_hallucination(
            question=query,
            answer=answer,
            context=context_blocks,
            model_name=self.model_name
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
        
        # Build response
        response = RAGResponse(
            answer=answer,
            citations=self._extract_citations(context_blocks),
            hallucination_risk=hallucination_check['confidence'],
            sources_used=file_paths,
            context_quality={
                'factual': hallucination_check['scores']['factual'],
                'semantic': hallucination_check['scores']['semantic']
            }
        )
        
        return response
```

---

## 7. Ensure Knowledge Graph Provides Accurate Relationships

### Problem
Knowledge graph relationships may be incorrect or hallucinated

### Improvements

**File:** `graph/entity_extractor.py`
```python
class EntityExtractor:
    """Extract entities with validation"""
    
    def extract(self, text: str, validation_threshold: float = 0.7) -> list[EntityRecord]:
        """
        Extract entities with confidence threshold
        
        Only return entities that meet validation threshold
        """
        # Extract entities as usual
        entities = self._extract_entities_internal(text)
        
        # Validate each entity
        validated_entities = []
        for entity in entities:
            confidence = self._validate_entity(entity, text)
            
            if confidence >= validation_threshold:
                entity.confidence = confidence
                validated_entities.append(entity)
        
        return validated_entities
    
    def _validate_entity(self, entity: dict, original_text: str) -> float:
        """Check if extracted entity is actually in the text"""
        confidence = 0.0
        
        # Check 1: Does entity appear in text?
        if entity['text'].lower() in original_text.lower():
            confidence += 0.3
        
        # Check 2: Is entity a known type?
        known_types = {'PERSON', 'ORG', 'LOCATION', 'DATE', 'PRODUCT'}
        if entity.get('type') in known_types:
            confidence += 0.3
        
        # Check 3: Does context make sense?
        if self._is_context_plausible(entity, original_text):
            confidence += 0.4
        
        return confidence
    
    def _is_context_plausible(self, entity: dict, text: str) -> bool:
        """Check if entity makes sense in context"""
        # Extract surrounding words
        entity_text = entity['text']
        idx = text.lower().find(entity_text.lower())
        
        if idx == -1:
            return False
        
        # Get context window (50 chars before and after)
        start = max(0, idx - 50)
        end = min(len(text), idx + len(entity_text) + 50)
        context = text[start:end]
        
        # Check for contextual clues
        context_words = context.lower().split()
        entity_type = entity.get('type', '')
        
        # Person names usually preceded by: "Mr", "Ms", "Dr", etc.
        if entity_type == 'PERSON':
            person_markers = {'mr', 'ms', 'dr', 'prof', 'said', 'told', 'asked'}
            return any(marker in context_words for marker in person_markers)
        
        # Organizations usually followed by: "said", "announced", "reported"
        elif entity_type == 'ORG':
            org_markers = {'said', 'announced', 'reported', 'company', 'corp', 'inc'}
            return any(marker in context_words for marker in org_markers)
        
        # Locations usually followed by: "in", "from", "to", etc.
        elif entity_type == 'LOCATION':
            location_markers = {'in', 'from', 'to', 'near', 'located'}
            return any(marker in context_words for marker in location_markers)
        
        return True
```

**File:** `graph/relationship_extractor.py`
```python
class RelationshipExtractor:
    """Extract relationships between entities with validation"""
    
    def extract(self, text: str, entities: list[EntityRecord], 
                validation_threshold: float = 0.7) -> list[RelationshipRecord]:
        """
        Extract relationships with confidence threshold
        """
        relationships = []
        
        # Extract raw relationships
        raw_relationships = self._extract_relationships_internal(text, entities)
        
        for rel in raw_relationships:
            # Validate relationship
            confidence = self._validate_relationship(rel, text, entities)
            
            if confidence >= validation_threshold:
                rel.confidence = confidence
                rel.validated = True
                relationships.append(rel)
        
        return relationships
    
    def _validate_relationship(self, relationship: dict, text: str, 
                              entities: list[EntityRecord]) -> float:
        """
        Validate that a relationship actually exists in the text
        """
        confidence = 0.0
        
        source_entity = relationship['source']
        target_entity = relationship['target']
        rel_type = relationship['type']
        
        # Check 1: Are both entities in the text and validated?
        source_validated = any(e.name == source_entity for e in entities if e.validated)
        target_validated = any(e.name == target_entity for e in entities if e.validated)
        
        if source_validated and target_validated:
            confidence += 0.3
        
        # Check 2: Is there textual evidence of this relationship?
        evidence_score = self._find_relationship_evidence(
            source_entity, 
            target_entity, 
            rel_type,
            text
        )
        confidence += evidence_score * 0.4
        
        # Check 3: Is the relationship type plausible?
        plausible_score = self._is_relationship_plausible(
            source_entity,
            rel_type,
            target_entity
        )
        confidence += plausible_score * 0.3
        
        return confidence
    
    def _find_relationship_evidence(self, source: str, target: str, 
                                    rel_type: str, text: str) -> float:
        """Look for textual evidence of the relationship"""
        
        # Relationship keywords
        rel_keywords = {
            'works_for': ['works for', 'employed by', 'at company', 'joined'],
            'located_in': ['located in', 'based in', 'in city', 'of country'],
            'partner_with': ['partnered with', 'works with', 'allied with'],
            'owns': ['owns', 'founded', 'created', 'started'],
            'parent_of': ['parent of', 'father of', 'mother of'],
        }
        
        keywords = rel_keywords.get(rel_type, [])
        
        # Check if entities appear together in text
        source_idx = text.lower().find(source.lower())
        target_idx = text.lower().find(target.lower())
        
        if source_idx == -1 or target_idx == -1:
            return 0.0  # One or both entities not in text
        
        # Calculate proximity (entities should be close)
        proximity = abs(source_idx - target_idx)
        max_proximity = 500  # Characters apart
        
        if proximity > max_proximity:
            return 0.0  # Too far apart
        
        # Check for relationship keywords between entities
        start = min(source_idx, target_idx)
        end = max(source_idx, target_idx) + 100
        between_text = text[start:end].lower()
        
        for keyword in keywords:
            if keyword in between_text:
                return 0.8  # Strong evidence
        
        # Check for pronouns linking entities
        if 'he ' in between_text or 'she ' in between_text or 'they ' in between_text:
            return 0.5  # Weak evidence
        
        return 0.3  # Some evidence just from proximity
    
    def _is_relationship_plausible(self, source: str, rel_type: str, 
                                   target: str) -> float:
        """Check if the relationship type makes logical sense"""
        
        # Some relationships don't make sense
        # E.g., "John works_for John" or "NYC located_in USA located_in Earth" (redundant)
        
        if source.lower() == target.lower():
            return 0.0  # Entity can't have relationship with itself
        
        # All other relationships are potentially plausible
        return 1.0
```

---

## Summary of Changes

| Feature | Issue | Solution | Impact |
|---------|-------|----------|--------|
| **Semantic Search** | Wrong supporting files | Confidence scoring + reranking | ✅ Better context |
| **RAG Q&A** | Hallucinations | Multi-layer validation + warnings | ✅ Fewer false answers |
| **Organize Files** | Misleading UI + crashes | Single button + progress bar + threading | ✅ Clear UX + stable |
| **Inactive Files** | Confusion about scope | Settings dialog + reset option | ✅ Clear documentation |
| **Duplicate Detection** | No progress info | Progress bar during scan | ✅ User awareness |
| **Document Comparison** | Inaccurate results | 3-method triangulation | ✅ More accurate |
| **Knowledge Graph** | Wrong relationships | Entity/relationship validation | ✅ Accurate graph |
| **All AI Features** | Hallucination risk | Detector + confidence scores | ✅ Trust worthy answers |

---

## Implementation Priority

### Phase 1 (Immediate - This Week)
1. ✅ Add hallucination detector
2. ✅ Fix Organize Files UI (single button)
3. ✅ Add progress bars (Organize, Duplicates)
4. ✅ Add confidence scoring to search

### Phase 2 (Next Week)
5. ✅ Add inactivity reminder settings
6. ✅ Improve comparison accuracy (3 methods)
7. ✅ Validate entity extraction
8. ✅ Validate relationship extraction

### Phase 3 (Following Week)
9. ✅ Query expansion for better search
10. ✅ Answer validation in RAG
11. ✅ Enhanced error handling
12. ✅ Testing & bug fixes

---

**Status:** University Project - Feature Refinement Focus  
**Scope:** Quality improvement, not enterprise scaling  
**Estimated Time:** 2-3 weeks for full implementation
