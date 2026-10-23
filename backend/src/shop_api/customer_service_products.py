"""Restricted product tools; identity and fixture context come only from the server."""

from collections.abc import Callable, Mapping
from datetime import datetime
import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from shop_api.catalog import Product
from shop_api.customer_service import CustomerServiceUnavailable, ProductFixture, QueryDeadline


class ListProductsArguments(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    keyword: str = Field(default='', max_length=100)
    category: str | None = Field(default=None, max_length=64)
    page: int = Field(default=1, ge=1, le=100)
    page_size: int = Field(default=10, ge=1, le=20)


class GetProductArguments(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    product_id: Annotated[str, Field(max_length=36)]


class ProductTools:
    tool_names = ('list_products', 'get_product')
    server_name = 'shop-products'

    @staticmethod
    def verify_result(name, result):
        from shop_api.customer_service_product_mcp import verified_result
        return verified_result(result, name)

    def __init__(self, session: Session, fixtures: Mapping[str, ProductFixture], request_id: str, clock: Callable[[], datetime], *, deadline=None):
        self._session = session
        self._fixtures = fixtures
        self._request_id = request_id
        self._clock = clock
        self._calls = 0
        self._seen: set[tuple[str, str]] = set()
        self._deadline = deadline or QueryDeadline(45.0)

    def call(self, name: Literal['list_products', 'get_product'], arguments: dict) -> dict:
        if name not in {'list_products', 'get_product'}:
            raise HTTPException(status_code=422, detail='工具参数无效')
        list_params: ListProductsArguments | None = None
        detail_params: GetProductArguments | None = None
        try:
            if name == 'list_products':
                list_params = ListProductsArguments.model_validate(arguments)
                list_params.keyword = list_params.keyword.strip().casefold()
            else:
                detail_params = GetProductArguments.model_validate(arguments)
                detail_params.product_id = str(UUID(detail_params.product_id))
        except (ValidationError, ValueError):
            raise HTTPException(status_code=422, detail='工具参数无效') from None
        normalized = list_params or detail_params
        assert normalized is not None
        if self._calls >= 2:
            raise HTTPException(status_code=503, detail='商品工具额度已用完')
        call_key = (name, json.dumps(normalized.model_dump(), sort_keys=True, separators=(',', ':')))
        if call_key in self._seen:
            raise HTTPException(status_code=422, detail='重复商品工具调用')
        self._seen.add(call_key)
        products = self._read_products()
        self._deadline.check()
        if len(products) != len(self._fixtures) or any(not self._fixtures[str(product.id)].matches(product) for product in products):
            raise CustomerServiceUnavailable
        if detail_params is not None:
            product = next((product for product in products if str(product.id) == detail_params.product_id and product.is_listed), None)
            if product is None:
                raise HTTPException(status_code=403, detail='未找到可访问的记录')
            data = self._facts(product)
            status = 'ok'
        else:
            assert list_params is not None
            keyword = list_params.keyword
            matching = [product for product in products if product.is_listed
                        and (not keyword or keyword in product.name.casefold())
                        and (list_params.category is None or product.category == list_params.category)]
            start = (list_params.page - 1) * list_params.page_size
            items = [self._facts(product) for product in matching[start:start + list_params.page_size]]
            data = {'items': items, 'total': len(matching), 'page': list_params.page, 'page_size': list_params.page_size,
                    'has_more': start + list_params.page_size < len(matching)}
            status = 'ok' if items else 'empty'
        return {'request_id': self._request_id, 'queried_at': self._clock().isoformat(), 'status': status, 'data': data}

    def _read_products(self):
        # A savepoint preserves the caller's session/advisory locks and dedupe
        # transaction when a retryable read fails. Never roll back the outer turn.
        for attempt in range(2):
            if self._calls >= 2:
                raise HTTPException(status_code=503, detail='商品工具额度已用完')
            self._deadline.check()
            self._calls += 1
            try:
                with self._session.begin_nested():
                    query_deadline = QueryDeadline(3.0)
                    self._deadline.apply(self._session, maximum_seconds=3.0)
                    products = self._session.scalars(select(Product).where(Product.id.in_(tuple(self._fixtures))).order_by(Product.listed_at.desc(), Product.id.asc())).all()
                    query_deadline.check()
                return products
            except DBAPIError as error:
                sqlstate = getattr(error.orig, 'sqlstate', None)
                if attempt or self._calls >= 2 or sqlstate not in {'40001', '40P01', '55P03', '57014'}:
                    raise
        raise CustomerServiceUnavailable

    @staticmethod
    def _facts(product: Product) -> dict:
        return {'id': str(product.id), 'name': product.name, 'category': product.category,
                'price': str(product.price), 'stock': product.stock, 'is_listed': product.is_listed}
