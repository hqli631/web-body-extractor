"""Compare the rule extractor with Trafilatura as an external reference baseline."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from html import escape
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from lxml import html
import trafilatura

from extractor import detect_template, extract_bytes


ROOT = Path(__file__).resolve().parent
TRAFILATURA_REPOSITORY = "https://github.com/adbar/trafilatura"
TRAFILATURA_SETTINGS = {
    "fast": False,
    "no_fallback": False,
    "favor_precision": False,
    "favor_recall": False,
    "include_comments": False,
    "include_tables": True,
    "include_images": False,
    "include_links": False,
    "include_formatting": False,
}

# A block is treated as an approximate match when its whitespace-compacted text
# is at least 95 percent covered by the opposite blocks, or a length-comparable
# local block reaches 95 percent character similarity. The threshold is kept
# explicit so formatting noise does not silently become an extraction error.
BLOCK_MATCH_THRESHOLD = 0.95


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + chr(10), encoding="utf8")


def local_path(value):
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def display_path(path):
    path = Path(path)
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalize_text(value):
    """Normalize whitespace and presentation-only Sphinx headerlink markers."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).replace("\u00a0", " ")
    text = re.sub(r"\s*¶\s*$", "", text)
    return " ".join(text.split())


def compact_text(value):
    return re.sub(r"\s+", "", normalize_text(value))


def ngram_scores(reference_text, candidate_text, size=5):
    reference = compact_text(reference_text)
    candidate = compact_text(candidate_text)
    if not reference and not candidate:
        return dict(precision=1.0, recall=1.0, f1=1.0)
    if not reference or not candidate:
        return dict(precision=0.0, recall=0.0, f1=0.0)
    reference_grams = Counter(reference[i:i + size] for i in range(max(1, len(reference) - size + 1)))
    candidate_grams = Counter(candidate[i:i + size] for i in range(max(1, len(candidate) - size + 1)))
    overlap = sum((reference_grams & candidate_grams).values())
    precision = overlap / sum(candidate_grams.values())
    recall = overlap / sum(reference_grams.values())
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return dict(precision=round(precision, 4), recall=round(recall, 4), f1=round(f1, 4))


def normalized_titles_equal(left, right):
    left_value = normalize_text(left).rstrip("¶").strip()
    right_value = normalize_text(right).rstrip("¶").strip()
    if not left_value or not right_value:
        return False
    return left_value == right_value or left_value in right_value or right_value in left_value


def reference_segments(payload, own_title):
    """Convert Trafilatura's rendered text into normalized comparison segments."""
    title_candidates = {
        normalize_text(payload.get("title", "")).rstrip("¶").strip(),
        normalize_text(own_title).rstrip("¶").strip(),
    }
    title_candidates.discard("")
    segments = []
    for raw_line in (payload.get("text") or "").splitlines():
        value = normalize_text(raw_line)
        if not value:
            continue
        if not segments and value.rstrip("¶").strip() in title_candidates:
            continue
        value = re.sub(r"^(?:[-+*]|\d+[.)])\s+", "", value).strip()
        if value:
            segments.append(value)
    return segments


def own_segments(result):
    return [normalize_text(block["text"]) for block in result["blocks"] if normalize_text(block["text"])]


def own_alignment_segments(result):
    """Return body text plus classified page information for block alignment."""
    segments = own_segments(result)
    segments.extend(
        normalize_text(item["text"])
        for item in result.get("metadata", [])
        if normalize_text(item.get("text"))
    )
    return segments


def block_similarity(left, right):
    """Whitespace-insensitive character similarity of two already-normalized blocks."""
    left_value = compact_text(left)
    right_value = compact_text(right)
    if not left_value and not right_value:
        return 1.0
    if not left_value or not right_value:
        return 0.0
    matching = sum(
        block.size for block in SequenceMatcher(None, left_value, right_value, autojunk=False).get_matching_blocks()
    )
    return matching / max(len(left_value), len(right_value))


