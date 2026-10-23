"""Whole-sentence local fictional product grammar. No substring extraction."""
import re


def understand(text, fixtures):
    sentence = text.strip()
    if re.fullmatch(r'(?:请问|请帮我|帮我)?(?:有哪些商品|有什么商品|查看商品列表|看看商品|列出商品)[？?。]?', sentence):
        return 'list', 'list_products', {}
    matches = []
    for product in fixtures.values():
        pattern = r'(?:请问|请帮我查询|帮我查询)?' + re.escape(product.name) + r'(?:的)?(多少钱|价格是多少|还有库存吗|有货吗|库存是多少|价格和库存|价格与库存|多少钱还有多少库存)[？?。]?'
        found = re.fullmatch(pattern, sentence)
        if found:
            intent = 'price_stock' if found.group(1) in {'价格和库存', '价格与库存', '多少钱还有多少库存'} else 'detail'
            matches.append((intent, 'get_product', {'product_id': product.id}))
    return matches[0] if len(matches) == 1 else ('clarify', None, {})
