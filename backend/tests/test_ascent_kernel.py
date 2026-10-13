import math

import pytest

from app.services.ascent.kernel import ArithmeticKernel, generate_candidates


def test_generated_source_changes_forecasts_and_preserves_probability_bounds():
    candidates = generate_candidates(prior=0.5, limit=4)
    assert len({source for source in candidates}) == 4
    outputs = [ArithmeticKernel(source).predict(0.9) for source in candidates]
    assert outputs == pytest.approx([0.5, 0.6, 0.7, 0.8])
    for source in candidates:
        kernel = ArithmeticKernel(source)
        assert 0 <= kernel.predict(0) <= kernel.predict(1) <= 1


@pytest.mark.parametrize("source", [
    "import os\ndef calibrate(p):\n    return p\n",
    "def calibrate(p):\n    return __import__('os').environ\n",
    "def calibrate(p):\n    return p.__class__\n",
    "def calibrate(p):\n    while True: pass\n",
    "def calibrate(p):\n    return [p][0]\n",
    "def calibrate(p):\n    return open('/tmp/secret')\n",
    "def calibrate(p):\n    return 2 ** 99999999\n",
    "@danger\ndef calibrate(p):\n    return p\n",
    "def calibrate(p=secret):\n    return p\n",
    "def calibrate(p):\n    return 1e309\n",
    "def calibrate(p):\n    return 'a'\n",
    "def calibrate(p):\n    return True\n",
    "def calibrate(p):\n    return " + "+".join(["p"] * 200),
])
def test_candidate_cannot_execute_host_code(source):
    with pytest.raises(ValueError):
        ArithmeticKernel(source)


@pytest.mark.parametrize("value", [-0.1, 1.1, math.nan, math.inf])
def test_invalid_inputs_fail_closed(value):
    with pytest.raises(ValueError):
        ArithmeticKernel("def calibrate(p):\n    return p\n").predict(value)


@pytest.mark.parametrize("source", [
    "def calibrate(p):\n    return p / 0\n",
    "def calibrate(p):\n    return p + 2\n",
])
def test_invalid_outputs_fail_closed(source):
    with pytest.raises(ValueError):
        ArithmeticKernel(source).predict(0.5)
