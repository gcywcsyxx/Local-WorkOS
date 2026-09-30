"""Domain-contract and safety regression tests; only unittest + stdlib required.

Run: python -m unittest discover -s tests -p test_engine.py -v
Real PDF tests run when optional pypdf is installed. Stub tests always cover the
optional dependency boundary, physical page preservation, and scanned-PDF notice.
"""
from __future__ import annotations

from datetime import date, timedelta
from io import BytesIO
import copy
import hashlib
import importlib.util
import json
import math
import random
import stat
import sys
from types import SimpleNamespace
import unittest
from unittest import mock
import zipfile

from workos import engine
from workos.demo import demo_data
from workos.engine import (calculate_model, chunk_text, local_answer, meeting_draft,
                           parse_upload, retrieve)


def make_docx(xml: bytes | None = None, extras: list | None = None) -> bytes:
    if xml is None:
        xml = (b'<?xml version="1.0" encoding="UTF-8"?>'
               b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
               b'<w:body><w:p><w:r><w:t>Revenue 218</w:t><w:tab/><w:t>EBITDA 28</w:t>'
               b'</w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Table cell</w:t></w:r>'
               b'</w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml)
        for name, data in extras or []:
            archive.writestr(name, data)
    return output.getvalue()


def fake_pdf(pages: list[str | None], *, encrypted: bool = False):
    reader = SimpleNamespace(is_encrypted=encrypted,
                             pages=[SimpleNamespace(extract_text=lambda value=text: value) for text in pages])
    return mock.patch.dict(sys.modules, {"pypdf": SimpleNamespace(PdfReader=lambda *args, **kwargs: reader)})


def tiny_real_pdf() -> bytes:
    """Two plain-text physical pages with a standard PDF font, no external data."""
    streams = [b"BT /F1 12 Tf 30 100 Td (Beichen revenue 218) Tj ET",
               b"BT /F1 12 Tf 30 100 Td (Yuanshan capacity 4200) Tj ET"]
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Resources << /Font << /F1 5 0 R >> >> /Contents 7 0 R >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    objects.extend(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream" for stream in streams)
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(output)


class UploadTests(unittest.TestCase):
    def test_utf8_bom_markdown_and_newlines(self):
        parsed = parse_upload("研究.MD", b"\xef\xbb\xbf" + "# 模拟\r\n收入 218\r\n".encode())
        self.assertEqual(parsed["content"], "# 模拟\n收入 218")
        self.assertEqual(parsed["page_count"], 1)
        self.assertIsNone(parsed["pages"][0]["page"])
        self.assertEqual(parsed["pages"][0]["text"], parsed["content"])
        self.assertEqual(set(parsed), {"content", "page_count", "pages", "warnings"})

    def test_utf16_and_gb18030(self):
        for encoding in ("utf-16", "gb18030"):
            with self.subTest(encoding=encoding):
                parsed = parse_upload("模拟.txt", "北辰机器人收入".encode(encoding))
                self.assertEqual(parsed["content"], "北辰机器人收入")
                if encoding == "gb18030":
                    self.assertTrue(any("GB18030" in warning for warning in parsed["warnings"]))

    def test_invalid_uploads_raise_chinese_value_error(self):
        for name, content in [("x.exe", b"x"), ("x.docm", b"x"), ("", b"x"),
                              ("x.txt", b""), ("x.txt", b"   \n"), ("x.txt", "not bytes"),
                              ("x.txt", b"binary\x00text"), ("x.txt", b"binary\x01text"),
                              ("x.txt", b"\xff"), ("bad\x00.txt", b"x")]:
            with self.subTest(name=name, content=content):
                with self.assertRaisesRegex(ValueError, r"[\u3400-\u9fff]"):
                    parse_upload(name, content)

    def test_upload_size_limit(self):
        with mock.patch.object(engine, "MAX_UPLOAD_BYTES", 20):
            with self.assertRaisesRegex(ValueError, "12MB"):
                parse_upload("x.txt", b"x" * 21)

    def test_docx_body_and_table_without_fabricated_pages(self):
        parsed = parse_upload("example.docx", make_docx())
        self.assertEqual(parsed["content"], "Revenue 218\tEBITDA 28\nTable cell")
        self.assertIsNone(parsed["pages"][0]["page"])
        self.assertTrue(any("无法确定排版页码" in warning for warning in parsed["warnings"]))

    def test_docx_ignores_macros_links_and_embedded_objects(self):
        parsed = parse_upload("safe.docx", make_docx(extras=[
            ("word/vbaProject.bin", b"unexecuted macro data"),
            ("word/_rels/document.xml.rels", b'<Relationship Target="https://invalid.example/"/>'),
            ("word/embeddings/object.bin", b"unexecuted object")]))
        self.assertNotIn("macro", parsed["content"])
        self.assertNotIn("invalid.example", parsed["content"])
        self.assertTrue(any("不会执行宏" in warning for warning in parsed["warnings"]))

    def test_docx_rejects_zip_slip_and_drive_paths(self):
        for path in ("../outside.txt", "/absolute.txt", "C:/outside.txt", "word/../../outside.txt", "..\\outside.txt"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(ValueError, "不安全"):
                    parse_upload("x.docx", make_docx(extras=[(path, b"x")]))

    def test_docx_rejects_symlinks(self):
        link = zipfile.ZipInfo("word/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaisesRegex(ValueError, "符号链接"):
            parse_upload("x.docx", make_docx(extras=[(link, b"/etc/passwd")]))

    def test_docx_rejects_duplicate_members(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            packed = make_docx(extras=[("word/document.xml", b"duplicate")])
        with self.assertRaisesRegex(ValueError, "重复"):
            parse_upload("x.docx", packed)

    def test_docx_expansion_limits(self):
        packed = make_docx(extras=[("word/filler.bin", b"a" * 2000)])
        with mock.patch.object(engine, "MAX_DOCX_EXPANDED_BYTES", 1000):
            with self.assertRaisesRegex(ValueError, "解压量"):
                parse_upload("x.docx", packed)
        with mock.patch.object(engine, "MAX_DOCX_MEMBER_BYTES", 1000):
            with self.assertRaisesRegex(ValueError, "解压量"):
                parse_upload("x.docx", packed)

    def test_docx_rejects_dtd_entities_utf8_and_utf16(self):
        xml = ('<?xml version="1.0" encoding="ENCODING"?>'
               '<!DOCTYPE document [<!ENTITY bomb "bad">]>'
               '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
               '<w:body><w:p><w:r><w:t>&bomb;</w:t></w:r></w:p></w:body></w:document>')
        for encoding in ("utf-8", "utf-16"):
            with self.subTest(encoding=encoding):
                with self.assertRaisesRegex(ValueError, "实体"):
                    parse_upload("x.docx", make_docx(xml.replace("ENCODING", encoding).encode(encoding)))

    def test_docx_malformed_archive_and_xml(self):
        for packed in (b"not a zip", make_docx(b"<broken>"), make_docx(b"<notdocx/>")):
            with self.subTest(packed=packed[:20]):
                with self.assertRaisesRegex(ValueError, r"[\u3400-\u9fff]"):
                    parse_upload("x.docx", packed)
        output = BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("other.xml", "<x/>")
        with self.assertRaisesRegex(ValueError, "缺少正文"):
            parse_upload("x.docx", output.getvalue())

    def test_pdf_dependency_is_optional_and_failure_is_actionable(self):
        with mock.patch.dict(sys.modules, {"pypdf": None}):
            with self.assertRaisesRegex(ValueError, "可选依赖 pypdf"):
                parse_upload("x.pdf", b"%PDF")
        self.assertEqual(parse_upload("x.txt", b"still works")["content"], "still works")

    def test_pdf_pages_and_scanned_page_warning(self):
        with fake_pdf(["first page", None, "third page"]):
            parsed = parse_upload("x.pdf", b"%PDF")
        self.assertEqual(parsed["page_count"], 3)
        self.assertEqual([p["page"] for p in parsed["pages"]], [1, 2, 3])
        self.assertTrue(any("OCR" in warning for warning in parsed["warnings"]))
        chunks = chunk_text(parsed["content"], parsed["pages"])
        self.assertEqual([chunk["page"] for chunk in chunks], [1, 3])

    def test_pdf_scanned_only_does_not_invent_text(self):
        with fake_pdf([None]):
            parsed = parse_upload("scan.pdf", b"%PDF")
        self.assertEqual(parsed["content"], "")
        self.assertEqual(chunk_text(parsed["content"], parsed["pages"]), [])
        self.assertIn("不支持自动 OCR", " ".join(parsed["warnings"]))

    def test_pdf_encryption_page_and_text_limits(self):
        with fake_pdf(["hello"], encrypted=True):
            with self.assertRaisesRegex(ValueError, "加密"):
                parse_upload("x.pdf", b"%PDF")
        with fake_pdf(["one", "two"]), mock.patch.object(engine, "MAX_PDF_PAGES", 1):
            with self.assertRaisesRegex(ValueError, "页"):
                parse_upload("x.pdf", b"%PDF")
        with fake_pdf(["many words"]), mock.patch.object(engine, "MAX_TEXT_CHARS", 2):
            with self.assertRaisesRegex(ValueError, "大小限制"):
                parse_upload("x.pdf", b"%PDF")

    def test_pdf_unexpected_parse_failure_becomes_value_error(self):
        with mock.patch.dict(sys.modules, {"pypdf": SimpleNamespace(PdfReader=mock.Mock(side_effect=RuntimeError("bad")))}):
            with self.assertRaisesRegex(ValueError, "PDF 文件损坏"):
                parse_upload("x.pdf", b"%PDF")

    @unittest.skipUnless(importlib.util.find_spec("pypdf"), "可选 pypdf 未安装；其余解析边界照常测试")
    def test_real_pdf_text_extraction_and_locations(self):
        parsed = parse_upload("synthetic.pdf", tiny_real_pdf())
        self.assertEqual(parsed["page_count"], 2)
        self.assertIn("Beichen revenue 218", parsed["pages"][0]["text"])
        self.assertIn("Yuanshan capacity 4200", parsed["pages"][1]["text"])
        citations = retrieve("Yuanshan capacity", [{"id": "pdf", "title": "Synthetic PDF",
                            "content": parsed["content"], "chunks": chunk_text(parsed["content"], parsed["pages"])}])
        self.assertEqual(citations[0]["page"], 2)


class ChunkAndRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.docs = [
            {"id": "north", "title": "北辰机器人收入（模拟）",
             "content": "[模拟] 北辰机器人管理账收入为218百万元，尚未经审计。不同口径的预测收入为240百万元。"},
            {"id": "far", "title": "远山算力容量（模拟）",
             "content": "[模拟] 远山算力已安装4200卡，在租3000卡；扩容计划为8000卡。"},
            {"id": "english", "title": "Beichen Robotics (synthetic)",
             "content": "Synthetic only. Beichen Robotics revenue was 218 million; gross margin excludes power costs."},
        ]

    def test_chunks_stable_bounded_and_quote_exact_original(self):
        text = "[模拟] 北辰收入与原文定位。" * 300
        chunks = chunk_text(text)
        self.assertEqual(chunks, chunk_text(text))
        self.assertGreater(len(chunks), 3)
        self.assertEqual([chunk["ordinal"] for chunk in chunks], list(range(1, len(chunks) + 1)))
        self.assertEqual(len({chunk["id"] for chunk in chunks}), len(chunks))
        for chunk in chunks:
            self.assertLessEqual(len(chunk["text"]), 900)
            self.assertIn(chunk["text"], text)
            self.assertIsNone(chunk["page"])

    def test_chunk_does_not_cross_pdf_page_boundary(self):
        chunks = chunk_text("ignored joined text", [{"page": 2, "text": "second physical page"},
                                                    {"page": 5, "text": "fifth physical page"}])
        self.assertEqual([(c["page"], c["ordinal"]) for c in chunks], [(2, 1), (5, 2)])
        self.assertNotIn("ignored", str(chunks))
        self.assertEqual(chunk_text(" \n"), [])
        self.assertEqual(chunk_text("", []), [])

    def test_chunk_invalid_inputs(self):
        for args in [(None,), ("x", {}), ("x", ["bad"]), ("x", [{"page": 0, "text": "x"}]),
                     ("x", [{"page": True, "text": "x"}]), ("x", [{"page": 1, "text": 1}])]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                chunk_text(*args)

    def test_chinese_keywords_retrieve_only_relevant_document(self):
        citations = retrieve("北辰机器人的收入是多少？", self.docs)
        self.assertTrue(citations)
        self.assertEqual({c["document_id"] for c in citations}, {"north"})
        self.assertIn("218", citations[0]["quote"])
        self.assertIn(citations[0]["quote"], self.docs[0]["content"])
        self.assertEqual(set(citations[0]), {"id", "document_id", "title", "page", "ordinal", "quote"})

    def test_english_keywords_case_and_whole_word_matching(self):
        citations = retrieve("What is BEICHEN Robotics revenue?", self.docs)
        self.assertEqual(citations[0]["document_id"], "english")
        self.assertEqual(retrieve("cat", [{"id": "a", "title": "Education", "content": "Education category"}]), [])

    def test_english_phrase_occurrence_improves_rank(self):
        docs = [{"id": "separate", "title": "Overview", "content": "Synthetic gross costs and net margin."},
                {"id": "phrase", "title": "Overview", "content": "Synthetic gross margin measurement."}]
        self.assertEqual(retrieve('"gross margin"', docs)[0]["document_id"], "phrase")

    def test_irrelevant_queries_do_not_force_citations(self):
        docs = self.docs + [{"id": "generic", "title": "模拟资料", "content": "普通经营风险尚需核实，收入数字未经审计。"}]
        for question in ("火星移民风险", "火星移民有哪些风险", "Mars colony revenue",
                         "量子纠缠实验结果", "what is the", "2025", "与和的吗？"):
            with self.subTest(question=question):
                self.assertEqual(retrieve(question, docs), [])
        self.assertEqual(retrieve("北辰收入", []), [])

    def test_generic_metric_query_is_allowed_but_title_alone_is_not(self):
        self.assertTrue(retrieve("收入", self.docs))
        document = {"id": "x", "title": "Mars revenue", "content": "Unrelated oceans and coral reefs."}
        self.assertEqual(retrieve("Mars revenue", [document]), [])
        self.assertEqual(retrieve("北辰收入", [{"title": "北辰", "content": "北辰收入218"}]), [])

    def test_existing_chunks_locations_and_unique_citation_ids(self):
        docs = [{"id": "a", "title": "北辰资料", "content": "", "chunks": [
            {"id": "same", "page": 3, "ordinal": 7, "text": "北辰机器人收入218"}]},
                {"id": "b", "title": "北辰资料", "content": "", "chunks": [
            {"id": "same", "page": 1, "ordinal": 1, "text": "北辰机器人收入240"}]}]
        citations = retrieve("北辰机器人收入", docs)
        self.assertEqual(len(citations), 2)
        self.assertEqual((citations[0]["page"], citations[0]["ordinal"]), (3, 7))
        self.assertNotEqual(citations[0]["id"], citations[1]["id"])

    def test_limit_deduplication_and_stable_order(self):
        docs = [{"id": str(index), "title": "北辰收入", "content": "北辰收入218"} for index in range(10)]
        self.assertEqual(len(retrieve("北辰收入", docs)), 6)
        self.assertEqual(len(retrieve("北辰收入", docs, 2)), 2)
        self.assertEqual(retrieve("北辰收入", docs, 0), [])
        self.assertEqual(retrieve("北辰收入", docs), retrieve("北辰收入", docs))
        for invalid in (-1, 51, True, 2.0):
            with self.subTest(limit=invalid), self.assertRaises(ValueError):
                retrieve("北辰收入", docs, invalid)
        duplicate = {"id": "x", "title": "北辰", "chunks": [
            {"id": "1", "text": "北辰收入218"}, {"id": "2", "text": "北辰收入218"}]}
        self.assertEqual(len(retrieve("北辰收入", [duplicate])), 1)

    def test_long_existing_chunk_excerpt_is_bounded_and_exact(self):
        content = "背景材料。" * 400 + "Beichen revenue is synthetic." + "尾部说明。" * 200
        citations = retrieve("Beichen revenue", [{"id": "x", "title": "Example", "chunks": [{"text": content}]}])
        self.assertEqual(len(citations), 1)
        self.assertLessEqual(len(citations[0]["quote"]), 900)
        self.assertIn(citations[0]["quote"], content)
        self.assertIn("Beichen revenue", citations[0]["quote"])

    def test_local_answer_is_explicitly_unverified_excerpts(self):
        citations = retrieve("北辰收入", self.docs)
        original = copy.deepcopy(citations)
        result = local_answer("北辰收入", citations)
        self.assertEqual(result["mode"], "local")
        self.assertEqual(result["citations"], citations)
        self.assertIn("原文摘录", result["answer"])
        self.assertIn("不是已验证事实", result["answer"])
        self.assertIn("不同日期或口径", result["warning"])
        self.assertIn(citations[0]["quote"], result["answer"])
        result["citations"][0]["quote"] = "changed"
        self.assertEqual(citations, original)

    def test_local_answer_empty_never_claims_an_answer(self):
        result = local_answer("没有材料支持的问题", [])
        self.assertEqual(result["citations"], [])
        self.assertIn("未找到", result["answer"])
        self.assertIn("不猜测", result["answer"])
        for args in [("", []), ("x", None), ("x", [{}])]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                local_answer(*args)


class MeetingTests(unittest.TestCase):
    def test_explicit_owner_due_and_exact_source_quotes(self):
        transcript = ("收入范围仍待核实，不能形成投资结论。\n"
                      "下一步：核对合同；负责人：张晨；截止：2026-04-18。\n"
                      "待办：由李然负责补充验收材料；最晚2026年4月20日。")
        draft = meeting_draft(transcript)
        self.assertEqual(draft["mode"], "rules")
        self.assertEqual(len(draft["actions"]), 2)
        self.assertEqual([(a["owner"], a["due"]) for a in draft["actions"]], [("张晨", "2026-04-18"), ("李然", "2026-04-20")])
        for action in draft["actions"]:
            self.assertIn(action["source_quote"], transcript)
            self.assertEqual(set(action), {"title", "owner", "due", "source_quote"})
        self.assertIn("收入范围仍待核实，不能形成投资结论。", draft["summary"])
        self.assertIn("原文摘录", draft["summary"])
        self.assertIn("逐条确认", draft["warning"])

    def test_no_inferred_owner_or_due(self):
        transcript = "王晨：下一步核对2025年12月31日的收入。\n待办：下周补齐资料，负责人待定。"
        actions = meeting_draft(transcript)["actions"]
        self.assertEqual(len(actions), 2)
        for action in actions:
            self.assertEqual(action["owner"], "")
            self.assertEqual(action["due"], "")

    def test_invalid_due_stays_empty(self):
        action = meeting_draft("待办：核对资料；负责人：张晨；截止：2026-02-30。")["actions"][0]
        self.assertEqual(action["owner"], "张晨")
        self.assertEqual(action["due"], "")

    def test_english_explicit_action_fields(self):
        action = meeting_draft("TODO: Check revenue; Owner: Alice Chen; Due: 2026-05-03")["actions"][0]
        self.assertEqual(action["owner"], "Alice Chen")
        self.assertEqual(action["due"], "2026-05-03")

    def test_no_actions_when_not_stated_or_negated(self):
        for transcript in ("今天只交流市场背景，没有形成结论。", "无需跟进。", "暂无待办。", "任务已完成，无需跟进。"):
            with self.subTest(transcript=transcript):
                self.assertEqual(meeting_draft(transcript)["actions"], [])

    def test_candidate_limits_dedup_and_invalid_transcript(self):
        repeated = "待办：核对资料；负责人：张晨。"
        self.assertEqual(len(meeting_draft(repeated + "\n" + repeated)["actions"]), 1)
        draft = meeting_draft("\n".join(f"待办：核对第{index}项资料。" for index in range(40)))
        self.assertEqual(len(draft["actions"]), 30)
        self.assertLessEqual(draft["summary"].count('- "'), 8)
        for transcript in (None, " \n", "x" * 200001):
            with self.subTest(transcript=str(transcript)[:20]), self.assertRaises(ValueError):
                meeting_draft(transcript)


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.a = {"revenue": 100, "growth": 0, "margin": .2,
                  "entry_multiple": 5, "exit_multiple": 5, "leverage": .5,
                  "years": 2, "cash_conversion": 1, "interest_rate": .1}

    def test_hand_calculated_debt_and_terminal_only_returns(self):
        result = calculate_model(self.a)
        base = result["base"]
        self.assertEqual(base["entry_ev"], 100)
        self.assertEqual(base["entry_equity"], 50)
        first, second = base["rows"]
        self.assertEqual((first["revenue"], first["ebitda"], first["interest"]), (100, 20, 5))
        self.assertEqual((first["cash_flow"], first["debt_repayment"], first["debt"]), (15, 15, 35))
        self.assertEqual((second["interest"], second["cash_flow"], second["debt"]), (3.5, 16.5, 18.5))
        self.assertAlmostEqual(base["exit_equity"], 81.5)
        self.assertAlmostEqual(base["moic"], 1.63)
        self.assertAlmostEqual(base["irr"], math.sqrt(1.63) - 1)
        self.assertEqual(set(result), {"base", "bear", "bull", "sensitivity", "assumptions", "formulas", "warning"})

    def test_debt_repayment_then_cash_no_double_count(self):
        base = calculate_model({**self.a, "leverage": .1, "interest_rate": 0})["base"]
        self.assertEqual(base["entry_equity"], 90)
        self.assertEqual(base["rows"][0]["debt"], 0)
        self.assertEqual(base["rows"][0]["cash"], 10)
        self.assertEqual(base["rows"][1]["cash"], 30)
        self.assertEqual(base["net_debt"], -30)
        self.assertEqual(base["exit_equity"], 130)  # Not 170: annual CF is not added twice.
        self.assertAlmostEqual(base["moic"], 130 / 90)

    def test_unlevered_retained_cash_belongs_to_equity(self):
        base = calculate_model({**self.a, "leverage": 0, "years": 3, "interest_rate": .4})["base"]
        self.assertEqual(base["entry_equity"], 100)
        self.assertEqual(base["exit_cash"], 60)
        self.assertEqual(base["exit_equity"], 160)
        self.assertTrue(all(row["debt"] == 0 and row["interest"] == 0 for row in base["rows"]))

    def test_negative_cash_flow_is_financed_and_bankruptcy_is_minus_one(self):
        base = calculate_model({**self.a, "cash_conversion": 0, "interest_rate": .5, "exit_multiple": 0})["base"]
        self.assertEqual(base["rows"][0]["cash_flow"], -25)
        self.assertEqual(base["rows"][0]["debt_draw"], 25)
        self.assertEqual(base["exit_debt"], 112.5)
        self.assertEqual(base["exit_equity"], 0)
        self.assertEqual(base["moic"], 0)
        self.assertEqual(base["irr"], -1)

    def test_zero_exit_ev_can_still_return_retained_cash(self):
        base = calculate_model({**self.a, "leverage": 0, "exit_multiple": 0})["base"]
        self.assertEqual(base["exit_equity"], 40)
        self.assertAlmostEqual(base["irr"], math.sqrt(.4) - 1)

    def test_growth_is_applied_before_year_one_ebitda(self):
        base = calculate_model({**self.a, "growth": .1})["base"]
        self.assertAlmostEqual(base["rows"][0]["revenue"], 110)
        self.assertAlmostEqual(base["rows"][1]["revenue"], 121)

    def test_scenarios_hold_entry_price_fixed(self):
        result = calculate_model({**self.a, "growth": .1})
        for scenario in ("bear", "bull"):
            self.assertEqual(result[scenario]["entry_ev"], result["base"]["entry_ev"])
            self.assertEqual(result[scenario]["entry_equity"], result["base"]["entry_equity"])
            self.assertEqual(result[scenario]["entry_debt"], result["base"]["entry_debt"])
        self.assertLess(result["bear"]["irr"], result["base"]["irr"])
        self.assertLess(result["base"]["irr"], result["bull"]["irr"])
        self.assertIn("相同进入价格", result["formulas"]["scenarios"])

    def test_sensitivity_matrix_shape_center_and_monotonicity(self):
        result = calculate_model({**self.a, "growth": .1, "years": 5})
        matrix = result["sensitivity"]
        self.assertEqual(len(matrix["rows"]), 5)
        self.assertEqual(len(matrix["columns"]), 5)
        self.assertEqual(len(matrix["values"]), len(matrix["rows"]))
        for row in matrix["values"]:
            self.assertEqual(len(row), len(matrix["columns"]))
            self.assertEqual(row, sorted(row))
        r, c = matrix["rows"].index(.1), matrix["columns"].index(5)
        self.assertAlmostEqual(matrix["values"][r][c], result["base"]["irr"])
        for column in zip(*matrix["values"]):
            self.assertEqual(list(column), sorted(column))

    def test_sensitivity_boundaries_have_unique_numeric_axes(self):
        for changes in ({"growth": -.5, "exit_multiple": 0}, {"growth": 1, "exit_multiple": 50}):
            result = calculate_model({**self.a, **changes})
            matrix = result["sensitivity"]
            self.assertEqual(matrix["rows"], sorted(set(matrix["rows"])))
            self.assertEqual(matrix["columns"], sorted(set(matrix["columns"])))
            self.assertTrue(all(-.5 <= value <= 1 for value in matrix["rows"]))
            self.assertTrue(all(0 <= value <= 50 for value in matrix["columns"]))

    def test_defaults_do_not_mutate_input_and_result_is_json_finite(self):
        assumptions = {"years": 1}
        original = dict(assumptions)
        result = calculate_model(assumptions)
        self.assertEqual(assumptions, original)
        self.assertEqual(result["assumptions"]["years"], 1)
        json.dumps(result, allow_nan=False)
        self.assertIn("非完整 LBO", result["warning"])
        self.assertIn("税前", result["warning"])

    def test_reject_nan_infinity_bool_strings_and_absurd_values(self):
        invalid = {
            "revenue": [0, -1, 1e10, True, float("nan"), float("inf"), "100", None, 10 ** 1000],
            "growth": [-.51, 1.01, False, float("-inf")],
            "margin": [0, 1.1, True, float("nan")],
            "entry_multiple": [0, -1, 51, True],
            "exit_multiple": [-.1, 51, False],
            "leverage": [-.01, .8001, True],
            "years": [0, 11, 1.5, 5.0, True, "5", float("nan")],
            "cash_conversion": [-.1, 1.1, False],
            "interest_rate": [-.01, .51, True],
        }
        for key, values in invalid.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    with self.assertRaisesRegex(ValueError, r"[\u3400-\u9fff]"):
                        calculate_model({**self.a, key: value})
        for value in (None, [], {"unexpected": 1}, {"revenue": 1e-300, "entry_multiple": 1e-300}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                calculate_model(value)

    def test_valid_extreme_bounds_remain_finite(self):
        result = calculate_model({"revenue": 1e9, "growth": 1, "margin": 1, "entry_multiple": 50,
                                  "exit_multiple": 50, "leverage": .8, "years": 10,
                                  "cash_conversion": 1, "interest_rate": .5})
        json.dumps(result, allow_nan=False)
        for scenario in ("base", "bear", "bull"):
            self.assertGreaterEqual(result[scenario]["irr"], -1)
            self.assertTrue(all(row["debt"] >= 0 for row in result[scenario]["rows"]))

    def test_seeded_random_cash_conservation_and_return_identity(self):
        rng = random.Random(84721)
        for _ in range(70):
            assumptions = {"revenue": rng.uniform(1, 1000), "growth": rng.uniform(-.5, .8),
                           "margin": rng.uniform(.01, .7), "entry_multiple": rng.uniform(1, 20),
                           "exit_multiple": rng.uniform(0, 20), "leverage": rng.uniform(0, .8),
                           "years": rng.randint(1, 10), "cash_conversion": rng.random(),
                           "interest_rate": rng.uniform(0, .5)}
            result = calculate_model(assumptions)
            for scenario in ("base", "bear", "bull"):
                modeled = result[scenario]
                prior_net_debt = modeled["entry_debt"]
                for row in modeled["rows"]:
                    self.assertGreaterEqual(row["debt"], 0)
                    self.assertGreaterEqual(row["cash"], 0)
                    self.assertAlmostEqual(prior_net_debt - row["cash_flow"], row["net_debt"], places=7)
                    self.assertAlmostEqual(row["opening_debt"] * assumptions["interest_rate"], row["interest"], places=7)
                    prior_net_debt = row["net_debt"]
                self.assertAlmostEqual(modeled["exit_equity"], max(0, modeled["exit_ev"] - modeled["net_debt"]), places=7)
                self.assertAlmostEqual((1 + modeled["irr"]) ** assumptions["years"], modeled["moic"], places=6)
            json.dumps(result, allow_nan=False)


class DemoDataTests(unittest.TestCase):
    def test_collection_sizes_contracts_and_relative_dates(self):
        data = demo_data()
        counts = {"projects": 4, "tasks": 8, "documents": 6, "meetings": 2, "notes": 4, "deliverables": 2, "activity": 0}
        self.assertEqual(set(data), set(counts))
        for collection, expected in counts.items():
            self.assertEqual(len(data[collection]), expected)
            for item in data[collection]:
                for key in ("id", "created_at", "updated_at"):
                    self.assertIn(key, item)
        today = date.today()
        due_dates = [date.fromisoformat(task["due"]) for task in data["tasks"] if task["due"]]
        self.assertTrue(any(due < today for due in due_dates))
        self.assertTrue(any(due == today for due in due_dates))
        self.assertTrue(any(due > today for due in due_dates))
        self.assertTrue(all(today - timedelta(days=7) <= due <= today + timedelta(days=14) for due in due_dates))
        self.assertEqual({task["status"] for task in data["tasks"]}, {"待办", "进行中", "完成"})
        self.assertEqual({note["status"] for note in data["notes"]}, {"待核实", "已核实", "暂不采用"})

    def test_relations_are_complete_and_quotes_are_verbatim(self):
        data = demo_data()
        projects = {project["id"] for project in data["projects"]}
        meetings = {meeting["id"]: meeting for meeting in data["meetings"]}
        documents = {document["id"]: document for document in data["documents"]}
        all_ids = []
        for collection in data.values():
            for item in collection:
                all_ids.append(item["id"])
                if item.get("project_id"):
                    self.assertIn(item["project_id"], projects)
                if item.get("meeting_id"):
                    self.assertIn(item["meeting_id"], meetings)
                    self.assertEqual(item["project_id"], meetings[item["meeting_id"]]["project_id"])
                if item.get("document_id"):
                    self.assertIn(item["document_id"], documents)
                    source = documents[item["document_id"]]
                    self.assertIn(item["source_quote"], source["content"])
                    self.assertEqual(item["project_id"], source["project_id"])
        self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_every_source_line_is_labeled_and_hashes_match(self):
        data = demo_data()
        for document in data["documents"]:
            self.assertTrue(document["source_ref"].startswith("synthetic://"))
            self.assertFalse(document["private"])
            self.assertEqual(document["hash"], hashlib.sha256(document["content"].encode()).hexdigest())
            self.assertTrue(document["chunks"])
            for line in document["content"].splitlines():
                self.assertTrue(line.startswith("[模拟]"), line)
            for chunk in document["chunks"]:
                self.assertIn(chunk["text"], document["content"])
        for collection, fields in (("meetings", ("transcript", "summary")), ("notes", ("body", "source_quote")), ("deliverables", ("body",))):
            for item in data[collection]:
                for field in fields:
                    self.assertTrue(all(line.startswith("[模拟]") for line in item[field].splitlines()))
        self.assertTrue(all("合成" in project["name"] for project in data["projects"]))

    def test_demo_research_meeting_and_tasks_are_connected(self):
        data = demo_data()
        citations = retrieve("北辰机器人收入差异", data["documents"])
        self.assertIn("demo-source-beichen-ledger", {c["document_id"] for c in citations})
        self.assertIn("口径", local_answer("收入差异", citations)["warning"])
        for meeting in data["meetings"]:
            actions = meeting_draft(meeting["transcript"])["actions"]
            self.assertTrue(actions)
            self.assertTrue(any(task["meeting_id"] == meeting["id"] for task in data["tasks"]))
        capacity = retrieve("远山算力容量", data["documents"])
        self.assertTrue(capacity)
        self.assertTrue(any("规划" in c["quote"] and "不能" in c["quote"] for c in capacity))

    def test_calls_return_fresh_json_serializable_data(self):
        first = demo_data()
        first["projects"][0]["name"] = "mutated"
        first["documents"][0]["chunks"].clear()
        second = demo_data()
        self.assertNotEqual(second["projects"][0]["name"], "mutated")
        self.assertTrue(second["documents"][0]["chunks"])
        json.dumps(second, ensure_ascii=False, allow_nan=False)


class IntegrationRegressionTests(unittest.TestCase):
    def test_meeting_title_fits_store_and_keeps_full_source(self):
        source = "待办：" + "核对合同资料" * 50
        draft = meeting_draft(source)
        self.assertEqual(len(draft["actions"][0]["title"]), 200)
        self.assertEqual(draft["actions"][0]["source_quote"], source)
        self.assertIn('- "', draft["summary"])
        for codepoint in (0x300C, 0x300D, 0x300A, 0x300B, 0x3010, 0x3011):
            self.assertNotIn(chr(codepoint), draft["summary"])

    def test_answer_title_uses_plain_text(self):
        docs = [{"id": "d", "title": "北辰机器人", "content": "北辰机器人收入218"}]
        result = local_answer("北辰收入", retrieve("北辰收入", docs))
        self.assertIn("[1] 北辰机器人", result["answer"])
        self.assertNotIn(chr(0x300A), result["answer"])

    def test_company_match_does_not_invent_an_absent_metric(self):
        docs = [{"id": "d", "title": "北辰机器人", "content": "北辰机器人收入218，订单180。"}]
        self.assertEqual(retrieve("北辰机器人现金流", docs), [])
        self.assertEqual(retrieve("北辰机器人的毛利率是多少", docs), [])
        self.assertTrue(retrieve("北辰机器人收入", docs))

    def test_library_value_and_encoding_errors_are_chinese(self):
        with mock.patch.dict(sys.modules, {"pypdf": SimpleNamespace(PdfReader=mock.Mock(side_effect=ValueError("Invalid stream")))}):
            with self.assertRaisesRegex(ValueError, "PDF 文件损坏"):
                parse_upload("x.pdf", b"%PDF")
        with self.assertRaisesRegex(ValueError, "DOCX 文件损坏"):
            parse_upload("x.docx", make_docx(b'<?xml version="1.0" encoding="unknown-encoding"?><x/>'))


if __name__ == "__main__":
    unittest.main()
