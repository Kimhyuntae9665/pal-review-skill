# Synthetic correction example

The deliberately incorrect source and review brief live under
[`tests/fixtures`](../tests/fixtures). Do not silently replace that source: it is
the smoke-test input whose defects a reviewer is expected to identify.

[`weighted_price_fixed.py`](weighted_price_fixed.py) illustrates a supported
correction **after checking the requirement**: multiply price by quantity and
return `0.0` when total quantity is zero. Run the seven local checks with:

```powershell
python examples/verify_weighted_price.py
```

These are source/calculation checks, not another API call or a model accuracy
benchmark. Reviewer arithmetic examples and suggested extra input validation
still require scrutiny; do not adopt them merely because several models agree.
