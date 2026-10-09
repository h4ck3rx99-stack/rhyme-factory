// PARSE & VALIDATE — accepts a Gemini or Ollama response, extracts JSON, checks it against the schema.
// Never throws: it returns { ok, result | error } and a route_index for the "Route" switch.
const prep = $('Prepare').last().json; // the attempt that produced this response
const ctx = prep.ctx;
const res = $input.first().json;
const MAX_ATTEMPTS = 3;

function validate(value, schema, path, out, mustFill = true) {
  if (out.length > 12 || !schema) return out;
  const t = schema.type;
  const typeOk = {
    STRING: typeof value === 'string',
    INTEGER: Number.isInteger(value),
    NUMBER: typeof value === 'number' && !Number.isNaN(value),
    BOOLEAN: typeof value === 'boolean',
    ARRAY: Array.isArray(value),
    OBJECT: value !== null && typeof value === 'object' && !Array.isArray(value),
  }[t];
  if (!typeOk) { out.push(`${path} should be ${t.toLowerCase()}`); return out; }
  if (t === 'STRING') {
    if (mustFill && !value.trim()) out.push(`${path} is empty`);
    if (schema.enum && (mustFill || value) && !schema.enum.includes(value)) out.push(`${path} must be one of ${schema.enum.join(', ')}`);
  }
  if (t === 'ARRAY') {
    if (schema.minItems && value.length < schema.minItems) out.push(`${path} needs at least ${schema.minItems} items`);
    if (schema.maxItems && value.length > schema.maxItems) out.push(`${path} allows at most ${schema.maxItems} items`);
    value.forEach((v, i) => validate(v, schema.items, `${path}[${i}]`, out, mustFill));
  }
  if (t === 'OBJECT') {
    for (const key of schema.required ?? []) {
      if (mustFill && (value[key] === undefined || value[key] === null)) out.push(`${path}.${key} is missing`);
    }
    for (const [key, sub] of Object.entries(schema.properties ?? {})) {
      const req = mustFill && (schema.required ?? []).includes(key);
      if (value[key] !== undefined && value[key] !== null) validate(value[key], sub, `${path}.${key}`, out, req);
    }
  }
  return out;
}

let provider = 'gemini';
let error = '';
let result = null;
try {
  let text;
  if (res.candidates) {
    const c = res.candidates[0];
    if (!c?.content?.parts) throw new Error(`Gemini returned no content (finishReason: ${c?.finishReason ?? 'unknown'})`);
    if (c.finishReason === 'MAX_TOKENS') throw new Error('the answer was cut off (MAX_TOKENS) - keep it shorter');
    text = c.content.parts.filter((p) => !p.thought).map((p) => p.text ?? '').join('');
  } else if (res.message) {
    provider = 'ollama';
    text = res.message.content ?? '';
  } else if (res.error) {
    provider = 'ollama';
    const msg = typeof res.error === 'string' ? res.error : (res.error.message ?? JSON.stringify(res.error));
    throw new Error(`Gemini failed (see the Gemini node's error output) and the local Ollama fallback also failed: ${msg}`);
  } else if (res.promptFeedback?.blockReason) {
    throw new Error(`Gemini blocked the prompt: ${res.promptFeedback.blockReason}`);
  } else {
    throw new Error(`unexpected response: ${JSON.stringify(res).slice(0, 200)}`);
  }
  text = text.trim().replace(/^```(?:json)?\s*/i, '').replace(/```\s*$/, '');
  const a = text.indexOf('{');
  const b = text.lastIndexOf('}');
  if (a === -1 || b === -1) throw new Error('no JSON object in the answer');
  result = JSON.parse(text.slice(a, b + 1));
  const problems = validate(result, prep.schema, ctx.stage, []);
  if (problems.length) throw new Error(problems.slice(0, 8).join('; '));
} catch (e) {
  error = String(e.message ?? e).slice(0, 700);
}

const ok = !error;
const route_index = ok ? 0 : (ctx.attempt < MAX_ATTEMPTS - 1 ? 1 : 2);
return [{ json: { ok, result, error, provider, attempt: ctx.attempt, route_index, ctx } }];
