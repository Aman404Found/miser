const test = require('node:test');
const assert = require('node:assert/strict');
const { discountedPrice } = require('./pricing');

test('discount is subtracted', () => assert.equal(discountedPrice(200, 10), 180));
test('zero discount', () => assert.equal(discountedPrice(80, 0), 80));
test('full discount', () => assert.equal(discountedPrice(80, 100), 0));
test('invalid input', () => assert.throws(() => discountedPrice(10, 110), RangeError));