def block_covered_score(block_value, opposite_values, threshold=BLOCK_MATCH_THRESHOLD):
    """Coverage of one compacted block by any opposite blocks, or ``None``."""
    if not block_value:
        return None
    opposite_values = [value for value in opposite_values if value]
    if not opposite_values:
        return None
    block_length = len(block_value)
    intervals = []
    best_ratio = 0.0
    for opposite_value in opposite_values:
        if block_value in opposite_value:
            return 1.0
        start = 0
        while True:
            position = block_value.find(opposite_value, start)
            if position < 0:
                break
            intervals.append((position, position + len(opposite_value)))
            start = position + len(opposite_value)
        length_ratio = min(block_length, len(opposite_value)) / max(block_length, len(opposite_value))
        if length_ratio >= 0.6:
            ratio = SequenceMatcher(None, block_value, opposite_value, autojunk=False).ratio()
            best_ratio = max(best_ratio, ratio)
            if best_ratio >= threshold:
                return best_ratio

    def covered_length(items):
        if not items:
            return 0
        items = sorted(items)
        covered = 0
        start, end = items[0]
        for next_start, next_end in items[1:]:
            if next_start > end:
                covered += end - start
                start, end = next_start, next_end
            else:
                end = max(end, next_end)
        return covered + end - start

    coverage = covered_length(intervals) / block_length
    if coverage >= threshold:
        return coverage

    # A long merged reference can contain a paragraph with one small edit but
    # not as an exact substring. Align only against a few long candidates so
    # the normal case stays linear and the full corpus is never rescanned.
    for opposite_value in sorted(opposite_values, key=len, reverse=True)[:3]:
        if block_value in opposite_value or opposite_value in block_value:
            continue
        matcher = SequenceMatcher(None, block_value, opposite_value, autojunk=False)
        intervals.extend(
            (position, position + size)
            for _a, position, size in matcher.get_matching_blocks()
            if size
        )
        coverage = covered_length(intervals) / block_length
        if coverage >= threshold:
            return coverage

    score = max(coverage, best_ratio)
    return score if score >= threshold else None


def pair_identical_blocks(reference_values, candidate_values, matched_reference, matched_candidate):
    pairs = []
    exact_pairs = []
    for reference_index, reference_value in enumerate(reference_values):
        if reference_index in matched_reference or not reference_value:
            continue
        for candidate_index, candidate_value in enumerate(candidate_values):
            if candidate_index in matched_candidate or candidate_value != reference_value:
                continue
            pairs.append((abs(reference_index - candidate_index), reference_index, candidate_index))
    pairs.sort()
    for _distance, reference_index, candidate_index in pairs:
        if reference_index in matched_reference or candidate_index in matched_candidate:
            continue
        matched_reference.add(reference_index)
        matched_candidate.add(candidate_index)
        exact_pairs.append((reference_index, candidate_index))
    return exact_pairs


def segment_alignment(reference, candidate, limit=5, threshold=BLOCK_MATCH_THRESHOLD):
    """Compare rendered baseline segments with our blocks.

    Exact equality and approximate similarity both count as a content match.
    Differences are the blocks that stay unpaired on either side, so Markdown
    noise such as a leading ``|`` no longer inflates the error list. One
    baseline segment may cover several of our blocks, or the reverse, when the
    two extractors segment their output differently. Coverage is evaluated
    against the opposite full text so a long merged segment cannot be mistaken
    for a normal one-to-one block pair.
    """
    reference_values = [compact_text(value) for value in reference]
    candidate_values = [compact_text(value) for value in candidate]
    matched_reference, matched_candidate = set(), set()
    exact_pairs = pair_identical_blocks(reference_values, candidate_values, matched_reference, matched_candidate)
    exact_matches = len(exact_pairs)

    approximate_reference = []
    for index, value in enumerate(reference_values):
        if index in matched_reference:
            continue
        if block_covered_score(value, candidate_values, threshold) is not None:
            approximate_reference.append(index)
    approximate_candidate = []
    for index, value in enumerate(candidate_values):
        if index in matched_candidate:
            continue
        if block_covered_score(value, reference_values, threshold) is not None:
            approximate_candidate.append(index)
    matched_reference.update(approximate_reference)
    matched_candidate.update(approximate_candidate)
    approximate_matches = len(approximate_reference) + len(approximate_candidate)

    unmatched_reference = [index for index in range(len(reference)) if index not in matched_reference]
    unmatched_candidate = [index for index in range(len(candidate)) if index not in matched_candidate]
    reference_only = []
    for index in unmatched_reference:
        if len(reference_only) >= limit:
            break
        reference_only.append(reference[index][:300])
    candidate_only = []
    for index in unmatched_candidate:
        if len(candidate_only) >= limit:
            break
        candidate_only.append(candidate[index][:300])

    reference_segments = len(reference)
    candidate_segments = len(candidate)
    precision = 1.0 if candidate_segments == 0 else len(matched_candidate) / candidate_segments
    recall = 1.0 if reference_segments == 0 else len(matched_reference) / reference_segments
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return dict(
        block_match_threshold=threshold,
        exact_block_matches=exact_matches,
        approximate_block_matches=approximate_matches,
        approximate_reference_blocks=len(approximate_reference),
        approximate_candidate_blocks=len(approximate_candidate),
        block_precision=round(precision, 4),
        block_recall=round(recall, 4),
        block_f1=round(f1, 4),
        unmatched_reference=len(unmatched_reference),
        unmatched_candidate=len(unmatched_candidate),
        exact_segment_matches=exact_matches,
        sequence_ratio=round(SequenceMatcher(None, reference, candidate, autojunk=False).ratio(), 4),
        reference_only=reference_only,
        candidate_only=candidate_only,
    )


