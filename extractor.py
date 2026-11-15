"""Rule routing and evidence validation for adapted static article layouts."""
from lxml import html
from rules import sina, chinanews, pg_essay

SELECTORS = {
    'sina': "//div[@id='artibody']",
    'chinanews': "//div[contains(concat(' ',normalize-space(@class),' '),' left_zw ')]",
    'pg_essay': "//td[@width='435']/font[@size='2' and @face='verdana']",
}
EXTRACTORS = {'sina': sina.extract, 'chinanews': chinanews.extract, 'pg_essay': pg_essay.extract}

def detect_template(tree):
    matches = [key for key, xpath in SELECTORS.items() if tree.xpath(xpath)]
    if len(matches) != 1:
        raise ValueError('Unsupported or ambiguous layout: ' + repr(matches))
    if len(tree.xpath(SELECTORS[matches[0]])) != 1:
        raise ValueError('Expected a unique article container')
    return matches[0]

def validate_result(result, data):
    """Check types, source evidence and order; this is not semantic accuracy."""
    issues = []
    if not isinstance(result, dict) or set(result) != {'title','blocks','metadata','excluded','warnings'}:
        return ['invalid_top_level_contract']
    if not isinstance(result['title'], str) or not result['title'].strip():
        issues.append('empty_title')
    for key in ('blocks','metadata','excluded','warnings'):
        if not isinstance(result[key], list):
            issues.append(key + '_must_be_list')
    if issues:
        return issues
    if not result['blocks']:
        issues.append('empty_body')
    if any(not isinstance(w, str) for w in result['warnings']):
        issues.append('invalid_warning')
    tree = html.document_fromstring(data)
    order = {node: index for index, node in enumerate(tree.iter())}
    last = -1
    for key in ('blocks','metadata','excluded'):
        for block in result[key]:
            if not isinstance(block, dict) or not all(isinstance(block.get(k), str) and block[k] for k in ('kind','xpath')) or not isinstance(block.get('text'),str) or (key != 'excluded' and not block['text']):
                issues.append(key + '_invalid_entry')
                continue
            if key == 'blocks' and block['kind'] not in {'paragraph','subheading','caption','table'}:
                issues.append('unsupported_body_kind')
            try:
                nodes = tree.xpath(block['xpath'])
                if len(nodes) != 1 or not hasattr(nodes[0], 'text_content'):
                    issues.append('xpath_not_unique_element')
                    continue
                original = ' '.join(nodes[0].text_content().split())
                if ' '.join(block['text'].split()) not in original:
                    issues.append('text_missing_in_source')
                if key == 'blocks':
                    current = order[nodes[0]]
                    if current < last:
                        issues.append('body_order_changed')
                    last = current
                if block['kind'] == 'table':
                    expected = [[' '.join(cell.text_content().split()) for cell in row.xpath('./td|./th')] for row in nodes[0].xpath('.//tr')]
                    if block.get('rows') != expected:
                        issues.append('table_structure_changed')
            except (ValueError, TypeError, html.etree.XPathError):
                issues.append('invalid_xpath')
    return sorted(set(issues))

def extract_bytes(data, template='auto'):
    if not isinstance(data, bytes):
        raise TypeError('Input must be HTML bytes')
    if not data.strip():
        raise ValueError('Empty HTML input')
    tree = html.document_fromstring(data)
    selected = detect_template(tree) if template == 'auto' else template
    if selected not in EXTRACTORS:
        raise ValueError('Unknown template: ' + str(selected))
    result = EXTRACTORS[selected](data)
    issues = validate_result(result, data)
    if issues:
        raise ValueError('Extraction evidence/contract validation failed: ' + ', '.join(issues))
    return result
