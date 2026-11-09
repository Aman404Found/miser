function discountedPrice(price, discount_percent) {
  if (price < 0 || discount_percent < 0 || discount_percent > 100) {
    throw new RangeError('Invalid price or discount');
  }
  return price * discount_percent / 100;
}

module.exports = { discountedPrice };