def compare_texts(own_title, reference_title, reference_text, candidate_text):
    reference_value = compact_text(reference_text)
    candidate_value = compact_text(candidate_text)
    scores = ngram_scores(reference_text, candidate_text)
    title_match = normalized_titles_equal(own_title, reference_title)
    return dict(
        title_match=title_match,
        reference_chars=len(reference_value),
        candidate_chars=len(candidate_value),
        char_ngram_precision=scores["precision"],
        char_ngram_recall=scores["recall"],
        char_ngram_f1=scores["f1"],
    )


def needs_manual_review(comparison, threshold=0.9):
    """Flag large disagreements without deciding which extractor is correct.

    The trigger stays on whole-page character coverage. Block alignment is
    segmentation-sensitive by nature, so it is reported as a separate piece of
    evidence instead of being folded into the same gate.
    """
    return (
        comparison["char_ngram_precision"] < threshold
        or comparison["char_ngram_recall"] < threshold
        or comparison["char_ngram_f1"] < threshold
    )


def call_trafilatura(raw, url):
    options = dict(TRAFILATURA_SETTINGS)
    options["output_format"] = "json"
    options["with_metadata"] = True
    rendered = trafilatura.extract(raw, url=url, **options)
    if not rendered:
        raise ValueError("trafilatura returned no result")
    payload = json.loads(rendered)
    if not payload.get("text"):
        raise ValueError("trafilatura result has no text")
    return payload


