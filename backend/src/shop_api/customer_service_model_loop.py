"""Bounded synthetic product exchange; only server-built enums/facts cross it."""
import json
import re
import time

from shop_api.customer_service import CustomerServiceUnavailable
from shop_api.customer_service_model import ModelProductFacts, prepare_model_request
from shop_api.customer_service_model_turn import ModelTurn


class ModelUnavailable(CustomerServiceUnavailable):
    pass


def run_product_loop(request, session_id, deadline, mcp, product_id, transport):
    verified = {}
    try:
        return _run_product_loop(request, session_id, deadline, mcp, product_id, transport, verified)
    except Exception as error:
        from shop_api.customer_service_product_mcp import ProductMCPFailure
        code = error.code if isinstance(error, ProductMCPFailure) else 'model_unavailable'
        if verified.get('result') is not None and time.monotonic() < deadline:
            return {**verified['result'], 'model_degraded': code}
        if isinstance(error, ProductMCPFailure):
            raise
        raise ModelUnavailable from None


def _run_product_loop(request, session_id, deadline, mcp, product_id, transport, verified_state):
    facts = ModelProductFacts.from_fixture(request.app.state.customer_service_fixtures)
    permitted = next(item for item in facts.model_payload() if facts.resolve(item['product_ref']) == product_id)
    reference = permitted['product_ref']
    payload = prepare_model_request(facts)
    payload['messages'][0]['content'] = 'Use product tools. Final JSON exactly intent=price_stock and product_refs from verified tool results.'
    payload['messages'][1]['content'] = json.dumps({'intent': 'price_stock', 'product_ref': reference})
    payload['tools'] = [
        {'type': 'function', 'function': {'name': 'get_product', 'parameters': {'type': 'object', 'additionalProperties': False,
            'properties': {'product_ref': {'type': 'string', 'enum': [reference]}}, 'required': ['product_ref']}}},
        {'type': 'function', 'function': {'name': 'list_products', 'parameters': {'type': 'object', 'additionalProperties': False,
            'properties': {}, 'required': []}}},
    ]
    turn = ModelTurn(transport._budget, session_id, deadline=deadline)
    used_ids = set()
    result = None
    request.app.state.customer_service_log_writer.verify()
    for _ in range(4):
        if time.monotonic() >= deadline:
            raise CustomerServiceUnavailable
        response = transport.execute(turn, payload, token='')
        choice = response['choices'][0]
        message = choice.get('message')
        if not isinstance(message, dict) or message.get('role') != 'assistant':
            raise CustomerServiceUnavailable
        if choice['finish_reason'] == 'stop':
            if set(message) != {'role', 'content'} or not isinstance(message['content'], str):
                raise CustomerServiceUnavailable
            final = json.loads(message['content'])
            if final != {'intent': 'price_stock', 'product_refs': [reference]} or result is None:
                raise CustomerServiceUnavailable
            return result
        if set(message) != {'role', 'content', 'tool_calls'} or message['content'] not in {None, ''}:
            raise CustomerServiceUnavailable
        calls = message['tool_calls']
        if not isinstance(calls, list) or not 1 <= len(calls) <= 2:
            raise CustomerServiceUnavailable
        sanitized_calls, replies = [], []
        for call in calls:
            if (not isinstance(call, dict) or set(call) != {'id', 'type', 'function'} or call['type'] != 'function'
                    or not isinstance(call['id'], str) or not re.fullmatch(r'call_[1-4]', call['id'])
                    or call['id'] in used_ids):
                raise CustomerServiceUnavailable
            used_ids.add(call['id'])
            function = call['function']
            if not isinstance(function, dict) or set(function) != {'name', 'arguments'} or not isinstance(function['arguments'], str):
                raise CustomerServiceUnavailable
            arguments = json.loads(function['arguments'])
            name = function['name']
            if name == 'get_product' and arguments == {'product_ref': reference}:
                verified = mcp.call(name, {'product_id': facts.resolve(reference)})
                data = verified['data']
            elif name == 'list_products' and arguments == {}:
                verified = mcp.call(name, {'page_size': 20})
                data = next((item for item in verified['data']['items'] if item['id'] == product_id), None)
                if data is None:
                    raise CustomerServiceUnavailable
                verified = {**verified, 'data': data}
            else:
                raise CustomerServiceUnavailable
            if (data['id'] != product_id or data['price'] != permitted['price'] or data['stock'] != permitted['stock']
                    or data['is_listed'] != permitted['is_listed']):
                raise CustomerServiceUnavailable
            result = verified
            verified_state['result'] = verified
            sanitized_calls.append({'id': call['id'], 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(arguments)}})
            replies.append({'role': 'tool', 'tool_call_id': call['id'], 'content': json.dumps(permitted)})
        payload['messages'].append({'role': 'assistant', 'content': None, 'tool_calls': sanitized_calls})
        payload['messages'].extend(replies)
    raise CustomerServiceUnavailable
