def discounted_price(price, discount_percent):
    """Return the price after applying a percentage discount."""
    if price < 0 or not 0 <= discount_percent <= 100:
        raise ValueError("Invalid price or discount")
    return price * discount_percent / 100
