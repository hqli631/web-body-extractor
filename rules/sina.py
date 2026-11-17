"""Current-conversation AI candidate v2; static Sina article shell only."""
import re
from lxml import html


def extract(data):
    tree = html.document_fromstring(data)
    titles = tree.xpath("//h1[contains(concat(' ',normalize-space(@class),' '),' main-title ')]")
    bodies = tree.xpath("//div[@id='artibody']")
    if len(titles) != 1 or len(bodies) != 1:
        raise ValueError('expected one main-title and one artibody')
    body = bodies[0]
    result = dict(title=' '.join(titles[0].text_content().split()), blocks=[], metadata=[], excluded=[], warnings=[])

    def record(node, kind, text=None):
        clone = html.fromstring(html.tostring(node))
        for junk in clone.xpath('.//script|.//style|.//noscript'):
            junk.drop_tree()
        value = ' '.join(clone.text_content().split()) if text is None else ' '.join(text.split())
        return dict(kind=kind, text=value, xpath=tree.getroottree().getpath(node))

    def record_attribute(node, kind, name):
        value = ' '.join((node.get(name) or '').split())
        return dict(kind=kind, text=value, xpath=tree.getroottree().getpath(node))

    def source_name(value):
        text = ' '.join(value.split())
        text = re.sub(r'^[（(]?\s*文章来源\s*[:：]\s*', '', text)
        text = re.sub(r'[）)]$', '', text)
        return text.strip()

    seen_metadata = set()
    seen_sources = set()

    def add_metadata(item):
        key = (item['kind'], item['text'].casefold())
        if item['text'] and key not in seen_metadata:
            seen_metadata.add(key)
            result['metadata'].append(item)

    def add_source(node, text=None):
        value = source_name(text if text is not None else node.text_content())
        if value and value.casefold() not in seen_sources:
            seen_sources.add(value.casefold())
            add_metadata(record(node, 'source', value))

    # Publication metadata often lives in head tags or the article header,
    # outside the artibody body container.
    dates = tree.xpath("//div[contains(concat(' ',normalize-space(@class),' '),' date-source ')]//span[contains(concat(' ',normalize-space(@class),' '),' date ')]")
    if dates:
        add_metadata(record(dates[0], 'published_at'))
    else:
        published = tree.xpath("//meta[@property='article:published_time' and @content]")
        if published:
            add_metadata(record_attribute(published[0], 'published_at', 'content'))
    sources = tree.xpath("//div[contains(concat(' ',normalize-space(@class),' '),' date-source ')]//*[contains(concat(' ',normalize-space(@class),' '),' source ')]")
    if sources:
        add_source(sources[0])
    meta_authors = tree.xpath("//meta[@property='article:author' and @content]")
    if meta_authors:
        author = record_attribute(meta_authors[0], 'author', 'content')
        if source_name(author['text']).casefold() not in seen_sources:
            add_metadata(author)

    def visit(node):
        if not isinstance(node.tag, str) or node.tag in {'script','style','noscript'}:
            return
        classes = set((node.get('class') or '').split())
        item = record(node, 'paragraph')
        text = item['text']
        if 'appendQr_wrap' in classes or node.get('id') == 'app-kaihu-stock':
            item['kind'] = 'promotion'
            result['excluded'].append(item)
            return
        if 'article-editor' in classes:
            item['kind'] = 'editor'
            add_metadata(item)
            return
        if (node.tag == 'p' and body.xpath('./p') and node is body.xpath('./p')[0] and
                re.fullmatch(r'[\u4e00-\u9fff0-9]{2,20}记者\s+[\u4e00-\u9fff·]{2,8}', text)):
            item['kind'] = 'author'
            add_metadata(item)
            return
        if node.tag == 'p' and text.startswith('专题：') and node.xpath('.//a'):
            item['kind'] = 'topic_navigation'
            result['excluded'].append(item)
            return
        if node.tag == 'p' and re.fullmatch(r'[（(]?文章来源[:：].+?[）)]?', text):
            add_source(node, text)
            return
        if node.tag == 'table':
            rows = [[' '.join(c.text_content().split()) for c in r.xpath('./td|./th')]
                    for r in node.xpath('.//tr')]
            if text:
                item.update(kind='table', rows=rows)
                result['blocks'].append(item)
            return
        if node.tag in {'p','h2','h3','h4','li','figcaption'} or 'pictext' in classes:
            if text:
                item['kind'] = ('caption' if node.tag=='figcaption' or 'pictext' in classes else
                                'subheading' if node.tag.startswith('h') or 'align-Center' in (node.get('cms-style') or '').split() else 'paragraph')
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
