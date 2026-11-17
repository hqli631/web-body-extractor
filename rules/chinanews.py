"""Current-conversation AI candidate v2; static Chinanews left_zw shell only."""
import re
from lxml import html


def extract(data):
    tree = html.document_fromstring(data)
    titles = tree.xpath("//h1[contains(concat(' ',normalize-space(@class),' '),' content_left_title ')]")
    bodies = tree.xpath("//div[contains(concat(' ',normalize-space(@class),' '),' left_zw ')]")
    if len(titles)!=1 or len(bodies)!=1:
        raise ValueError('expected one content_left_title and one left_zw')
    body=bodies[0]
    result=dict(title=' '.join(titles[0].text_content().split()),blocks=[],metadata=[],excluded=[],warnings=[])

    # Only a contiguous suffix of explicit production-credit lines is metadata.
    credit_nodes=[]
    meaningful=[n for n in body if isinstance(n.tag,str) and n.tag not in {'script','style'}
                and ' '.join(n.text_content().split())
                and 'adEditor' not in (n.get('class') or '').split()]
    for n in reversed(meaningful):
        value=' '.join(n.text_content().split())
        if n.tag=='p' and re.fullmatch(r'[｜|](?:(?:总策划|策划|统筹|执笔|审校|视觉)[:：].+|.+工作室出品)',value):
            credit_nodes.append(n)
        else:
            break

    def record(node, kind, text=None):
        clone=html.fromstring(html.tostring(node))
        for junk in clone.xpath('.//script|.//style|.//noscript'):
            junk.drop_tree()
        value = ' '.join(clone.text_content().split()) if text is None else ' '.join(text.split())
        return dict(kind=kind,text=value,xpath=tree.getroottree().getpath(node))

    seen_metadata=set()
    def add_metadata(node, kind, text=None):
        item=record(node,kind,text)
        key=(kind,item['text'].casefold())
        if item['text'] and key not in seen_metadata:
            seen_metadata.add(key)
            result['metadata'].append(item)

    # The visible article header sits outside left_zw and carries the publication
    # time and source. Keep those as page information instead of body blocks.
    published=False
    time_containers=tree.xpath("//div[contains(concat(' ',normalize-space(@class),' '),' content_left_time ')]")
    for node in time_containers:
        match=re.search(r'\d{4}年\d{1,2}月\d{1,2}日\s+\d{1,2}:\d{2}',record(node,'published_at')['text'])
        if match:
            add_metadata(node,'published_at',match.group(0))
            published=True
            break
    if not published:
        fallback=tree.xpath("//*[@id='pubtime_baidu']")
        if fallback:
            add_metadata(fallback[0],'published_at')
    sources=tree.xpath("//div[contains(concat(' ',normalize-space(@class),' '),' content_left_time ')]//a[contains(concat(' ',normalize-space(@class),' '),' source ')]")
    if not sources:
        sources=tree.xpath("//*[@id='source_baidu']//a")
    if sources:
        add_metadata(sources[0],'source')

    def visit(node):
        if not isinstance(node.tag,str) or node.tag in {'script','style','noscript'}:
            return
        classes=set((node.get('class') or '').split())
        item=record(node,'paragraph')
        text=item['text']
        if 'adInContent' in classes or node.get('id')=='function_code_page':
            item['kind']='advertisement_or_page_widget'
            result['excluded'].append(item)
            return
        if 'adEditor' in classes:
            item['kind']='editor'
            add_metadata(node,'editor')
            return
        if node in credit_nodes:
            item['kind']='production_credit'
            add_metadata(node,'production_credit')
            return
        # Full-line anchored pattern: interview questions containing a colon do not match.
        if node.tag=='p' and re.fullmatch(r'中新[网社]记者\s+[\u4e00-\u9fff·]{2,12}(?:\s+[\u4e00-\u9fff·]{2,12})*',text):
            item['kind']='author'
            add_metadata(node,'author')
            return
        if node.tag=='table':
            if text:
                item.update(kind='table',rows=[[' '.join(c.text_content().split()) for c in r.xpath('./th|./td')] for r in node.xpath('.//tr')])
                result['blocks'].append(item)
            return
        if node.tag in {'p','h2','h3','h4','li','figcaption'} or 'pictext' in classes:
            if text:
                item['kind']=('caption' if 'pictext' in classes or node.tag=='figcaption' else
                              'subheading' if node.tag in {'h2','h3','h4'} else 'paragraph')
                result['blocks'].append(item)
            return
        if text and node.tag in {'div','section','details'} and not node.xpath('.//p|.//table|.//li|.//h2|.//h3|.//h4|.//figcaption|.//div'):
            result['blocks'].append(item)
            return
        for child in node:
            visit(child)
        if text and not len(node):
            result['warnings'].append('unhandled_text_node:'+item['xpath'])

    for node in body:
        visit(node)
    result['warnings'].append('static_dom_only_no_css_visibility_javascript_or_ocr')
    if body.xpath('.//img'):
        result['warnings'].append('images_present_pixels_not_extracted')
    return result
