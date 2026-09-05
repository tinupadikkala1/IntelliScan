"""Batch 7 tests — document comparison (B7-5)."""

import os
import sys
import tempfile

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


class _FakeRag:
    def __init__(self, answer="Changes are meaningful."):
        self._answer = answer
        self.calls = 0

    def _generate(self, prompt):
        self.calls += 1
        return self._answer


class TestDocumentComparison:
    def _svc(self, rag=None, retrieval=None):
        from services.document_comparison_service import DocumentComparisonService

        return DocumentComparisonService(rag_engine=rag, retrieval_engine=retrieval)

    def _write(self, tmp_path, name, text):
        p = tmp_path / name
        p.write_text(text, encoding="utf-8")
        return str(p)

    def test_identical_docs(self, tmp_path):
        a = self._write(tmp_path, "a.txt", "hello world\nsecond line\n")
        b = self._write(tmp_path, "b.txt", "hello world\nsecond line\n")
        result = self._svc(rag=_FakeRag()).compare(a, b)
        assert result.error == ""
        assert result.textual.unchanged_ratio > 0.99
        assert result.structural_a.word_count == result.structural_b.word_count

    def test_addition_detected(self, tmp_path):
        a = self._write(tmp_path, "a.txt", "line one\nline two\n")
        b = self._write(tmp_path, "b.txt", "line one\nline two\nbrand new line\n")
        result = self._svc(rag=_FakeRag()).compare(a, b)
        assert result.textual.added_chars > 0
        assert any("brand new line" in l for l in result.textual.added_lines)

    def test_removal_detected(self, tmp_path):
        a = self._write(tmp_path, "a.txt", "keep me\ndelete me\n")
        b = self._write(tmp_path, "b.txt", "keep me\n")
        result = self._svc(rag=_FakeRag()).compare(a, b)
        assert result.textual.removed_chars > 0
        assert any("delete me" in l for l in result.textual.removed_lines)

    def test_reordered_content(self, tmp_path):
        a = self._write(tmp_path, "a.txt", "first part\nsecond part\n")
        b = self._write(tmp_path, "b.txt", "second part\nfirst part\n")
        result = self._svc(rag=_FakeRag()).compare(a, b)
        # Same words → unchanged ratio still high.
        assert result.textual.unchanged_ratio >= 0.5
        assert result.error == ""

    def test_unsupported_format(self, tmp_path):
        from services.document_comparison_service import DocumentComparisonService

        a = self._write(tmp_path, "a.bin", "x")
        b = self._write(tmp_path, "b.txt", "y")
        svc = DocumentComparisonService()
        result = svc.compare(a, b)
        assert result.error

    def test_cross_format_comparison(self, tmp_path):
        from services.document_comparison_service import DocumentComparisonService
        a = self._write(tmp_path, "chart.png", "Image OCR Text: Quarterly Sales Chart 2024")
        b = self._write(tmp_path, "report.pdf", "Executive Summary: Fiscal Year 2024 Sales Performance")
        svc = self._svc(rag=_FakeRag())
        result = svc.compare(a, b)
        assert result.error == ""
        assert result.structural_a.format == "png"
        assert result.structural_b.format == "pdf"
        assert result.semantic_summary != ""

    def test_structural_pdf_pages(self):
        # PDF page counts come from form feeds in the extracted text.
        svc = self._svc()
        stats_a = svc._structural("x.pdf", "page one\fpage two\fpage three")
        stats_b = svc._structural("x.pdf", "page one\fpage two")
        assert stats_a.page_or_section_count == 3
        assert stats_b.page_or_section_count == 2
        assert stats_a.format == "pdf"

    def test_semantic_summary_generated(self, tmp_path):
        rag = _FakeRag()
        a = self._write(tmp_path, "a.txt", "version one content\n")
        b = self._write(tmp_path, "b.txt", "version two content\n")
        result = self._svc(rag=rag).compare(a, b)
        assert "Content Verdict:" in result.semantic_summary
        assert result.semantic_summary.endswith("Changes are meaningful.")
        assert rag.calls >= 1

    def test_missing_file(self, tmp_path):
        a = self._write(tmp_path, "a.txt", "content")
        result = self._svc().compare(a, str(tmp_path / "missing.txt"))
        assert result.error

    def test_same_file(self, tmp_path):
        a = self._write(tmp_path, "a.txt", "content")
        result = self._svc().compare(a, a)
        assert result.textual.unchanged_ratio > 0.99

    def test_structural_headings(self, tmp_path):
        a = self._write(tmp_path, "a.md", "# Heading One\nbody\n## Sub\nmore\n")
        result = self._svc().compare(a, a)
        assert result.structural_a.headings  # markdown headings detected

    def test_numerical_audit_detection(self, tmp_path):
        a_txt = "Invoice ID: INV-1001\nTotal: $500.00\nDiscount: 10%\nDue Date: 2024-05-10\nItem: Widget A"
        b_txt = "Invoice ID: INV-1001\nTotal: $750.00\nDiscount: 15%\nDue Date: 2024-05-15\nItem: Widget B"
        a = self._write(tmp_path, "inv_a.txt", a_txt)
        b = self._write(tmp_path, "inv_b.txt", b_txt)
        result = self._svc().compare(a, b)
        assert result.error == ""
        assert len(result.numerical_audit) > 0
        categories = [item["category"] for item in result.numerical_audit]
        assert "Currency / Amount" in categories
        # Currency changed
        currency_items = [item for item in result.numerical_audit if item["category"] == "Currency / Amount"]
        assert any(item["status"] == "Changed" for item in currency_items)

    def test_side_by_side_html_diff(self, tmp_path):
        a = self._write(tmp_path, "a.txt", "Alpha\nBeta\nGamma\n")
        b = self._write(tmp_path, "b.txt", "Alpha\nBeta Modified\nGamma\nDelta\n")
        result = self._svc().compare(a, b)
        assert "<table" in result.side_by_side_html
        assert "diff_chg" in result.side_by_side_html or "diff_add" in result.side_by_side_html

    def test_export_report_html_and_markdown(self, tmp_path):
        a = self._write(tmp_path, "doc1.txt", "Budget: $1000\nYear: 2025\n")
        b = self._write(tmp_path, "doc2.txt", "Budget: $1200\nYear: 2025\n")
        svc = self._svc()
        result = svc.compare(a, b)

        html_out = str(tmp_path / "report.html")
        md_out = str(tmp_path / "report.md")

        assert svc.export_report(result, html_out) is True
        assert os.path.isfile(html_out)
        with open(html_out, "r", encoding="utf-8") as f:
            html_content = f.read()
            assert "Document Comparison Report" in html_content
            assert "Numerical & Entity Audit Table" in html_content

        assert svc.export_report(result, md_out) is True
        assert os.path.isfile(md_out)
        with open(md_out, "r", encoding="utf-8") as f:
            md_content = f.read()
            assert "# Document Comparison Report" in md_content
            assert "Numerical & Entity Audit Table" in md_content


