import pytest

from shop_api.customer_service import CustomerServiceUnavailable
from shop_api.customer_service_model import measured_input_tokens


def test_estimated_admission_bounds_entire_serialized_request():
    assert measured_input_tokens({'messages': []}) == 527
    with pytest.raises(CustomerServiceUnavailable):
        measured_input_tokens({'messages': [{'role': 'user', 'content': '字' * 4000}]})


def test_oversized_combined_history_and_tool_results_is_rejected():
    # 2000 Chinese codepoints alone require 6000 UTF-8 bytes. Six 1500-byte
    # tool results add 9000, before history/template. It cannot fit 60% of16K.
    request = {'messages': [{'role': 'user', 'content': '字' * 2000}]
               + [{'role': 'tool', 'content': 'x' * 1500}] * 6
               + [{'role': 'user', 'content': '历史'}] * 12}
    with pytest.raises(CustomerServiceUnavailable):
        measured_input_tokens(request)
