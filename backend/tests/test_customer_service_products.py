from uuid import uuid4

import pytest
from fastapi import HTTPException

from shop_api.customer_service import ProductFixture
from shop_api.customer_service_products import ProductTools


@pytest.mark.parametrize('name,arguments', [
    ('execute_sql', {'sql': 'SELECT 1'}),
    ('list_products', {'user_id': str(uuid4())}),
    ('list_products', {'url': 'https://example.com'}),
    ('list_products', {'page': True}),
    ('list_products', {'page_size': 21}),
    ('get_product', {'product_id': 'invalid'}),
    ('get_product', {'product_id': str(uuid4()), 'identity': 'admin'}),
])
def test_product_tools_reject_unknown_tools_and_arguments(client, name, arguments):
    with client.app.state.session_factory() as session:
        tools = ProductTools(session, {}, str(uuid4()), client.app.state.clock)
        with pytest.raises(HTTPException) as error:
            tools.call(name, arguments)
        assert error.value.status_code == 422


def test_product_tools_reject_duplicate_normalized_arguments(client):
    fixture = ProductFixture('00000000-0000-0000-0000-000000000001', '春日轻盈针织开衫', '女装', '129.00', 24, True)
    with client.app.state.session_factory() as session:
        tools = ProductTools(session, {fixture.id: fixture}, str(uuid4()), client.app.state.clock)
        tools.call('list_products', {'keyword': '  针织  '})
        with pytest.raises(HTTPException) as error:
            tools.call('list_products', {'keyword': '针织', 'page': 1, 'page_size': 10})
        assert error.value.status_code == 422


@pytest.mark.parametrize('sqlstate,expected', [('40001', 2), ('40P01', 2), ('55P03', 2), ('57014', 2), ('42501', 1), ('08006', 1)])
def test_read_retry_consumes_same_two_attempt_budget(client, monkeypatch, sqlstate, expected):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    fixture = ProductFixture('00000000-0000-0000-0000-000000000001', '春日轻盈针织开衫', '女装', '129.00', 24, True)
    with client.app.state.session_factory() as session:
        original = session.scalars
        attempts = []
        def query(*args, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                session.execute(text(f"DO $$ BEGIN RAISE EXCEPTION 'synthetic read failure' USING ERRCODE = '{sqlstate}'; END $$"))
            return original(*args, **kwargs)
        monkeypatch.setattr(session, 'scalars', query)
        tools = ProductTools(session, {fixture.id: fixture}, str(uuid4()), client.app.state.clock)
        if expected == 1:
            with pytest.raises(DBAPIError):
                tools.call('list_products', {})
        else:
            assert tools.call('list_products', {})['status'] == 'ok'
            with pytest.raises(HTTPException):
                tools.call('get_product', {'product_id': fixture.id})
        assert len(attempts) == expected


def test_mcp_statement_timeout_preserves_category_and_two_attempt_budget(client, monkeypatch):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    from shop_api.customer_service_product_mcp import ProductMCP, ProductMCPFailure

    with client.app.state.session_factory() as session:
        sqlstates = []
        def timed_out_read(*args, **kwargs):
            session.execute(text("SET LOCAL statement_timeout = '10ms'"))
            try:
                session.execute(text('SELECT pg_sleep(0.05) /* PRIVATE_IDENTITY_SENTINEL */'))
            except DBAPIError as error:
                sqlstates.append(error.orig.sqlstate)
                raise
        monkeypatch.setattr(session, 'scalars', timed_out_read)
        mcp = ProductMCP(ProductTools(session, {}, str(uuid4()), client.app.state.clock))
        mcp.initialize()
        with pytest.raises(ProductMCPFailure) as failure:
            mcp.call('list_products', {})
        assert failure.value.code == 'mcp_timeout'
        assert str(failure.value) == 'mcp_timeout'
        assert sqlstates == ['57014', '57014']
        with pytest.raises(ProductMCPFailure) as exhausted:
            mcp.call('get_product', {'product_id': str(uuid4())})
        assert exhausted.value.code == 'mcp_unavailable'
        assert sqlstates == ['57014', '57014']


def test_mcp_expired_query_deadline_is_timeout(client):
    from shop_api.customer_service import QueryDeadline
    from shop_api.customer_service_product_mcp import ProductMCP, ProductMCPFailure

    with client.app.state.session_factory() as session:
        mcp = ProductMCP(ProductTools(session, {}, str(uuid4()), client.app.state.clock,
                                      deadline=QueryDeadline(-1)))
        mcp.initialize()
        with pytest.raises(ProductMCPFailure) as failure:
            mcp.call('list_products', {})
        assert failure.value.code == 'mcp_timeout'


@pytest.mark.parametrize('sqlstate', [None, '42501', '08006'])
def test_mcp_unrelated_dependency_failures_remain_unavailable(client, monkeypatch, sqlstate):
    from sqlalchemy import text
    from shop_api.customer_service import CustomerServiceUnavailable
    from shop_api.customer_service_product_mcp import ProductMCP, ProductMCPFailure

    with client.app.state.session_factory() as session:
        attempts = []
        def unavailable_read(*args, **kwargs):
            attempts.append(1)
            if sqlstate is not None:
                session.execute(text(f"DO $$ BEGIN RAISE EXCEPTION 'PRIVATE_IDENTITY_SENTINEL timeout' USING ERRCODE = '{sqlstate}'; END $$"))
            raise CustomerServiceUnavailable('PRIVATE_IDENTITY_SENTINEL timeout')
        monkeypatch.setattr(session, 'scalars', unavailable_read)
        mcp = ProductMCP(ProductTools(session, {}, str(uuid4()), client.app.state.clock))
        mcp.initialize()
        with pytest.raises(ProductMCPFailure) as failure:
            mcp.call('list_products', {})
        assert failure.value.code == 'mcp_unavailable'
        assert str(failure.value) == 'mcp_unavailable'
        assert len(attempts) == 1


def test_product_tools_share_two_call_budget(client):
    fixture = ProductFixture('00000000-0000-0000-0000-000000000001', '春日轻盈针织开衫', '女装', '129.00', 24, True)
    with client.app.state.session_factory() as session:
        tools = ProductTools(session, {fixture.id: fixture}, str(uuid4()), client.app.state.clock)
        assert tools.call('list_products', {})['data']['items'][0]['stock'] == 24
        assert tools.call('get_product', {'product_id': fixture.id})['data']['price'] == '129.00'
        with pytest.raises(HTTPException) as error:
            tools.call('list_products', {})
        assert error.value.status_code == 503
