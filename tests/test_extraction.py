"""Synthetic regression controls, not natural-page accuracy measurements."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from extractor import extract_bytes


def encoded(markup):
    return ('<meta charset="utf-8">' + markup).encode('utf-8')


class ExtractionControls(unittest.TestCase):
    def test_sina_noise_metadata_and_normal_link_are_separated(self):
        raw = encoded('''<nav>站点导航</nav><h1 class="extra main-title active">文章标题</h1>
        <div id="artibody"><p>经济日报记者 张三</p>
        <p>正文包含<a href="/report">正常报告链接</a>，应当保留。</p>
        <p>专题：<a href="/topic">专题导航</a></p>
        <div class="appendQr_wrap"><p>推广关注二维码</p></div>
        <p id="app-kaihu-stock">开户推广</p>
        <p class="article-editor">责任编辑：李四</p>
        <p>文章来源：公开报告</p><p>风险声明仍是文章论述。</p></div>
        <aside>评论区</aside>''')
        result = extract_bytes(raw)
        text = '\n'.join(b['text'] for b in result['blocks'])
        self.assertIn('正常报告链接', text)
        self.assertIn('风险声明仍是文章论述', text)
        for unwanted in ['站点导航', '专题导航', '推广关注二维码', '开户推广', '责任编辑', '文章来源', '评论区']:
            self.assertNotIn(unwanted, text)
        self.assertEqual({x['kind'] for x in result['metadata']}, {'author', 'editor', 'source'})
        self.assertEqual(len(result['excluded']), 3)

    def test_sina_table_rows_and_text_order(self):
        raw = encoded('''<h1 class="main-title">表格文章</h1><div id="artibody">
        <p>表格前</p><table><tr><th>项目</th><th>数量</th></tr>
        <tr><td>服务站</td><td>3</td></tr></table><p>表格后</p></div>''')
        result = extract_bytes(raw, template='sina')
        self.assertEqual([b['kind'] for b in result['blocks']], ['paragraph', 'table', 'paragraph'])
        self.assertEqual(result['blocks'][1]['rows'], [['项目', '数量'], ['服务站', '3']])
        self.assertEqual(result['blocks'][0]['text'], '表格前')
        self.assertEqual(result['blocks'][-1]['text'], '表格后')

    def test_chinanews_byline_not_interview_and_folded_text_kept(self):
        raw = encoded('''<h1 class="content_left_title selected">访谈</h1><div class="main left_zw">
        <p>中新社记者 张三</p><p>中新社记者：为什么要保留这个问题？</p>
        <p>受访者：这是正文内容。</p>
        <div style="display:none">折叠的<span>重要信息</span>仍在源DOM中。</div>
        <div class="pictext">图为试点现场。</div><div class="adInContent">广告占位</div>
        <p class="adEditor">编辑：李四</p></div>''')
        result = extract_bytes(raw)
        self.assertEqual(result['title'], '访谈')
        texts = [b['text'] for b in result['blocks']]
        self.assertNotIn('中新社记者 张三', texts)
        self.assertIn('中新社记者：为什么要保留这个问题？', texts)
        self.assertIn('折叠的重要信息仍在源DOM中。', texts)
        self.assertEqual([b['text'] for b in result['blocks'] if b['kind'] == 'caption'], ['图为试点现场。'])
        self.assertEqual({x['kind'] for x in result['metadata']}, {'author', 'editor'})
        self.assertEqual(result['excluded'][0]['text'], '广告占位')

    def test_blog_br_and_inline_tail_preserve_order(self):
        raw = encoded('''<title>Essay</title><table><tr><td width="435"><font size="2" face="verdana">First <b>bold</b> tail.<br><br>Second paragraph.<p>Third <em>inline</em> text.</p>Fourth tail.</font></td></tr></table>''')
        result = extract_bytes(raw, template='pg_essay')
        self.assertEqual(result['title'], 'Essay')
        self.assertEqual([b['text'] for b in result['blocks']], ['First bold tail.', 'Second paragraph.', 'Third inline text.', 'Fourth tail.'])
        self.assertTrue(all(b['xpath'] for b in result['blocks']))

    def test_unknown_layout_is_rejected_instead_of_silent_whole_page(self):
        with self.assertRaises(ValueError):
            extract_bytes(encoded('<h1>Unknown</h1><div><p>Unadapted layout.</p></div>'))

    def test_ambiguous_container_is_rejected(self):
        raw = encoded('''<h1 class="main-title">Ambiguous</h1>
        <div id="artibody"><p>First candidate</p></div>
        <div id="artibody"><p>Second candidate</p></div>''')
        with self.assertRaises(ValueError):
            extract_bytes(raw, template='sina')

    def test_image_warning_does_not_claim_pixels_extracted(self):
        raw = encoded('''<h1 class="content_left_title">图片文章</h1>
        <div class="left_zw"><p>导语。</p><img src="image.png" alt=""></div>''')
        result = extract_bytes(raw, template='chinanews')
        self.assertTrue(any('images_present_pixels_not_extracted' in w for w in result['warnings']))

    def test_batch_preserves_failure_and_continues_with_other_pages(self):
        from app import batch
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            good = root / 'good.html'
            good.write_bytes(encoded('<h1 class="main-title">Control</h1><div id="artibody"><p>Valid body.</p></div>'))
            bad = root / 'bad.html'
            bad.write_bytes(encoded('<h1>Unknown layout</h1><p>No adapted container.</p>'))
            pages = [dict(id=name, path=str(path), url=None, template='sina', sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                     for name, path in [('synthetic_bad', bad), ('synthetic_good', good)]]
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps(dict(scope='Synthetic controls only', pages=pages)), encoding='utf-8')
            with contextlib.redirect_stdout(io.StringIO()):
                result = batch(manifest, root / 'output', root / 'reports')
            self.assertEqual(result['samples'], 2)
            self.assertEqual(result['extraction_passed'], 1)
            self.assertEqual([p['status'] for p in result['pages']], ['error', 'success'])
            self.assertTrue((root / 'output' / 'synthetic_good.json').exists())
            self.assertTrue((root / 'reports' / 'index.html').exists())
            cli = subprocess.run([sys.executable, '-X', 'utf8', str(Path(__file__).resolve().parents[1] / 'app.py'),
                                  'batch', '--manifest', str(manifest), '--output-dir', str(root / 'cli-output'),
                                  '--report-dir', str(root / 'cli-reports')], capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(cli.returncode, 1)
            self.assertIn('FAIL synthetic_bad', cli.stdout)
            self.assertIn('OK synthetic_good', cli.stdout)


if __name__ == '__main__':
    unittest.main()
