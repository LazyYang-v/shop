"""Whole-sentence local fictional product grammar. No substring extraction."""
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CompositeIntent:
    policy_question: str | None = None
    product_id: str | None = None
    product_list: bool = False
    orders: bool = False
    cancel: bool = False
    delivery_refund: bool = False


def understand_composite(text, fixtures):
    """Only complete approved clauses; never extract intent from private prose."""
    from shop_api.customer_service_orders import understand_order
    from shop_api.customer_service_policy import understand_policy_scope
    if is_delivery_refund(text):
        return CompositeIntent(orders=True, cancel=True, delivery_refund=True)
    clauses = re.split(r'[；;]', text.strip())
    if not 2 <= len(clauses) <= 4:
        return None
    values: dict[str, Any] = {}
    for clause in clauses:
        clause = clause.strip()
        if understand_policy_scope(clause) is not None and 'policy_question' not in values:
            values['policy_question'] = clause
        elif clause == '申请取消订单' and not values.get('cancel'):
            values.update(cancel=True, orders=True)
        elif understand_order(clause) == ('list_my_orders', {}) and not values.get('orders'):
            values['orders'] = True
        else:
            intent, name, arguments = understand(clause, fixtures)
            if name is None or 'product_list' in values or 'product_id' in values:
                return None
            if name == 'list_products':
                values['product_list'] = True
            else:
                values['product_id'] = arguments['product_id']
    return CompositeIntent(**values)


DELIVERY_REFUND_TEXT = '快递未到且想退款'


def is_delivery_refund(text):
    return bool(re.fullmatch(r'(?:请问|请帮我)?快递未到(?:且想退款|[，,]我想退款)[？?。]?', text.strip()))


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
