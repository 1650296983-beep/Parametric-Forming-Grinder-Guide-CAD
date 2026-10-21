import test from "node:test";
import assert from "node:assert/strict";
import {
  normalizeSpec,
  parseRelief,
  parseSpec,
  splitTopLevel,
} from "../src/spec.ts";

test("normalizeSpec accepts pasted CAD punctuation", () => {
  assert.equal(
    normalizeSpec(" 42.6×8.6（-0.07／-0.09）＊2.1(+0.01/−0.01) "),
    "42.6*8.6(-0.07/-0.09)*2.1(+0.01/-0.01)",
  );
  assert.equal(normalizeSpec("Ｒ９.６＊８.６"), "R9.6*8.6");
});

test("splitTopLevel ignores separators inside tolerances", () => {
  assert.deepEqual(
    splitTopLevel("42.6*8.6(-0.07/-0.09)*2.1(+0.01/-0.01)"),
    ["42.6", "8.6(-0.07/-0.09)", "2.1(+0.01/-0.01)"],
  );
});

test("parseSpec reads a block preform", () => {
  const result = parseSpec(
    "42.6*8.6(-0.07/-0.09)*2.1(+0.01/-0.01)",
    "preform",
    "rectangular_block",
  );
  assert.equal(result.error, null);
  assert.equal(result.tokens.length, 3);
  assert.deepEqual(
    result.tokens.map((token) => token.label),
    ["长度", "宽度", "厚度"],
  );
  assert.equal(result.tokens[1].value, 8.6);
  assert.equal(result.tokens[1].tolerance, "-0.07 / -0.09");
});

test("parseSpec reads a tile finished spec", () => {
  const result = parseSpec(
    "R30*R28*17.4*23.5*3.95",
    "finished",
    "tile_shape",
  );
  assert.equal(result.error, null);
  assert.equal(result.tokens.length, 5);
  assert.equal(result.tokens[0].radius, true);
  assert.equal(result.tokens[2].label, "弦宽");
});

test("parseSpec rejects a wrong segment count", () => {
  const result = parseSpec("R9.6*8.6", "finished", "bread_shape");
  assert.match(result.error ?? "", /需要 4 段/);
});

test("parseSpec rejects unbalanced parentheses", () => {
  const result = parseSpec("42.6*8.6(-0.07/-0.09", "preform", "rectangular_block");
  assert.match(result.error ?? "", /括号/);
});

test("parseSpec warns about malformed tolerance but keeps the value", () => {
  const result = parseSpec(
    "42.6*8.6(-0.07/-0.09/-0.01)*2.1",
    "preform",
    "rectangular_block",
  );
  assert.equal(result.error, null);
  assert.match(result.warning ?? "", /公差/);
  assert.equal(result.tokens[1].value, 8.6);
});

test("parseRelief understands the 4-1 convention", () => {
  assert.deepEqual(parseRelief("4-1"), { count: 4, diameter: 1, radius: 0.5 });
  assert.deepEqual(parseRelief("4−0.5"), {
    count: 4,
    diameter: 0.5,
    radius: 0.25,
  });
  assert.equal(parseRelief("four"), null);
});
