"""Standalone XPath extraction CLI. No API, GPU or network required to extract."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from html import escape
from datetime import datetime, timezone
from extractor import extract_bytes, detect_template
from trafilatura_baseline import compare_manifest_pages
from lxml import html

ROOT = Path(__file__).resolve().parent

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + chr(10), encoding='utf8')

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def local_path(value):
    path = Path(value)
    return path if path.is_absolute() else ROOT / path

def load_trafilatura_summary():
    comparison_path = ROOT / 'output' / 'trafilatura_comparison.json'
    if not comparison_path.exists():
        return None
    try:
        return read_json(comparison_path).get('summary')
    except (OSError, ValueError, TypeError):
        return None

def batch(manifest=None, output_dir=None, report_dir=None):
    manifest = Path(manifest) if manifest else ROOT / 'samples/manifest.json'
    output_dir = Path(output_dir) if output_dir else ROOT / 'output'
    report_dir = Path(report_dir) if report_dir else ROOT / 'reports'
    config = read_json(manifest)
    baseline_path = ROOT / 'samples/baseline.json'
    baseline = read_json(baseline_path) if baseline_path.exists() else {'pages': {}}
    pages = []
    for item in config['pages']:
        record = dict(id=item['id'], path=item['path'], url=item.get('url'), expected_template=item['template'], source_sha256=item['sha256'])
        try:
            source = local_path(item['path'])
            if digest(source) != item['sha256']:
                raise ValueError('Source bytes differ from manifest; inspect before updating provenance')
            raw = source.read_bytes()
            selected = detect_template(html.document_fromstring(raw))
            if selected != item['template']:
                raise ValueError('Detected layout differs from manifest')
            started = time.perf_counter()
            result = extract_bytes(raw)
            seconds = time.perf_counter() - started
            expected = baseline.get('pages', {}).get(item['id'])
            same = (result == expected['result'] and item['sha256'] == expected['source_sha256']) if expected else None
            record.update(status='success', template=selected, result=result, seconds=seconds,
                          baseline_match=same, checks='contract, source XPath, DOM order and table rows')
            write_json(output_dir / (item['id'] + '.json'), result)
            state = 'BASELINE MATCH' if same else 'BASELINE CHANGED' if same is False else 'NO BASELINE'
            print(f"OK {item['id']}: blocks={len(result['blocks'])}, metadata={len(result['metadata'])}, excluded={len(result['excluded'])}; {state}")
        except Exception as exc:
            record.update(status='error', error=type(exc).__name__ + ': ' + str(exc), baseline_match=False)
            print(f"FAIL {item['id']}: {record['error']}")
        pages.append(record)
    passed = sum(p['status'] == 'success' for p in pages)
    report = dict(version=1, generated_at_utc=datetime.now(timezone.utc).isoformat(), scope=config['scope'],
                  samples=len(pages), extraction_passed=passed, baseline_available=baseline_path.exists(),
                  baseline_matches=sum(p.get('baseline_match') is True for p in pages),
                  semantic_accuracy=None, unseen_evaluation=False, live_ai_calls=0,
                  measurement='single local CPU invocation per page; not a benchmark', pages=pages)
    write_json(output_dir / 'results.json', report)
    build_report(report, report_dir)
    print(f"REPORT: {report_dir / 'index.html'}")
    return report

def build_report(report, destination):
    import os
    destination.mkdir(parents=True, exist_ok=True)
    rows, sections = [], []
    body_labels = {
        'paragraph': '段落',
        'subheading': '小标题',
        'heading': '标题',
        'caption': '图说',
        'table': '表格',
        'code_block': '代码块',
        'list_item': '列表项',
        'definition_term': '定义项',
        'definition_description': '定义说明',
        'footnote': '脚注',
    }
    metadata_labels = {
        'author': '作者',
        'editor': '责任编辑',
        'source': '来源',
        'published_at': '发布时间',
        'production_credit': '制作署名',
    }
    for item in report['pages']:
        ident = escape(item['id'], quote=True)
        result = item.get('result', {})
        counts = [len(result.get(k, [])) for k in ('blocks','metadata','excluded')]
        rows.append('<tr><td><a href="#'+ident+'">'+ident+'</a></td><td>'+escape(item.get('template',item['expected_template']))+'</td><td>'+escape(item['status'])+'</td>'+''.join('<td>'+str(n)+'</td>' for n in counts)+'<td>'+('一致' if item.get('baseline_match') is True else '变化' if item.get('baseline_match') is False else '无基准')+'</td></tr>')
        source = local_path(item['path'])
        local = Path(os.path.relpath(source, destination)).as_posix()
        original = (' · <a target="_blank" rel="noopener" href="'+escape(item['url'], quote=True)+'">原站地址</a>') if item.get('url') else ''
        section = '<section id="'+ident+'"><h2>'+escape(result.get('title',item['id']))+'</h2><p><a target="_blank" rel="noopener" href="'+escape(local,quote=True)+'">原始HTML快照</a>'+original+'</p>'
        if item['status'] != 'success':
            section += '<pre>'+escape(item['error'])+'</pre>'
        else:
            section += '<p>规则：'+escape(item['template'])+'；正文块 '+str(counts[0])+'；本次提取 '+format(item['seconds']*1000,'.2f')+' ms（不含安装和报告，非性能基准）。</p>'
            section += '<h3>页面信息（与正文分离）</h3>'
            if result['metadata']:
                section += '<table><tr><th>类别</th><th>文本</th><th>XPath</th></tr>'
                for metadata in result['metadata']:
                    section += ('<tr><td>'+escape(metadata_labels.get(metadata['kind'],metadata['kind']))
                                +'</td><td>'+escape(metadata['text'])+'</td><td><code>'
                                +escape(metadata['xpath'])+'</code></td></tr>')
                section += '</table>'
            else:
                section += '<p>本页没有规则明确识别的作者、编辑、来源、发布时间或制作署名。</p>'
            section += '<details><summary>原始页面信息、排除项与局限（JSON）</summary><pre>'+escape(json.dumps({k:result[k] for k in ('metadata','excluded','warnings')},ensure_ascii=False,indent=2))+'</pre></details>'
            section += '<h3>正文</h3><ol>'
            for block in result['blocks']:
                section += '<li><span class="kind">'+escape(body_labels.get(block['kind'],block['kind']))+'</span><p>'+escape(block['text'])+'</p>'
                if block['kind']=='table':
                    section += '<table>'+''.join('<tr>'+''.join('<td>'+escape(cell)+'</td>' for cell in row)+'</tr>' for row in block['rows'])+'</table>'
                section += '<details><summary>XPath原文定位</summary><code>'+escape(block['xpath'])+'</code></details></li>'
            section += '</ol>'
        sections.append(section+'<p><a href="#top">返回汇总</a></p></section>')
    page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>项目一 · XPath规则抽取报告</title><style>body{font:16px/1.7 system-ui,sans-serif;max-width:1120px;margin:28px auto;padding:0 20px;color:#18314a}table{border-collapse:collapse;width:100%;margin:12px 0}td,th{border:1px solid #ccd6e0;padding:8px;text-align:left;vertical-align:top}section{margin-top:32px;border-top:2px solid #ccd6e0;padding-top:16px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f4f8;padding:16px}code{overflow-wrap:anywhere}.kind{background:#eaf1fa;padding:3px 8px}li{margin-bottom:16px}.note{background:#fff4d8;padding:16px}a{color:#185ca2}.metrics{display:grid;grid-template-columns:repeat(5,minmax(120px,1fr));gap:10px;margin:16px 0}.metric{background:#f1f4f8;border-left:4px solid #185ca2;padding:10px}.metric strong{display:block;font-size:1.35rem}@media(max-width:760px){.metrics{grid-template-columns:1fr 1fr}}</style>'
    baseline_report = destination / 'trafilatura_comparison.html'
    if baseline_report.exists():
        summary = load_trafilatura_summary() or {}
        baseline_link = '<p><a href="'+baseline_report.name+'">打开完整“结果与Trafilatura外部基线对照”报告</a>。该报告是独立参照，不是人工标注。</p>'
        baseline_metrics = (
            '<h2>结果与Trafilatura外部基线对照</h2>'
            '<div class="metrics">'
            '<div class="metric"><span>对照页数</span><strong>'+str(summary.get('compared','-'))+'</strong></div>'
            '<div class="metric"><span>标题一致</span><strong>'+str(summary.get('title_matches','-'))+'</strong></div>'
            '<div class="metric"><span>运行错误</span><strong>'+str(summary.get('errors','-'))+'</strong></div>'
            '<div class="metric"><span>平均字符5-gram F1</span><strong>'
            + (format(summary['average_char_ngram_f1'],'.4f') if summary.get('average_char_ngram_f1') is not None else '-')
            + '</strong></div>'
            '<div class="metric"><span>平均块级匹配F1</span><strong>'
            + (format(summary['average_block_f1'],'.4f') if summary.get('average_block_f1') is not None else '-')
            + '</strong></div>'
            '<div class="metric"><span>近似匹配块（两侧合计）</span><strong>'+str(summary.get('approximate_block_matches','-'))+'</strong></div>'
            '<div class="metric"><span>需人工核查</span><strong>'+str(summary.get('review_count','-'))+'</strong></div>'
            '</div>' + baseline_link
        )
    else:
        baseline_metrics = ('<h2>结果与Trafilatura外部基线对照</h2>'
                            '<p class="note">对照报告尚未生成；运行 <code>app.py baseline</code> 后会在此处显示汇总指标和入口。</p>')
    page += '<h1 id="top">项目一：基于XPath的规则化网页内容提取</h1><p>样本 '+str(report['samples'])+'；提取及证据检查通过 '+str(report['extraction_passed'])+'；与固定历史回归基准一致 '+str(report['baseline_matches'])+'。</p>'+baseline_metrics+'<table><tr><th>样本</th><th>模板</th><th>状态</th><th>正文块</th><th>页面信息</th><th>排除项</th><th>历史基准</th></tr>'+''.join(rows)+'</table>'+''.join(sections)+'</html>'
    (destination/'index.html').write_text(page,encoding='utf8')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    b=sub.add_parser('batch',help='run the bundled nine-page offline regression')
    b.add_argument('--manifest');b.add_argument('--output-dir');b.add_argument('--report-dir')
    e=sub.add_parser('extract',help='extract one saved HTML page')
    e.add_argument('--input',required=True);e.add_argument('--output',required=True)
    e.add_argument('--template',choices=['auto','sina','chinanews','pg_essay','pydoc'],default='auto')
    t=sub.add_parser('baseline',help='compare rule extraction with the local Trafilatura baseline')
    t.add_argument('--manifest',action='append',help='manifest to compare; repeat for multiple manifests')
    t.add_argument('--output',default=str(ROOT / 'output/trafilatura_comparison.json'))
    t.add_argument('--report',default=str(ROOT / 'reports/trafilatura_comparison.html'))
    t.add_argument('--reference-dir',default=str(ROOT / 'output/trafilatura_reference'))
    args=p.parse_args()
    try:
        if args.command=='batch':
            report=batch(local_path(args.manifest) if args.manifest else None,local_path(args.output_dir) if args.output_dir else None,local_path(args.report_dir) if args.report_dir else None)
            return 0 if report['extraction_passed']==report['samples'] and all(p.get('baseline_match') is not False for p in report['pages']) else 1
        if args.command=='baseline':
            manifests=args.manifest or [str(ROOT / 'samples/manifest.json')]
            pydoc_manifest=ROOT / 'samples/pydoc_manifest.json'
            if args.manifest is None and pydoc_manifest.exists():
                manifests.append(str(pydoc_manifest))
            report=compare_manifest_pages(
                manifests,
                local_path(args.output),
                local_path(args.report),
                local_path(args.reference_dir),
            )
            print(f"BASELINE: compared={report['summary']['compared']}, errors={report['summary']['errors']}, "
                  f"average_f1={report['summary']['average_char_ngram_f1']}")
            print(f"REPORT: {local_path(args.report)}")
            return 0 if report['summary']['errors']==0 else 1
        source=local_path(args.input);target=local_path(args.output)
        if source.resolve()==target.resolve():raise ValueError('Output must not overwrite source HTML')
        result=extract_bytes(source.read_bytes(),args.template)
        write_json(target,result);print('TITLE:',result['title']);print('BLOCKS:',len(result['blocks']));print('SAVED:',target)
        return 0
    except Exception as exc:
        print('ERROR:',str(exc),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
