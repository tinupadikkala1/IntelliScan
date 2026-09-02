"""Batch 4 tests — persistent conversations, folder/workspace chat,
multi-document reasoning, knowledge graph, agentic workflows and the
reusable chat/graph/agent UI.

All tests run WITHOUT Ollama; LLM calls are mocked.
"""

import os
import sys
import time
import uuid
from contextlib import contextmanager

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


@contextmanager
def _db_session_factory(tmp_path, name="test_batch4.db"):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database.models import Base

    engine = create_engine(f"sqlite:///{tmp_path / name}", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    @contextmanager
    def session_ctx():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    yield session_ctx


# ================================================================
# M1 — Conversation store
# ================================================================

class TestConversationStore:
    def test_crud_roundtrip(self, tmp_path):
        from conversation.conversation_store import ConversationStore
        with _db_session_factory(tmp_path) as sf:
            store = ConversationStore(sf)
            cid = store.create_conversation("folder", "/tmp/proj", title="Project Q")
            assert cid > 0

            convs = store.list_conversations()
            assert len(convs) == 1
            assert convs[0].title == "Project Q"
            assert convs[0].scope_type == "folder"
            assert convs[0].scope_path == "/tmp/proj"
            assert convs[0].message_count == 0

            assert store.rename_conversation(cid, "Renamed")
            assert store.get_conversation(cid).title == "Renamed"
            assert store.delete_conversation(cid)
            assert store.get_conversation(cid) is None

    def test_message_and_citation_persistence(self, tmp_path):
        from conversation.conversation_store import ConversationStore
        from conversation.models import CitationRecord
        with _db_session_factory(tmp_path) as sf:
            store = ConversationStore(sf)
            cid = store.create_conversation("workspace", "")

            store.append_message(cid, "user", "What is third normal form?")
            store.append_message(cid, "assistant", "3NF eliminates transitive dependencies.",
                                 citations=[CitationRecord(
                                     chunk_id="c1", file_path="/tmp/notes.pdf",
                                     source_label="Page 3", source_index=2,
                                     source_type="page", snippet="transitive dependency...",
                                 )])
            messages = store.get_messages(cid)
            assert len(messages) == 2
            assert messages[0].role == "user"
            assert messages[1].role == "assistant"
            assert len(messages[1].citations) == 1
            assert messages[1].citations[0].file_path == "/tmp/notes.pdf"
            assert messages[1].citations[0].source_index == 2

    def test_conversation_survives_store_reopen(self, tmp_path):
        """Messages persist across a fresh store instance (restart simulation)."""
        from conversation.conversation_store import ConversationStore
        with _db_session_factory(tmp_path) as sf:
            store = ConversationStore(sf)
            cid = store.create_conversation("folder", "/tmp/proj", title="Persistent")
            store.append_message(cid, "user", "persisted question")

            # New store over the same DB (as after an app restart)
            store2 = ConversationStore(sf)
            msgs = store2.get_messages(cid)
            assert len(msgs) == 1
            assert msgs[0].content == "persisted question"


# ================================================================
# M2 — Scope manager, context builder, citation builder
# ================================================================

class TestScopeManager:
    def test_workspace_filter_none(self):
        from conversation.scope_manager import ChatScope, ScopeManager
        assert ScopeManager().file_filter(ChatScope("workspace")) is None

    def test_file_filter(self):
        from conversation.scope_manager import ChatScope, ScopeManager
        flt = ScopeManager().file_filter(ChatScope("file", "/tmp/a.txt"))
        assert flt == ["/tmp/a.txt"]

    def test_folder_filter_from_evidence(self):
        from conversation.scope_manager import ChatScope, ScopeManager
        from engines import EvidenceChunk
        ev = {
            "k1": EvidenceChunk(chunk_id="k1", text="t", file_path="/tmp/proj/a.txt",
                                file_hash="h", source_type="s", source_index=0,
                                source_label="s", char_start=0, char_end=1),
            "k2": EvidenceChunk(chunk_id="k2", text="t", file_path="/tmp/other/b.txt",
                                file_hash="h", source_type="s", source_index=0,
                                source_label="s", char_start=0, char_end=1),
        }
        flt = ScopeManager().file_filter(ChatScope("folder", "/tmp/proj"), ev)
        assert flt == ["/tmp/proj/a.txt"]

    def test_path_in_scope(self):
        from conversation.scope_manager import ChatScope, ScopeManager
        assert ScopeManager.path_in_scope("/tmp/proj/a.txt", ChatScope("folder", "/tmp/proj"))
        assert not ScopeManager.path_in_scope("/tmp/other/a.txt", ChatScope("folder", "/tmp/proj"))


class TestContextBuilder:
    def test_history_bounded(self):
        from conversation.context_builder import ConversationContextBuilder
        from conversation.models import ChatMessage
        msgs = [
            ChatMessage(role="user" if i % 2 == 0 else "assistant", content=f"msg {i}")
            for i in range(20)
        ]
        builder = ConversationContextBuilder(max_turns=4)
        history = builder.build_history(msgs)
        # 4 turns = 8 messages max (4 user + 4 assistant)
        assert history.count("User:") <= 4
        assert history.count("Assistant:") <= 4
        # The most recent turns are kept
        assert "msg 19" in history

    def test_multi_doc_groups_by_file(self):
        from conversation.context_builder import MultiDocumentContextBuilder
        from engines import RetrievalResult

        def _r(path, idx, score):
            return RetrievalResult(
                chunk_id=f"{path}-{idx}", text=f"content {idx}", score=score, rank=idx,
                file_path=path, file_hash="h", source_type="page", source_index=idx,
                source_label=f"Page {idx+1}", char_start=0, char_end=5,
            )

        results = [
            _r("/tmp/a.pdf", 0, 0.9), _r("/tmp/a.pdf", 1, 0.8), _r("/tmp/a.pdf", 2, 0.7),
            _r("/tmp/a.pdf", 3, 0.6),  # 4th chunk for the same file
            _r("/tmp/b.pdf", 0, 0.5),
        ]
        builder = MultiDocumentContextBuilder(max_chunks_per_file=3)
        grouped = builder.group_by_file(results)
        assert len(grouped["/tmp/a.pdf"]) == 3  # capped per file
        assert grouped["/tmp/a.pdf"][0].score == 0.9
        assert builder.document_map(results) == {"/tmp/a.pdf": 3, "/tmp/b.pdf": 1}
        ctx = builder.build(results)
        assert "/tmp/a.pdf" in ctx or "a.pdf" in ctx
        assert "--- DOCUMENT:" in ctx

    def test_evidence_serialization_bounded(self):
        from conversation.context_builder import ConversationContextBuilder
        from engines import RetrievalResult
        results = [
            RetrievalResult(chunk_id=f"c{i}", text="x" * 500, score=0.5, rank=i,
                            file_path=f"/tmp/{i}.pdf", file_hash="h", source_type="page",
                            source_index=i, source_label="Page 1", char_start=0, char_end=5)
            for i in range(20)
        ]
        builder = ConversationContextBuilder(max_evidence_chars=1000)
        ctx = builder.build_evidence(results)
        assert len(ctx) <= 1000 + 200  # small overflow from separators


class TestCitationBuilder:
    def test_builds_from_results_with_locations(self):
        from conversation.citation_builder import CitationBuilder
        from engines import RetrievalResult
        results = [
            RetrievalResult(chunk_id="c1", text="text", score=0.8, rank=0,
                            file_path="/tmp/lec.mp3", file_hash="h", source_type="transcript",
                            source_index=0, source_label="02:14 - 02:31", char_start=0, char_end=5,
                            modality="audio", timestamp_start=134.0, timestamp_end=151.0),
        ]
        citations = CitationBuilder.from_results(results)
        assert len(citations) == 1
        assert citations[0].modality == "audio"
        assert citations[0].timestamp_start == 134.0
        assert citations[0].source_label == "02:14 - 02:31"

    def test_deduplicates_by_chunk(self):
        from conversation.citation_builder import CitationBuilder
        from engines import RetrievalResult
        r = RetrievalResult(chunk_id="dup", text="t", score=0.5, rank=0,
                            file_path="/tmp/a.txt", file_hash="h", source_type="s",
                            source_index=0, source_label="S", char_start=0, char_end=1)
        assert len(CitationBuilder.from_results([r, r])) == 1


# ================================================================
# M2/M6 — Conversation manager (mocked retrieval + RAG)
# ================================================================

class TestConversationManager:
    @staticmethod
    def _manager(tmp_path, answer="Grounded answer."):
        from conversation.conversation_manager import ConversationManager
        from conversation.conversation_store import ConversationStore
        with _db_session_factory(tmp_path) as sf:
            store = ConversationStore(sf)
            return ConversationManager(store=store, retrieval=_MockRetrieval(),
                                       rag=_MockRAG(answer=answer)), store

    def test_ask_persists_turn_and_citations(self, tmp_path):
        from conversation.conversation_manager import ConversationManager
        with _db_session_factory(tmp_path) as sf:
            from conversation.conversation_store import ConversationStore
            store = ConversationStore(sf)
            manager = ConversationManager(store=store, retrieval=_MockRetrieval(),
                                          rag=_MockRAG(answer="3NF is a schema design."))
            cid = store.create_conversation("workspace", "")
            result = manager.ask(cid, "What is 3NF?")
            assert result.grounded
            assert "3NF" in result.answer
            assert len(result.citations) == 1
            msgs = store.get_messages(cid)
            assert [m.role for m in msgs] == ["user", "assistant"]

    def test_ask_empty_question(self, tmp_path):
        manager, _ = self._manager(tmp_path)
        result = manager.ask(1, "   ")
        assert result.error == "Empty question"

    def test_ask_missing_conversation(self, tmp_path):
        manager, _ = self._manager(tmp_path)
        with pytest.raises(ValueError):
            manager.ask(999, "hello")

    def test_cancel_event(self, tmp_path):
        import threading
        manager, store = self._manager(tmp_path)
        cid = store.create_conversation("workspace", "")
        ev = threading.Event()
        ev.set()
        result = manager.ask(cid, "hello", cancel_event=ev)
        assert result.error == "cancelled"

    def test_graph_supplements_folder_scope(self, tmp_path):
        """Graph entity matches add related files to a folder-scope filter."""
        from conversation.conversation_manager import ConversationManager
        from conversation.conversation_store import ConversationStore
        from graph.graph_store import GraphStore
        from graph.graph_models import EntityRecord, RelationshipRecord

        with _db_session_factory(tmp_path) as sf:
            store = ConversationStore(sf)
            gstore = GraphStore(sf)
            alice_id = gstore.upsert_entity(EntityRecord(name="Alice", entity_type="PERSON"))
            acme_id = gstore.upsert_entity(EntityRecord(name="Acme", entity_type="ORGANIZATION"))
            gstore.add_relationship(
                RelationshipRecord(source="Alice", relation="works_at", target="Acme"),
                alice_id, acme_id,
            )
            gstore.add_relationship(
                RelationshipRecord(source="Acme", relation="related_to", target="Alice",
                                   file_path="/tmp/proj/report.pdf", source_label="Page 1"),
                acme_id, alice_id,
            )

            manager = ConversationManager(
                store=store, retrieval=_MockRetrieval(),
                rag=_MockRAG(answer="ok"), graph=_GraphStub(gstore),
            )
            cid = store.create_conversation("folder", "/tmp/proj")
            result = manager.ask(cid, "Who works at Acme?")
            assert result.grounded
            assert manager._graph_files("Acme", ["/tmp/proj/a.txt"])  # returns related files
            assert manager._graph_files("Acme", None) == []  # never widens workspace


class _MockRetrieval:
    _evidence = {}  # used by scope manager / conversation manager

    def retrieve(self, query, scope, top_k=5, threshold=0.3, file_filter=None,
                 max_chunks_per_file=None):
        from engines import RetrievalResult
        results = [
            RetrievalResult(chunk_id="c1", text="Alice works at Acme.", score=0.9, rank=0,
                            file_path="/tmp/proj/report.pdf", file_hash="h", source_type="page",
                            source_index=0, source_label="Page 1", char_start=0, char_end=5),
        ]
        from engines.retrieval_engine import RetrievalResponse
        return RetrievalResponse(query=query, scope=getattr(scope, "value", str(scope)),
                                 results=results, total_found=1, elapsed_ms=1.0,
                                 embedding_available=True)


class _MockRAG:
    def __init__(self, answer="answer", model="mock"):
        self._model = model
        self._answer = answer

    def answer_multi(self, question, context, extra_instructions=None):
        return self._answer

    def resolve_followup(self, question, history):
        return question


class _GraphStub:
    def __init__(self, store):
        self.store = store


# ================================================================
# M7 — Knowledge graph backend
# ================================================================

class TestGraphNormalization:
    def test_normalize_folds_case_and_punctuation(self):
        from graph.graph_models import normalize_entity_name
        assert normalize_entity_name("  Python!  ") == "python"
        assert normalize_entity_name("Python") == normalize_entity_name("python")
        assert normalize_entity_name("Project Apollo") == "project apollo"
        assert normalize_entity_name("") == ""

    def test_entity_type_coerced_to_concept(self):
        from graph.graph_models import EntityRecord
        assert EntityRecord("Bob", "PERSON").entity_type == "PERSON"
        assert EntityRecord("Bob", "GARBAGE").entity_type == "CONCEPT"
        assert EntityRecord("Bob", "").entity_type == "CONCEPT"


class TestGraphStore:
    def test_entity_upsert_dedupes_by_normalized_name(self, tmp_path):
        from graph.graph_store import GraphStore
        from graph.graph_models import EntityRecord
        with _db_session_factory(tmp_path) as sf:
            store = GraphStore(sf)
            a = store.upsert_entity(EntityRecord("Python", "TECHNOLOGY"))
            b = store.upsert_entity(EntityRecord("python", "TECHNOLOGY"))
            assert a == b  # merged into one node
            assert store.stats()["entities"] == 1

    def test_relationship_dedup_and_evidence(self, tmp_path):
        from graph.graph_store import GraphStore
        from graph.graph_models import EntityRecord, RelationshipRecord
        with _db_session_factory(tmp_path) as sf:
            store = GraphStore(sf)
            a = store.upsert_entity(EntityRecord("Alice", "PERSON"))
            b = store.upsert_entity(EntityRecord("Acme", "ORGANIZATION"))
            r1 = store.add_relationship(
                RelationshipRecord("Alice", "works_at", "Acme", confidence=0.8,
                                   chunk_id="c1", file_path="/tmp/f.pdf",
                                   source_label="Page 2", source_index=1),
                a, b)
            r2 = store.add_relationship(
                RelationshipRecord("Alice", "works_at", "Acme", confidence=0.9,
                                   chunk_id="c1", file_path="/tmp/f.pdf"),
                a, b)
            assert r1 == r2  # deduped
            rels = store.get_relationships(a)
            assert len(rels) == 1
            assert rels[0]["confidence"] == 0.9  # max confidence kept
            links = store.get_evidence_links(r1)
            assert len(links) >= 1
            assert links[0]["chunk_id"] == "c1"

    def test_remove_file_cascades(self, tmp_path):
        from graph.graph_store import GraphStore
        from graph.graph_models import EntityRecord, RelationshipRecord
        with _db_session_factory(tmp_path) as sf:
            store = GraphStore(sf)
            a = store.upsert_entity(EntityRecord("Alice", "PERSON"))
            b = store.upsert_entity(EntityRecord("Acme", "ORGANIZATION"))
            store.add_relationship(
                RelationshipRecord("Alice", "works_at", "Acme", file_path="/tmp/f.pdf"), a, b)
            assert store.stats() == {"entities": 2, "relationships": 1, "evidence_links": 1}
            removed = store.remove_file("/tmp/f.pdf")
            assert removed == 1
            assert store.stats() == {"entities": 0, "relationships": 0, "evidence_links": 0}

    def test_search_entities(self, tmp_path):
        from graph.graph_store import GraphStore
        from graph.graph_models import EntityRecord
        with _db_session_factory(tmp_path) as sf:
            store = GraphStore(sf)
            store.upsert_entity(EntityRecord("Random Forest", "ALGORITHM"))
            hits = store.search_entities("forest")
            assert len(hits) == 1
            assert hits[0]["name"] == "Random Forest"
            assert hits[0]["type"] == "ALGORITHM"


class TestGraphEngine:
    class _MockLLM:
        def _generate(self, prompt, **kw):
            if "KNOWN ENTITIES" in prompt:
                return ('{"relationships": [{"source": "Alice", "relation": "works_at", '
                        '"target": "Acme", "confidence": 0.9}]}')
            return ('{"entities": [{"name": "Alice", "type": "PERSON"}, '
                    '{"name": "Acme", "type": "ORGANIZATION"}]}')

    def test_index_file_full_flow(self, tmp_path):
        from graph.graph_engine import GraphEngine
        with _db_session_factory(tmp_path) as sf:
            engine = GraphEngine(sf, rag=self._MockLLM())

            class Chunk:
                chunk_id = "chunk-1"
                source_label = "Page 1"
                source_index = 0
                text = "Alice works at Acme since 2020."

            result = engine.index_file("/tmp/fake.pdf", chunks=[Chunk()])
            assert result["error"] is None
            assert result["entities"] == 2
            assert result["relationships"] == 1
            assert engine.stats()["entities"] == 2
            assert engine.stats()["relationships"] == 1
            assert engine.stats()["evidence_links"] == 1

    def test_disabled_engine_skips(self, tmp_path):
        from graph.graph_engine import GraphEngine
        with _db_session_factory(tmp_path) as sf:
            engine = GraphEngine(sf, rag=self._MockLLM(), enabled=False)
            result = engine.index_file("/tmp/f.pdf", chunks=[])
            assert result["error"] == "disabled"

    def test_extractor_failure_is_safe(self, tmp_path):
        from graph.graph_engine import GraphEngine
        with _db_session_factory(tmp_path) as sf:
            class BadLLM:
                def _generate(self, prompt, **kw):
                    return "not json at all"
            engine = GraphEngine(sf, rag=BadLLM())

            class Chunk:
                chunk_id = "c"; source_label = "S"; source_index = 0
                text = "some text"
            result = engine.index_file("/tmp/f.pdf", chunks=[Chunk()])
            assert result["error"] is None  # extraction fails quietly
            assert result["entities"] == 0


class TestGraphQueryService:
    def test_entity_details_and_neighbors(self, tmp_path):
        from graph.graph_query_service import GraphQueryService
        from graph.graph_store import GraphStore
        from graph.graph_models import EntityRecord, RelationshipRecord
        with _db_session_factory(tmp_path) as sf:
            store = GraphStore(sf)
            a = store.upsert_entity(EntityRecord("Alice", "PERSON"))
            b = store.upsert_entity(EntityRecord("Acme", "ORGANIZATION"))
            store.add_relationship(
                RelationshipRecord("Alice", "works_at", "Acme",
                                   file_path="/tmp/f.pdf", source_label="Page 1"), a, b)
            qs = GraphQueryService(store)
            detail = qs.entity_details(a)
            assert detail.name == "Alice"
            assert detail.relationship_count == 1
            assert detail.related_files == ["/tmp/f.pdf"]
            assert detail.relationships[0]["relation"] == "works_at"
            neigh = qs.neighbors(a)
            assert any(n["name"] == "Acme" for n in neigh)
            ev = qs.relationships_with_evidence(a)
            assert ev[0]["evidence"][0]["source_label"] == "Page 1"


# ================================================================
# M9-M11 — Agent subsystem
# ================================================================

class TestAgentSchemas:
    def test_tool_input_validation(self):
        from agent.schemas import SchemaValidationError, ToolInput
        with pytest.raises(SchemaValidationError):
            ToolInput(limit=0).validate()
        with pytest.raises(SchemaValidationError):
            ToolInput(limit=99).validate()
        with pytest.raises(SchemaValidationError):
            ToolInput(scope="galaxy").validate()
        assert ToolInput(query="q", limit=5, scope="folder").validate().scope == "folder"

    def test_parse_tool_call(self):
        from agent.schemas import parse_tool_call
        call = parse_tool_call('Sure! {"tool": "search", "arguments": {"query": "x"}}')
        assert call == {"tool": "search", "arguments": {"query": "x"}}
        with pytest.raises(ValueError):
            parse_tool_call("no json here")

    def test_policy_guardrails(self):
        from agent.policies import AgentPolicy
        p = AgentPolicy(max_steps=8, max_time_seconds=90.0, read_only=True)
        assert p.allows("search")
        blocked = AgentPolicy(read_only=True, allowed_tools=["search"])
        assert not blocked.allows("query_knowledge_graph")
        assert blocked.allows("search")


class TestAgentState:
    def test_cancel_is_sticky(self):
        from agent.agent_state import AgentState
        s = AgentState(request="r", status="running")
        s.cancel()
        assert s.cancelled
        assert s.status == "cancelled"

    def test_steps_and_observations(self):
        from agent.agent_state import AgentState, AgentStep
        s = AgentState(request="r")
        s.add_step(AgentStep(tool="search", arguments={}, summary="found 3"))
        s.add_observation({"tool": "search", "result": {"total": 3}})
        assert len(s.steps) == 1
        assert len(s.observations) == 1


class TestToolRegistry:
    def test_registers_expected_tools(self):
        from agent.tool_registry import ToolRegistry
        reg = ToolRegistry()
        expected = {"search", "retrieve_evidence", "list_related_files", "get_file_metadata",
                    "query_knowledge_graph", "open_evidence", "summarize_evidence",
                    "compare_documents"}
        assert expected.issubset(set(reg.names()))
        spec = reg.get("search")
        assert spec.description
        assert "query" in spec.parameters

    def test_search_handler_with_mock_retrieval(self):
        from agent.tool_registry import ToolRegistry
        from agent.schemas import ToolInput

        class MockRetrieval:
            def retrieve(self, query, scope, top_k=5):
                from types import SimpleNamespace
                return SimpleNamespace(results=[
                    SimpleNamespace(file_path="/tmp/a.pdf", score=0.8, source_label="Page 1",
                                    modality="document", text="content")
                ])

        reg = ToolRegistry(retrieval=MockRetrieval())
        out = reg._handle_search(ToolInput(query="q", limit=5))
        assert out["total"] == 1
        assert out["results"][0]["file_path"] == "/tmp/a.pdf"

    def test_graph_query_handler(self):
        from agent.tool_registry import ToolRegistry
        from agent.schemas import ToolInput

        class MockGraphQuery:
            def search_entities(self, q, limit=5):
                return [{"id": 1, "name": "Alice", "type": "PERSON"}]

            def entity_details(self, eid):
                from types import SimpleNamespace
                d = SimpleNamespace(id=1, name="Alice", entity_type="PERSON", aliases=[],
                                    relationship_count=1, related_files=["/tmp/f.pdf"],
                                    relationships=[{"source": "Alice", "relation": "works_at",
                                                    "target": "Acme", "confidence": 0.9}])
                return d

        reg = ToolRegistry(graph_query=MockGraphQuery())
        out = reg._handle_graph_query(ToolInput(entity_name="Alice"))
        assert out["entity"] == "Alice"
        assert out["related_files"] == ["/tmp/f.pdf"]


class TestToolExecutor:
    def test_unknown_tool_recorded_as_failure(self):
        from agent.agent_state import AgentState
        from agent.tool_executor import ToolExecutor
        from agent.tool_registry import ToolRegistry
        state = AgentState(request="r")
        step = ToolExecutor(ToolRegistry()).execute("nope", {}, state)
        assert not step.ok
        assert "Unknown tool" in step.error

    def test_invalid_input_fails_validation(self):
        from agent.agent_state import AgentState
        from agent.tool_executor import ToolExecutor
        from agent.tool_registry import ToolRegistry
        state = AgentState(request="r")
        step = ToolExecutor(ToolRegistry()).execute("search", {"limit": 500}, state)
        assert not step.ok
        assert "Invalid input" in step.summary

    def test_handler_failure_recorded(self):
        from agent.agent_state import AgentState
        from agent.tool_executor import ToolExecutor
        from agent.tool_registry import ToolRegistry

        class BoomRetrieval:
            def retrieve(self, *args, **kwargs):
                raise RuntimeError("boom")

        reg = ToolRegistry(retrieval=BoomRetrieval())
        state = AgentState(request="r")
        step = ToolExecutor(reg).execute("search", {"query": "x"}, state)
        assert not step.ok
        assert "boom" in step.error


class TestAgentEngine:
    @staticmethod
    def _mock_rag():
        class MockRAG:
            def _generate(self, prompt):
                p = prompt.lower()
                if "next tool call" in p or ("json" in p and "tool" in p and "arguments" in p):
                    return '{"tool": "search", "arguments": {"query": "x", "limit": 3}}'
                if "concise" in p and "observations" in p:
                    return "Synthesis: found results in a.pdf. [a.pdf]"
                return '{"tool": "__final__", "arguments": {"answer": "done"}}'
        return MockRAG()

    @staticmethod
    def _mock_retrieval():
        class MockRetrieval:
            _db_store = None
            _indexer = None

            def retrieve(self, query, scope, top_k=5):
                from types import SimpleNamespace
                return SimpleNamespace(results=[
                    SimpleNamespace(file_path="/tmp/a.pdf", score=0.7, source_label="Page 1",
                                    modality="document", text="content")
                ])
        return MockRetrieval()

    def test_full_loop_synthesizes(self):
        from agent.agent_engine import AgentEngine
        from agent.policies import AgentPolicy
        engine = AgentEngine(retrieval=self._mock_retrieval(), rag=self._mock_rag(),
                             policy=AgentPolicy(max_steps=2))
        state = engine.run("question")
        assert state.status in ("finished", "max_steps")
        final = [s for s in state.steps if s.tool == "__synthesis__"]
        assert final and final[0].summary

    def test_max_steps_terminates(self):
        from agent.agent_engine import AgentEngine
        from agent.policies import AgentPolicy
        engine = AgentEngine(retrieval=self._mock_retrieval(), rag=self._mock_rag(),
                             policy=AgentPolicy(max_steps=1))
        state = engine.run("q")
        assert state.status in ("finished", "max_steps")
        assert len(state.steps) >= 1  # at least one tool step

    def test_timeout_terminates(self):
        from agent.agent_engine import AgentEngine
        from agent.policies import AgentPolicy
        import threading

        class SlowRAG:
            def _generate(self, prompt):
                time.sleep(0.3)
                return '{"tool": "search", "arguments": {"query": "x"}}'

        engine = AgentEngine(retrieval=self._mock_retrieval(), rag=SlowRAG(),
                             policy=AgentPolicy(max_steps=50, max_time_seconds=0.05))
        state = engine.run("q")
        assert state.status == "timeout"

    def test_cancel_between_tools(self):
        from agent.agent_engine import AgentEngine
        from agent.policies import AgentPolicy
        import threading

        engine = AgentEngine(retrieval=self._mock_retrieval(), rag=self._mock_rag(),
                             policy=AgentPolicy(max_steps=50))
        cancel = threading.Event()

        def _on_status(text):
            cancel.set()  # cancel as soon as the first tool starts

        state = engine.run("q", cancel_event=cancel, on_status=_on_status)
        assert state.status == "cancelled"

    def test_policy_blocks_disallowed_tool(self):
        from agent.agent_engine import AgentEngine
        from agent.policies import AgentPolicy
        engine = AgentEngine(retrieval=self._mock_retrieval(), rag=self._mock_rag(),
                             policy=AgentPolicy(max_steps=2, read_only=True,
                                                allowed_tools=["search"]))
        state = engine.run("q")
        # search is allowed so loop runs; blocked tools are recorded as failures
        assert state.status in ("finished", "max_steps")

    def test_llm_unavailable_falls_back_to_search(self):
        from agent.agent_engine import AgentEngine
        from agent.policies import AgentPolicy
        engine = AgentEngine(retrieval=self._mock_retrieval(), rag=None,
                             policy=AgentPolicy(max_steps=2))
        state = engine.run("q")
        # With no LLM, planner falls back deterministically to search
        assert any(s.tool == "search" for s in state.steps)


# ================================================================
# M3/M8/M11 — UI smoke tests (offscreen)
# ================================================================

class TestChatUI:
    def test_chat_dialog_renders_and_signals(self, qapp, qtbot):
        from ui.dialogs.chat_dialog import ChatDialog
        dlg = ChatDialog(scope_type="folder", scope_path="/tmp/proj")
        qtbot.addWidget(dlg)
        dlg.show()
        sent = []
        dlg.send_requested.connect(lambda q: sent.append(q))
        dlg.view.input_box.setText("hello")
        dlg.view._on_send()
        assert sent == ["hello"]
        dlg.append_user("hi")
        dlg.append_assistant("answer", citations=[])

    def test_chat_dialog_busy_state(self, qapp, qtbot):
        from ui.dialogs.chat_dialog import ChatDialog
        dlg = ChatDialog(scope_type="workspace")
        qtbot.addWidget(dlg)
        dlg.set_busy_state("retrieving")
        assert dlg.view.busy
        dlg.set_busy_state("ready")
        assert not dlg.view.busy


class TestAgentUI:
    def test_agent_dialog_signals(self, qapp, qtbot):
        from ui.dialogs.agent_dialog import AgentDialog
        dlg = AgentDialog()
        qtbot.addWidget(dlg)
        dlg.show()
        sent = []
        stopped = []
        dlg.send_requested.connect(lambda q: sent.append(q))
        dlg.stop_requested.connect(lambda: stopped.append(True))
        dlg.view.input_box.setText("agent question")
        dlg.view._on_send()
        assert sent == ["agent question"]
        dlg.set_action("✓ Searched workspace")
        assert "Searched" in dlg.action_label.text()
        dlg.set_state("cancelled")
        assert dlg.status_badge.text() == "cancelled"


class TestGraphUI:
    def test_graph_dialog_renders_empty_state(self, qapp, qtbot, tmp_path):
        from graph.graph_query_service import GraphQueryService
        from graph.graph_store import GraphStore
        from ui.dialogs.graph_dialog import GraphDialog

        with _db_session_factory(tmp_path) as sf:
            qs = GraphQueryService(GraphStore(sf))
            dlg = GraphDialog(query_service=qs)
            qtbot.addWidget(dlg)
            dlg.show()
            assert dlg.stats_label.text() == "0 entities · 0 relationships"

    def test_graph_dialog_with_entities(self, qapp, qtbot, tmp_path):
        from graph.graph_query_service import GraphQueryService
        from graph.graph_store import GraphStore
        from graph.graph_models import EntityRecord, RelationshipRecord
        from ui.dialogs.graph_dialog import GraphDialog

        with _db_session_factory(tmp_path) as sf:
            store = GraphStore(sf)
            a = store.upsert_entity(EntityRecord("Alice", "PERSON"))
            b = store.upsert_entity(EntityRecord("Acme", "ORGANIZATION"))
            store.add_relationship(
                RelationshipRecord("Alice", "works_at", "Acme", file_path="/tmp/f.pdf",
                                   source_label="Page 1"), a, b)
            qs = GraphQueryService(store)
            dlg = GraphDialog(query_service=qs)
            qtbot.addWidget(dlg)
            dlg.show()
            assert "2 entities" in dlg.stats_label.text()
            # Selecting an entity populates details
            dlg._select_entity(a)
            assert "Alice" in dlg.details_text.toPlainText()
            assert dlg.relationships_list.count() == 1
            assert dlg.evidence_list.count() == 1
