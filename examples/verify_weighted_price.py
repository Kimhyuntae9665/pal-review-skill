"""Run the public corrected example locally; no network, keys or inference."""
import json
from weighted_price_fixed import weighted_unit_price

cases = [([(10, 2), (100, 1)], 40.0), ([(10, 1), (100, 9)], 91.0),
         ([], 0.0), ([(10, 0)], 0.0), ([(10, 2), (20, 2)], 15.0),
         ([(100, 1), (1, 100)], 200 / 101), ([(9, 3), (20, 2), (0, 0)], 13.4)]
for items, expected in cases:
    actual = weighted_unit_price(items)
    assert abs(actual - expected) < 1e-12, (items, expected, actual)
print(json.dumps({"synthetic_example": True, "checks_passed": len(cases), "inference_called": False}))
