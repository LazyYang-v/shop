"""Private stateless MCP 2025-03-26 HTTP profile over in-process ASGI.

No socket, configurable URL, browser route or generic tool forwarding exists.
Identity/fixtures/turn counters are bound outside the JSON-RPC arguments.
"""
import asyncio
import json
import time
import httpx
from datetime import datetime
from uuid import UUID

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import DBAPIError

from shop_api.customer_service import CustomerServiceUnavailable, QueryDeadlineExceeded
from shop_api.customer_service_products import ListProductsArguments, GetProductArguments

class CustomerServiceMCPFailure(CustomerServiceUnavailable):
    def __init__(self, code='mcp_unavailable'):
        self.code = code
        super().__init__(code)


ProductMCPFailure = CustomerServiceMCPFailure


VERSION = '2025-03-26'
TOOLS = [dict(name=name, inputSchema=schema.model_json_schema()) for name, schema in
         [('list_products', ListProductsArguments), ('get_product', GetProductArguments)]]


class ProductFact(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: str
    name: str
    category: str
    price: str = Field(pattern=r'^[0-9]+\.[0-9]{2}$')
    stock: int = Field(ge=0)
    is_listed: bool


def verified_result(name, result):
    if not isinstance(result, dict) or set(result) != {'request_id', 'queried_at', 'status', 'data'}:
        raise CustomerServiceUnavailable
    if name not in {'list_products', 'get_product'}:
        raise CustomerServiceUnavailable
    UUID(result['request_id'])
    if datetime.fromisoformat(result['queried_at']).utcoffset() is None:
        raise CustomerServiceUnavailable
    data = result['data']
    if name == 'get_product':
        if result['status'] != 'ok':
            raise CustomerServiceUnavailable
        ProductFact.model_validate(data)
    else:
        if not isinstance(data, dict) or set(data) != {'items', 'total', 'page', 'page_size', 'has_more'}:
            raise CustomerServiceUnavailable
        if (type(data['items']) is not list or len(data['items']) > 20
                or type(data['total']) is not int or not 0 <= data['total'] <= 20
                or type(data['page']) is not int or not 1 <= data['page'] <= 100
                or type(data['page_size']) is not int or not 1 <= data['page_size'] <= 20
                or type(data['has_more']) is not bool
                or result['status'] != ('ok' if data['items'] else 'empty')):
            raise CustomerServiceUnavailable
        for item in data['items']:
            ProductFact.model_validate(item)
    return result


def product_mcp_app(tools):
    app = FastAPI()
    definitions = getattr(tools, 'tool_schemas', TOOLS)
    names = {tool['name'] for tool in definitions}
    server_name = getattr(tools, 'server_name', 'shop-products')
    verify = getattr(tools, 'verify_result', verified_result)

    @app.post('/mcp')
    async def rpc(request: Request):
        identifier = None
        try:
            raw = await request.body()
            if len(raw) > 16384:
                raise ValueError
            body = json.loads(raw)
            if not isinstance(body, dict) or body.get('jsonrpc') != '2.0':
                raise ValueError
            method = body.get('method')
            if method == 'notifications/initialized':
                if set(body) != {'jsonrpc', 'method'}:
                    raise ValueError
                return Response(status_code=202)
            identifier = body.get('id')
            if type(identifier) is not int or not 1 <= identifier <= 100:
                raise ValueError
            if set(body) != {'jsonrpc', 'id', 'method', 'params'} or not isinstance(body['params'], dict):
                raise ValueError
            params = body['params']
            if method == 'initialize':
                if params != {'protocolVersion': VERSION, 'capabilities': {}, 'clientInfo': {'name': 'shop-local', 'version': '1'}}:
                    raise ValueError
                result = {'protocolVersion': VERSION, 'capabilities': {'tools': {'listChanged': False}},
                          'serverInfo': {'name': server_name, 'version': '1'}}
            elif method == 'tools/list' and params == {}:
                result = {'tools': definitions}
            elif method == 'tools/call' and set(params) == {'name', 'arguments'}:
                name = params['name']
                if name not in names or not isinstance(params['arguments'], dict):
                    raise ValueError
                data = verify(name, tools.call(name, params['arguments']))
                result = {'content': [{'type': 'text', 'text': json.dumps(data, separators=(',', ':'))}], 'isError': False}
            else:
                return JSONResponse({'jsonrpc': '2.0', 'id': identifier, 'error': {'code': -32601, 'message': 'Unsupported method'}})
            return JSONResponse({'jsonrpc': '2.0', 'id': identifier, 'result': result})
        except Exception as error:
            category = ('resource_unavailable' if isinstance(error, HTTPException) and error.status_code == 403
                        else 'state_conflict' if isinstance(error, HTTPException) and error.status_code == 409
                        else 'invalid_input' if isinstance(error, HTTPException) and error.status_code == 422
                        else 'mcp_timeout' if (isinstance(error, (QueryDeadlineExceeded, TimeoutError, httpx.TimeoutException))
                                               or isinstance(error, DBAPIError) and getattr(error.orig, 'sqlstate', None) == '57014')
                        else 'invalid_input' if isinstance(error, ValueError)
                        else 'mcp_unavailable')
            return JSONResponse({'jsonrpc': '2.0', 'id': identifier, 'error': {
                'code': -32602 if category == 'invalid_input' else -32000,
                'message': 'Customer service request unavailable', 'data': {'code': category}}})
    return app


class CustomerServiceMCP:
    """Private MCP client for whichever bounded tool set the caller supplies."""

    def __init__(self, tools, *, deadline=None, asgi_app=None):
        self._definitions = getattr(tools, 'tool_schemas', TOOLS)
        self._names = tuple(tool['name'] for tool in self._definitions)
        self._server_name = getattr(tools, 'server_name', 'shop-products')
        self._verify = getattr(tools, 'verify_result', verified_result)
        self._app = asgi_app if asgi_app is not None else product_mcp_app(tools)
        self._deadline = deadline if deadline is not None else time.monotonic() + 45
        self._id = 0
        self._ready = False

    def _request(self, method, params):
        self._id += 1
        response = self._post('/mcp', json={'jsonrpc': '2.0', 'id': self._id, 'method': method, 'params': params},
                                     headers={'MCP-Protocol-Version': VERSION, 'Accept': 'application/json, text/event-stream'})
        if response.status_code != 200 or len(response.content) > 65536:
            raise CustomerServiceUnavailable
        value = response.json()
        if (isinstance(value, dict) and set(value) == {'jsonrpc', 'id', 'error'}
                and value['jsonrpc'] == '2.0' and type(value['id']) is int and value['id'] == self._id):
            error = value['error']
            allowed = {'invalid_input', 'resource_unavailable', 'state_conflict', 'mcp_timeout', 'mcp_unavailable'}
            if (isinstance(error, dict) and set(error) == {'code', 'message', 'data'}
                    and type(error['code']) is int and error['code'] in {-32602, -32000}
                    and error['message'] == 'Customer service request unavailable' and isinstance(error['data'], dict)
                    and set(error['data']) == {'code'} and error['data']['code'] in allowed):
                raise ProductMCPFailure(error['data']['code'])
            raise ProductMCPFailure()
        if (not isinstance(value, dict) or set(value) != {'jsonrpc', 'id', 'result'}
                or value['jsonrpc'] != '2.0' or type(value['id']) is not int or value['id'] != self._id):
            raise CustomerServiceUnavailable
        return value['result']

    def initialize(self):
        result = self._request('initialize', {'protocolVersion': VERSION, 'capabilities': {}, 'clientInfo': {'name': 'shop-local', 'version': '1'}})
        if result != {'protocolVersion': VERSION, 'capabilities': {'tools': {'listChanged': False}},
                      'serverInfo': {'name': self._server_name, 'version': '1'}}:
            raise CustomerServiceUnavailable
        notification = self._post('/mcp', json={'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        if notification.status_code != 202 or notification.content:
            raise CustomerServiceUnavailable
        self._ready = True

    def tools(self):
        if not self._ready:
            raise CustomerServiceUnavailable
        result = self._request('tools/list', {})
        if result != {'tools': self._definitions}:
            raise CustomerServiceUnavailable
        return result['tools']

    def call(self, name, arguments):
        if not self._ready or name not in self._names:
            raise CustomerServiceUnavailable
        result = self._request('tools/call', {'name': name, 'arguments': arguments})
        if (not isinstance(result, dict) or set(result) != {'content', 'isError'} or result['isError'] is not False
                or not isinstance(result['content'], list) or len(result['content']) != 1
                or set(result['content'][0]) != {'type', 'text'} or result['content'][0]['type'] != 'text'):
            raise CustomerServiceUnavailable
        return self._verify(name, json.loads(result['content'][0]['text']))

    def _post(self, path, **kwargs):
        async def send():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self._app), base_url='http://shop-local') as client:
                remaining = min(3.0, self._deadline - time.monotonic())
                if remaining <= 0:
                    raise ProductMCPFailure('mcp_timeout')
                response = await asyncio.wait_for(client.post(path, **kwargs), timeout=remaining)
                if time.monotonic() >= self._deadline:
                    raise ProductMCPFailure('mcp_timeout')
                return response
        try:
            return asyncio.run(send())
        except (TimeoutError, httpx.TimeoutException):
            raise ProductMCPFailure('mcp_timeout') from None
        except ProductMCPFailure:
            raise
        except Exception:
            raise ProductMCPFailure() from None

    def close(self):
        pass


ProductMCP = CustomerServiceMCP
