"""Static CPython documentation Sphinx pages using the semantic main landmark."""
import re
from lxml import html


def extract(data):
    tree = html.document_fromstring(data)
    bodies = tree.xpath("//*[@role='main']")
    if len(bodies) != 1:
        raise ValueError('expected one semantic main container')
    body = bodies[0]
    titles = body.xpath('.//h1')
    if len(titles) != 1:
        raise ValueError('expected one h1 inside the main container')

    def clean(text):
        return re.sub(r'\s*¶\s*$', '', ' '.join(text.split()))

    result = dict(title=clean(titles[0].text_content()), blocks=[], metadata=[], excluded=[], warnings=[])

    def record(node, kind, text=None):
        clone = html.fromstring(html.tostring(node))
        for junk in clone.xpath('.//script|.//style|.//noscript'):
            junk.drop_tree()
        value = ' '.join(clone.text_content().split()) if text is None else text
        return dict(kind=kind, text=value, xpath=tree.getroottree().getpath(node))

    block_tags = {'h2', 'h3', 'h4', 'p', 'pre', 'li', 'dt', 'dd', 'table', 'blockquote'}

    def has_block_descendant(node):
        return bool(node.xpath('.//h2|.//h3|.//h4|.//p|.//pre|.//li|.//dt|.//dd|.//table|.//blockquote'))

    def visit(node):
        if not isinstance(node.tag, str) or node.tag in {'script', 'style', 'noscript'}:
            return
        classes = set((node.get('class') or '').split())
        text = ' '.join(node.text_content().split())

        if 'footnote-list' in classes:
            for child in node:
                visit(child)
            return
        if 'footnote' in classes:
            if text:
                result['blocks'].append(record(node, 'footnote'))
            return
        if node.tag == 'dl':
            for child in node:
                if not isinstance(child.tag, str):
                    continue
                if child.tag == 'dt':
                    item = record(child, 'definition_term')
                    if item['text']:
                        result['blocks'].append(item)
                elif child.tag == 'dd':
                    item = record(child, 'definition_description')
                    if item['text']:
                        result['blocks'].append(item)
            return
        if node.tag == 'table':
            if text:
                item = record(node, 'table')
                item['rows'] = [[' '.join(cell.text_content().split()) for cell in row.xpath('./th|./td')]
                                for row in node.xpath('.//tr')]
                result['blocks'].append(item)
            return
        if node.tag == 'h1':
            return
        if node.tag in {'h2', 'h3', 'h4'}:
            value = clean(text)
            if value:
                result['blocks'].append(record(node, 'subheading', value))
            return
        if node.tag == 'pre':
            if text:
                result['blocks'].append(record(node, 'code_block'))
            return
        if node.tag == 'li':
            if text:
                result['blocks'].append(record(node, 'list_item'))
            return
        if node.tag in {'p', 'blockquote'}:
            if text:
                result['blocks'].append(record(node, 'paragraph'))
            return
        if node.tag in {'div', 'section', 'aside', 'ul', 'ol', 'details'}:
            if text and not has_block_descendant(node):
                result['blocks'].append(record(node, 'paragraph'))
                return
            for child in node:
                visit(child)
            return
        if text:
            result['warnings'].append('unhandled_text_node:' + tree.getroottree().getpath(node))

    for child in body:
        visit(child)
    result['warnings'].append('static_dom_only_no_css_visibility_javascript_or_ocr')
    if body.xpath('.//img'):
        result['warnings'].append('images_present_pixels_not_extracted')
    return result
