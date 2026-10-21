export type SpecKind = "finished" | "preform";
export type SpecShape =
  | "bread_shape"
  | "tile_shape"
  | "rectangular_block"
  | "same_r_tile";

export interface SpecToken {
  label: string;
  raw: string;
  value: number | null;
  tolerance: string | null;
  radius: boolean;
}

export interface SpecPreview {
  normalized: string;
  tokens: SpecToken[];
  error: string | null;
  warning: string | null;
}

const LABELS: Record<string, string[]> = {
  "finished:bread_shape": ["R", "宽度", "长度", "厚度"],
  "finished:tile_shape": ["R 外", "R 内", "弦宽", "长度", "厚度"],
  "preform:rectangular_block": ["长度", "宽度", "厚度"],
  "preform:same_r_tile": ["R", "R", "弦宽", "长度", "厚度"],
};

const EXAMPLES: Record<string, string> = {
  "finished:bread_shape": "R9.6*8.6*42.6*2.1",
  "finished:tile_shape": "R30*R28*17.4*23.5*3.95",
  "preform:rectangular_block": "42.6*8.6(-0.07/-0.09)*2.1(+0.01/-0.01)",
  "preform:same_r_tile": "R30*R30*17.4(+0.02/-0.02)*23.5*3.95(+0.01/-0.01)",
};

const HINTS: Record<string, string> = {
  "finished:bread_shape": "R * 宽度 * 长度 * 厚度",
  "finished:tile_shape": "R 外 * R 内 * 弦宽 * 长度 * 厚度",
  "preform:rectangular_block": "长度 * 宽度(上公差/下公差) * 厚度(上公差/下公差)",
  "preform:same_r_tile":
    "R * R * 弦宽(上公差/下公差) * 长度 * 厚度(上公差/下公差)",
};

const FULLWIDTH_FROM = 0xff01;
const FULLWIDTH_TO = 0xff5e;
const ASCII_OFFSET = 0xfee0;

const DASHES = /[−–—―﹣－]/g;
const MULTIPLY = /[×✕✖✱∗＊]/g;
const SPACES = /[\s 　]+/g;

const key = (kind: SpecKind, shape: SpecShape) => `${kind}:${shape}`;

export function normalizeSpec(input: string): string {
  let value = "";
  for (const character of input) {
    const code = character.codePointAt(0) ?? 0;
    if (code >= FULLWIDTH_FROM && code <= FULLWIDTH_TO) {
      value += String.fromCodePoint(code - ASCII_OFFSET);
    } else {
      value += character;
    }
  }
  return value
    .replace(DASHES, "-")
    .replace(MULTIPLY, "*")
    .replace(/[xX]/g, "*")
    .replace(/[rｒ]/g, "R")
    .replace(SPACES, "")
    .replace(/±/g, "±");
}

export function expectedTokenLabels(
  kind: SpecKind,
  shape: SpecShape,
): string[] {
  return LABELS[key(kind, shape)] ?? [];
}

export function specHint(kind: SpecKind, shape: SpecShape): string {
  return HINTS[key(kind, shape)] ?? "";
}

export function exampleSpec(kind: SpecKind, shape: SpecShape): string {
  return EXAMPLES[key(kind, shape)] ?? "";
}

export function splitTopLevel(value: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let current = "";
  for (const character of value) {
    if (character === "(") depth += 1;
    if (character === ")") depth -= 1;
    if (character === "*" && depth === 0) {
      parts.push(current);
      current = "";
    } else {
      current += character;
    }
  }
  parts.push(current);
  return parts;
}

function formatTolerance(raw: string): string | null {
  const compact = raw.replace(/\s/g, "");
  if (!compact) return null;
  if (compact.startsWith("±")) {
    return /^±\d+(?:\.\d+)?$/.test(compact) ? compact : null;
  }
  const match = compact.match(
    /^([+-]?\d+(?:\.\d+)?)\/([+-]?\d+(?:\.\d+)?)$/,
  );
  if (!match) return null;
  return `${match[1]} / ${match[2]}`;
}

export function parseSpec(
  input: string,
  kind: SpecKind,
  shape: SpecShape,
): SpecPreview {
  const normalized = normalizeSpec(input);
  if (!normalized) {
    return { normalized, tokens: [], error: null, warning: null };
  }

  const invalid = normalized.match(/[^0-9R*().+\-/±]/);
  if (invalid) {
    return {
      normalized,
      tokens: [],
      error: `包含不支持的字符“${invalid[0]}”。`,
      warning: null,
    };
  }

  let depth = 0;
  for (const character of normalized) {
    if (character === "(") depth += 1;
    if (character === ")") depth -= 1;
    if (depth < 0) break;
  }
  if (depth !== 0) {
    return {
      normalized,
      tokens: [],
      error: "括号没有成对闭合。",
      warning: null,
    };
  }

  const parts = splitTopLevel(normalized);
  const labels = expectedTokenLabels(kind, shape);
  if (labels.length && parts.length !== labels.length) {
    return {
      normalized,
      tokens: [],
      error: `当前形态需要 ${labels.length} 段，实际 ${parts.length} 段。${specHint(kind, shape)}`,
      warning: null,
    };
  }

  const tokens: SpecToken[] = [];
  const warnings: string[] = [];
  parts.forEach((part, index) => {
    const label = labels[index] ?? `第 ${index + 1} 段`;
    const match = part.match(
      /^(R)?(\d+(?:\.\d+)?)(?:\(([^()]*)\))?$/i,
    );
    if (!match) {
      warnings.push(`${label}“${part}”无法解析。`);
      tokens.push({
        label,
        raw: part,
        value: null,
        tolerance: null,
        radius: part.startsWith("R"),
      });
      return;
    }
    const value = Number(match[2]);
    if (!Number.isFinite(value) || value <= 0) {
      warnings.push(`${label}必须是大于 0 的数值。`);
    }
    const tolerance = match[3] ? formatTolerance(match[3]) : null;
    if (match[3] && !tolerance) {
      warnings.push(`${label}的公差“${match[3]}”格式建议写成 +0.01/-0.01。`);
    }
    const radius = Boolean(match[1]) || label.startsWith("R");
    if (label.startsWith("R") && !match[1]) {
      warnings.push(`${label}建议以 R 开头。`);
    }
    tokens.push({
      label,
      raw: part,
      value: Number.isFinite(value) ? value : null,
      tolerance,
      radius,
    });
  });

  return {
    normalized,
    tokens,
    error: null,
    warning: warnings.length ? warnings[0] : null,
  };
}

export interface ReliefPreview {
  count: number;
  diameter: number;
  radius: number;
}

export function parseRelief(input: string): ReliefPreview | null {
  const normalized = normalizeSpec(input);
  const match = normalized.match(/^(\d+)-(\d+(?:\.\d+)?)$/);
  if (!match) return null;
  const count = Number(match[1]);
  const diameter = Number(match[2]);
  if (
    !Number.isInteger(count) ||
    count < 1 ||
    count > 8 ||
    !Number.isFinite(diameter) ||
    diameter <= 0
  ) {
    return null;
  }
  return {
    count,
    diameter,
    radius: diameter / 2,
  };
}

export function formatToleranceValue(
  upper: number | null | undefined,
  lower: number | null | undefined,
): string {
  if (upper == null && lower == null) return "—";
  const format = (value: number | null | undefined) =>
    value == null ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
  return `${format(upper)} / ${format(lower)}`;
}
