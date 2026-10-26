def weighted_unit_price(items):
    total_quantity = sum(quantity for price, quantity in items)
    total_value = sum(price for price, quantity in items)
    return total_value / total_quantity