def compare_manifest_pages(manifest_paths, output_path, report_path, reference_dir):
    output_path = Path(output_path)
    report_path = Path(report_path)
    reference_dir = Path(reference_dir)
    pages = []
    manifests = []
    for manifest_value in manifest_paths:
        manifest_path = local_path(manifest_value)
        config = read_json(manifest_path)
        manifests.append(dict(path=display_path(manifest_path), scope=config.get("scope", "")))
        for item in config["pages"]:
            source = local_path(item["path"])
            record = dict(
                id=item["id"],
                group=config.get("group") or manifest_path.stem,
                path=item["path"],
                url=item.get("url"),
                role=item.get("role"),
                template=item["template"],
                source_sha256=item["sha256"],
            )
            try:
                if digest(source) != item["sha256"]:
                    raise ValueError("Source bytes differ from manifest")
                raw = source.read_bytes()
                selected = detect_template(html.document_fromstring(raw))
                if selected != item["template"]:
                    raise ValueError("Detected layout differs from manifest")
                own = extract_bytes(raw, selected)
                reference = call_trafilatura(raw, item.get("url"))
                reference_title = normalize_text(reference.get("title", ""))
                segments = reference_segments(reference, own["title"])
                reference_text = "\n".join(segments)
                candidate_text = "\n".join(own_segments(own))
                candidate_segments = own_alignment_segments(own)
                comparison = compare_texts(own["title"], reference_title, reference_text, candidate_text)
                comparison.update(segment_alignment(segments, candidate_segments))
                comparison["needs_manual_review"] = needs_manual_review(comparison)
                metadata_counts = Counter(item["kind"] for item in own["metadata"])
                comparison.update(
                    own_blocks=len(own["blocks"]),
                    own_metadata=len(own["metadata"]),
                    own_metadata_kinds=dict(sorted(metadata_counts.items())),
                    reference_segments=len(segments),
                )
                record.update(status="success", own_title=own["title"], reference_title=reference_title, comparison=comparison)
                write_json(
                    reference_dir / (item["id"] + ".json"),
                    dict(
                        id=item["id"],
                        source_sha256=item["sha256"],
                        url=item.get("url"),
                        trafilatura_repository=TRAFILATURA_REPOSITORY,
                        trafilatura_version=getattr(trafilatura, "__version__", None),
                        settings=TRAFILATURA_SETTINGS,
                        payload=reference,
                        normalized_segments=segments,
                    ),
                )
            except Exception as exc:
                record.update(status="error", error=type(exc).__name__ + ": " + str(exc))
            pages.append(record)

    successful = [page for page in pages if page["status"] == "success"]
    summary = dict(
        pages=len(pages),
        compared=len(successful),
        errors=len(pages) - len(successful),
        title_matches=sum(page["comparison"]["title_match"] for page in successful),
        review_count=sum(page["comparison"]["needs_manual_review"] for page in successful),
        average_char_ngram_f1=round(
            sum(page["comparison"]["char_ngram_f1"] for page in successful) / len(successful), 4
        ) if successful else None,
        average_sequence_ratio=round(
            sum(page["comparison"]["sequence_ratio"] for page in successful) / len(successful), 4
        ) if successful else None,
        average_block_precision=round(
            sum(page["comparison"]["block_precision"] for page in successful) / len(successful), 4
        ) if successful else None,
        average_block_recall=round(
            sum(page["comparison"]["block_recall"] for page in successful) / len(successful), 4
        ) if successful else None,
        average_block_f1=round(
            sum(page["comparison"]["block_f1"] for page in successful) / len(successful), 4
        ) if successful else None,
        approximate_block_matches=sum(page["comparison"]["approximate_block_matches"] for page in successful),
        unmatched_reference_blocks=sum(page["comparison"]["unmatched_reference"] for page in successful),
        unmatched_candidate_blocks=sum(page["comparison"]["unmatched_candidate"] for page in successful),
    )
    report = dict(
        version=1,
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        trafilatura_repository=TRAFILATURA_REPOSITORY,
        trafilatura_version=getattr(trafilatura, "__version__", None),
        settings=TRAFILATURA_SETTINGS,
        comparison_method=(
            "normalized body text for whole-page 5-character n-gram precision, recall and F1; "
            "body segments plus classified page information for block alignment; "
            "block alignment counts exact matches and approximate matches whose compacted text is "
            "covered by the opposite full text or locally similar at character similarity >= "
            + format(BLOCK_MATCH_THRESHOLD, ".2f")
            + "; no manual adjudication"
        ),
        block_alignment_method=(
            "Each body or classified page-information segment is evaluated independently against "
            "the opposite full set of baseline segments so merged or split segmentation does not "
            "have to form a one-to-one pair."
        ),
        block_match_threshold=BLOCK_MATCH_THRESHOLD,
        caveat="Trafilatura is an external baseline, not absolute ground truth. It can include page furniture or omit content.",
        manifests=manifests,
        summary=summary,
        pages=pages,
    )
    write_json(output_path, report)
    build_html(report, report_path)
    build_markdown(report, report_path.with_suffix(".md"))
    return report


