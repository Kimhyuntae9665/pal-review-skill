"""Synthetic example after verifying the two stated correctness defects.

This is an illustration, not an automatically applied reviewer patch.
Inputs follow the fixture's nonnegative-price/integer-quantity preconditions.
"""


def weighted_unit_price(items):
    total_quantity = sum(quantity for price, quantity in items)
    if total_quantity == 0:
        return 0.0
    total_value = sum(price * quantity for price, quantity in items)
    return total_value / total_quantity
