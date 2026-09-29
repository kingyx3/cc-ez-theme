const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(__dirname, '../theme/snippets/mobile-number-normalize.liquid'),
  'utf8'
);
const script = source.match(/<script>([\s\S]*)<\/script>/)[1];

function normalize(value) {
  const sandbox = {};
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(script, sandbox);
  return sandbox.ccNormalizeSgMobile(value);
}

test('a bare 8-digit Singapore mobile number gets the +65 country code', () => {
  assert.equal(normalize('96556718'), '+6596556718');
});

test('the number that started this bug is not read as Kuwait', () => {
  // "96556718" happens to read as Kuwait's "+965" calling code plus a
  // 5-digit remainder if left unprefixed; it must resolve to Singapore.
  assert.equal(normalize('96556718'), '+6596556718');
  assert.notEqual(normalize('96556718'), '+96556718');
});

test('spaces and dashes in a local number are tolerated', () => {
  assert.equal(normalize('9123 4567'), '+6591234567');
  assert.equal(normalize('9123-4567'), '+6591234567');
});

test('a Singapore number missing only its leading + is completed', () => {
  assert.equal(normalize('6596556718'), '+6596556718');
});

test('a number already carrying an explicit + is left exactly as typed', () => {
  assert.equal(normalize('+96556718'), '+96556718');
  assert.equal(normalize('+60123456789'), '+60123456789');
});

test('an email address is never touched', () => {
  assert.equal(normalize('shopper@example.com'), 'shopper@example.com');
});

test('a value too short or unrecognizable is left untouched', () => {
  assert.equal(normalize('12345'), '12345');
  assert.equal(normalize(''), '');
});