def build_html(report, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    details = []
    for page in report["pages"]:
        ident = escape(page["id"], quote=True)
        if page["status"] == "error":
            rows.append(
                "<tr><td><a href=\"#" + ident + "\">" + ident + "</a></td><td>"
                + escape(page.get("group", "")) + "</td><td>error</td><td colspan=\"10\">"
                + escape(page.get("error", "")) + "</td></tr>"
            )
            details.append("<section id=\"" + ident + "\"><h2>" + ident + "</h2><pre>"
                           + escape(page.get("error", "")) + "</pre></section>")
            continue
        comparison = page["comparison"]
        rows.append(
            "<tr><td><a href=\"#" + ident + "\">" + ident + "</a></td><td>"
            + escape(page.get("group", "")) + "</td><td>" + str(comparison["own_blocks"])
            + "</td><td>" + str(comparison["own_metadata"])
            + "</td><td>" + str(comparison["reference_segments"])
            + "</td><td>" + ("是" if comparison["title_match"] else "否")
            + "</td><td>" + ("是" if comparison["needs_manual_review"] else "否")
            + "</td><td>" + str(comparison["exact_block_matches"])
            + "</td><td>" + str(comparison["approximate_block_matches"])
            + "</td><td>" + format(comparison["block_f1"], ".3f")
            + "</td><td>" + format(comparison["char_ngram_precision"], ".3f")
            + "</td><td>" + format(comparison["char_ngram_recall"], ".3f")
            + "</td><td>" + format(comparison["char_ngram_f1"], ".3f") + "</td></tr>"
        )
        reference_only = "".join("<li>" + escape(value) + "</li>" for value in comparison["reference_only"])
        candidate_only = "".join("<li>" + escape(value) + "</li>" for value in comparison["candidate_only"])
        metadata_kinds = "、".join(
            key + ":" + str(value) for key, value in comparison["own_metadata_kinds"].items()
        ) or "无"
        details.append(
            "<section id=\"" + ident + "\"><h2>" + escape(page.get("own_title") or page["id"]) + "</h2>"
            "<p>我们标题：" + escape(page.get("own_title", "")) + "；Trafilatura 标题："
            + escape(page.get("reference_title", "")) + "。</p>"
            "<p>已分离页面信息：" + str(comparison["own_metadata"]) + " 条（"
            + escape(metadata_kinds) + "）；页面信息参与块级对齐，正文字符F1仍只统计正文块。</p>"
            "<p>字符数：" + str(comparison["candidate_chars"]) + " / 基线 "
            + str(comparison["reference_chars"]) + "；精确率/召回率/F1："
            + format(comparison["char_ngram_precision"], ".3f") + " / "
            + format(comparison["char_ngram_recall"], ".3f") + " / "
            + format(comparison["char_ngram_f1"], ".3f") + "；顺序比 "
            + format(comparison["sequence_ratio"], ".3f") + "；需人工核查 "
            + ("是" if comparison["needs_manual_review"] else "否") + "。</p>"
            "<p>块级对齐：完全一致 " + str(comparison["exact_block_matches"]) + "，近似匹配 "
            + str(comparison["approximate_block_matches"]) + " 个文本块（阈值 "
            + format(comparison["block_match_threshold"], ".2f") + "），未匹配 "
            + str(comparison["unmatched_reference"]) + " / " + str(comparison["unmatched_candidate"])
            + "；块级匹配精确率/召回率/F1：" + format(comparison["block_precision"], ".3f") + " / "
            + format(comparison["block_recall"], ".3f") + " / "
            + format(comparison["block_f1"], ".3f") + "。</p>"
            "<div class=\"diff\"><div><h3>未匹配的 Trafilatura 基线块</h3><ul>"
            + (reference_only or "<li>无</li>") + "</ul></div><div><h3>未匹配的规则提取块</h3><ul>"
            + (candidate_only or "<li>无</li>") + "</ul></div></div></section>"
        )
    page = (
        "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>项目一 · Trafilatura 外部基线对照</title>"
        "<style>body{font:16px/1.7 system-ui,sans-serif;max-width:1180px;margin:28px auto;padding:0 20px;"
        "color:#18314a}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd6e0;"
        "padding:8px;text-align:left;vertical-align:top}section{margin-top:34px;border-top:2px solid #ccd6e0;"
        "padding-top:16px}pre{white-space:pre-wrap;background:#f1f4f8;padding:16px}.diff{display:grid;"
        "grid-template-columns:1fr 1fr;gap:18px}.diff>div{background:#f7f9fb;"
        "padding:12px}li{margin-bottom:8px}code{overflow-wrap:anywhere}.score{display:inline-block;"
        "background:#e5f0e5;color:#20502b;border-radius:4px;padding:0 6px;margin-right:6px;"
        "font-variant-numeric:tabular-nums}@media(max-width:760px){.diff{grid-template-columns:1fr}}</style>"
        "<h1>项目一：Trafilatura 外部基线对照</h1>"
        "<p>对照 " + str(report["summary"]["compared"]) + " 页；平均字符 5-gram F1 "
        + (format(report["summary"]["average_char_ngram_f1"], ".3f")
           if report["summary"]["average_char_ngram_f1"] is not None else "无")
        + "；平均块级 F1 " + (format(report["summary"]["average_block_f1"], ".3f")
           if report["summary"]["average_block_f1"] is not None else "无")
        + "；标题一致 " + str(report["summary"]["title_matches"]) + " 页；需人工核查 "
        + str(report["summary"]["review_count"]) + " 页。</p>"
        "<p>Trafilatura 版本：" + escape(str(report["trafilatura_version"])) + "；上游："
        "<a href=\"" + escape(report["trafilatura_repository"], quote=True) + "\">"
        + escape(report["trafilatura_repository"]) + "</a>。</p>"
        "<table><tr><th>页面</th><th>分组</th><th>我们正文块</th><th>页面信息</th><th>基线行数</th>"
        "<th>标题一致</th><th>需核查</th><th>块完全一致</th><th>块近似匹配</th><th>块级匹配F1</th>"
        "<th>全文精确率</th><th>全文召回率</th><th>全文F1</th></tr>"
        + "".join(rows) + "</table>"
        + "".join(details) + "</html>"
    )
    destination.write_text(page, encoding="utf8")


def build_markdown(report, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Trafilatura 外部基线对照",
        "",
        "生成时间（UTC）：" + report["generated_at_utc"],
        "",
        "Trafilatura 版本：" + str(report["trafilatura_version"]),
        "",
        "上游仓库：" + report["trafilatura_repository"],
        "",
        "| 页面 | 分组 | 我们正文块 | 页面信息 | 基线行数 | 标题一致 | 需核查 | 块完全一致 | 块近似匹配 | 块级匹配F1 | 全文精确率 | 全文召回率 | 全文F1 |",
        "| --- | --- | ---: | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for page in report["pages"]:
        if page["status"] != "success":
            lines.append("| " + page["id"] + " | " + str(page.get("group", "")) + " | - | - | - | - | - | - | - | - | - | - | `"
                         + page.get("error", "").replace("|", "\\|") + "` |")
            continue
        comparison = page["comparison"]
        lines.append(
            "| " + page["id"] + " | " + str(page.get("group", "")) + " | "
            + str(comparison["own_blocks"]) + " | " + str(comparison["own_metadata"]) + " | "
            + str(comparison["reference_segments"]) + " | "
            + ("是" if comparison["title_match"] else "否") + " | "
            + ("是" if comparison["needs_manual_review"] else "否") + " | "
            + str(comparison["exact_block_matches"]) + " | "
            + str(comparison["approximate_block_matches"]) + " | "
            + format(comparison["block_f1"], ".3f") + " | "
            + format(comparison["char_ngram_precision"], ".3f") + " | "
            + format(comparison["char_ngram_recall"], ".3f") + " | "
            + format(comparison["char_ngram_f1"], ".3f") + " |"
        )
    lines += [
        "",
        "汇总：平均字符5-gram F1 " + (format(report["summary"]["average_char_ngram_f1"], ".4f")
           if report["summary"]["average_char_ngram_f1"] is not None else "无")
        + "；平均块级 F1 " + (format(report["summary"]["average_block_f1"], ".4f")
           if report["summary"]["average_block_f1"] is not None else "无")
        + "；近似匹配 " + str(report["summary"]["approximate_block_matches"]) + " 块；未匹配 "
        + str(report["summary"]["unmatched_reference_blocks"]) + " / "
        + str(report["summary"]["unmatched_candidate_blocks"]) + " 块。",
        "",
        "## 口径",
        "",
        "- Trafilatura 使用默认回退路径，关闭评论，保留表格。",
        "- 两边都做 Unicode 兼容规范化和空白规范化，去掉 Sphinx 标题末尾的 `¶`。",
        "- 标题不参加正文比较；Trafilatura 的列表符号在比较前去掉。",
        "- 作者、编辑、来源、发布时间等页面信息单独分类保存，并参与块级对齐；全文字符 F1 仍只比较正文块。",
        "- 整页指标是正文压缩后的字符 5-gram 精确率、召回率和 F1；顺序比仅作辅助。",
        "- 块级对齐分别把每个文本块与对面完整文本比较，因此允许一段对多段的合并/拆分，不要求形成一对一配对。",
        "- 块级匹配率是达到匹配阈值的文本块占比；近似匹配阈值为 "
        + format(report["block_match_threshold"], ".2f")
        + "（忽略空白后的字符覆盖率达到阈值，或长度相近时局部字符相似度达到阈值），"
        "达到阈值的块不计入未匹配差异，也不在报告中展开原文。",
        "- 近似匹配只识别格式噪声和小范围用词差异，不证明哪一侧正确；真实内容不同的块仍会进入未匹配列表。",
        "- Trafilatura 是外部参照，不是人工标注。差异必须结合原始 HTML 和规则意图判断。",
    ]
    destination.write_text("\n".join(lines) + chr(10), encoding="utf8")