class TestDocumentComparisonDialog:
    def test_dialog_constructs(self, qapp, tmp_path):
        from services.document_comparison_service import DocumentComparisonService
        from ui.dialogs.document_comparison_dialog import DocumentComparisonDialog

        p = tmp_path / "a.txt"
        p.write_text("hello")
        dlg = DocumentComparisonDialog(DocumentComparisonService(), file_a=str(p))
        assert dlg._file_a == str(p)
        dlg.close()

    def test_same_file_rejected(self, qapp, tmp_path):
        from services.document_comparison_service import DocumentComparisonService
        from ui.dialogs.document_comparison_dialog import DocumentComparisonDialog

        p = tmp_path / "a.txt"
        p.write_text("hello")
        dlg = DocumentComparisonDialog(DocumentComparisonService(),
                                       file_a=str(p), file_b=str(p))
        dlg._on_compare()
        assert "same file" in dlg.status_label.text().lower()
        dlg.close()

    def test_dialog_render_results(self, qapp, tmp_path):
        from services.document_comparison_service import DocumentComparisonService
        from ui.dialogs.document_comparison_dialog import DocumentComparisonDialog

        svc = DocumentComparisonService()
        p1 = tmp_path / "f1.txt"
        p2 = tmp_path / "f2.txt"
        p1.write_text("Invoice: $500\nDate: 2024-01-01")
        p2.write_text("Invoice: $600\nDate: 2024-01-01")

        result = svc.compare(str(p1), str(p2))
        dlg = DocumentComparisonDialog(svc, file_a=str(p1), file_b=str(p2))
        dlg._render_results(result)

        assert dlg.audit_table.rowCount() > 0
        assert dlg.metrics_table.rowCount() > 0
        assert "Match" in dlg.verdict_card.text()
        assert "<table" in dlg.diff_browser.toHtml()
        dlg.close()

    def test_pdf_vs_image_distinction(self, tmp_path):
        from services.document_comparison_service import DocumentComparisonService, get_file_type_info
        svc = DocumentComparisonService()

        cat_pdf, type_pdf = get_file_type_info("sample.pdf")
        cat_img, type_img = get_file_type_info("scan.png")
        assert cat_pdf == "Document" and "PDF" in type_pdf
        assert cat_img == "Image" and "Image" in type_img

        stats_pdf = svc._structural("doc.pdf", "Page 1\fPage 2")
        stats_img = svc._structural("doc.png", "HEADER OCR\nLine 1\nLine 2")

        assert stats_pdf.page_or_section_count == 2
        # An image must not count newlines as multiple pages or sections!
        assert stats_img.page_or_section_count == 1
        assert stats_img.headings == []
        assert "Image" in stats_img.media_type

    def test_dialog_pdf_vs_image_rendering(self, qapp, tmp_path):
        from services.document_comparison_service import DocumentComparisonService, ComparisonResult, StructuralStats, TextualDiff
        from ui.dialogs.document_comparison_dialog import DocumentComparisonDialog

        svc = DocumentComparisonService()
        pdf_path = str(tmp_path / "report.pdf")
        img_path = str(tmp_path / "diagram.png")

        res = ComparisonResult(
            file_a=pdf_path,
            file_b=img_path,
            structural_a=svc._structural(pdf_path, "Intro\fSection 2"),
            structural_b=svc._structural(img_path, "Chart text"),
            textual=TextualDiff(unchanged_ratio=0.3, added_chars=10, removed_chars=20),
            semantic_summary="Comparison summary",
        )

        dlg = DocumentComparisonDialog(svc, file_a=pdf_path, file_b=img_path)
        dlg._render_results(res)

        # Check verdict card mentions both types
        verdict_text = dlg.verdict_card.text()
        assert "PDF Document" in verdict_text
        assert "Image" in verdict_text

        # Check metrics table
        found_pages = False
        for row in range(dlg.metrics_table.rowCount()):
            metric_name = dlg.metrics_table.item(row, 0).text()
            if metric_name == "Pages / Sections":
                val_a = dlg.metrics_table.item(row, 1).text()
                val_b = dlg.metrics_table.item(row, 2).text()
                assert "Pages" in val_a
                assert "Single Image Frame" in val_b
                found_pages = True
            elif metric_name == "Detected Headings":
                val_b = dlg.metrics_table.item(row, 2).text()
                assert "N/A" in val_b

        assert found_pages
        dlg.close()


