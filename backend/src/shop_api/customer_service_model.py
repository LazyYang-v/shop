"""Offline model boundary. No transport or paid-call enablement exists here."""

from collections.abc import Mapping
from dataclasses import dataclass
import json
import re
from types import MappingProxyType

from shop_api.customer_service import CustomerServiceUnavailable, ProductFixture


@dataclass(frozen=True)
class ModelProductFacts:
    """Rebuild model facts only from the server's verified fixture, never user copy."""

    _products: Mapping[str, ProductFixture]

    @classmethod
    def from_fixture(cls, fixtures: Mapping[str, ProductFixture]):
        if not 1 <= len(fixtures) <= 20 or any(
            key != product.id or not isinstance(product.price, str)
            or not re.fullmatch(r'[0-9]+\.[0-9]{2}', product.price)
            or type(product.stock) is not int or product.stock < 0
            or type(product.is_listed) is not bool
            for key, product in fixtures.items()
        ):
            raise CustomerServiceUnavailable
        return cls(MappingProxyType({f'product_{index}': fixtures[key]
                                    for index, key in enumerate(sorted(fixtures), start=1)}))

    def model_payload(self) -> list[dict]:
        # Deliberately omit raw UUIDs, category/name/description strings and all
        # caller-supplied strings. The browser displays names from business APIs.
        return [{'product_ref': reference, 'price': product.price,
                 'stock': product.stock, 'is_listed': product.is_listed}
                for reference, product in self._products.items()]

    def resolve(self, reference: str) -> str:
        product = self._products.get(reference)
        if product is None:
            raise CustomerServiceUnavailable
        return product.id


def measured_input_tokens(request: dict) -> int:
    """Estimated admission score, not a verified provider token count.

    One UTF-8 byte per token plus 512 template tokens is a documented planning
    assumption. Enforce 60% of the frozen 16384 context reference, and reserve
    the full 12000 input allowance in the independent monetary ledger.
    """
    raw = json.dumps(request, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    estimate = len(raw) + 512
    if estimate > 9830:
        raise CustomerServiceUnavailable('本轮信息过多，请缩小范围')
    return estimate


def prepare_model_request(facts: ModelProductFacts) -> dict:
    request = {
        'model': 'deepseek-flash', 'stream': False,
        'thinking': {'type': 'disabled'}, 'max_tokens': 1500,
        'response_format': {'type': 'json_object'},
        'messages': [{'role': 'system', 'content': 'Only return verified product facts as JSON.'},
                     {'role': 'user', 'content': json.dumps(facts.model_payload(), separators=(',', ':'))}],
    }
    measured_input_tokens(request)
    # Estimated mode does not authorize a real provider call.
    return request
