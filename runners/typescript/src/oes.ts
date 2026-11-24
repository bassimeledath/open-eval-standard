#!/usr/bin/env node
// oes: reference runner for the Open Eval Standard (v1, draft 5). Section numbers refer to skills/oes/SPEC.md.
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import http from "node:http";
import https from "node:https";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { parseAllDocuments } from "yaml";
import Ajv2020 from "ajv/dist/2020.js";

type Obj = Record<string, any>;
type Kind = "target" | "check" | "judge" | "user" | "timeout";
const env = process.env;
const RUNNER = { name: "oes-typescript", version: "0.1.0" };
const HERE = path.dirname(fileURLToPath(import.meta.url));
const RETRIES = env.OES_RETRIES === undefined ? 2 : Math.max(0, Math.floor(Number(env.OES_RETRIES)) || 0);
const DEFAULT_TIMEOUT_S = 300;
const BUILTIN_TRIAL = ["equals", "reply_contains", "reply_not_contains", "tool_called", "tool_not_called"];
const BUILTIN_RUN = ["latency_p95_ms", "cost_per_trial_usd"];
const PATH_RE = /^(reply|data|state|tool_calls|turns)(\.[^.]+)*$/;
const HASH_SKIP = (name: string) => name === "__pycache__" || name === ".DS_Store" || name.endsWith(".pyc");
const MISSING = Symbol("missing");
const EPS = 1e-9;
const NOT_RUN = new WeakSet<Obj>(); // rows whose simulated user ended the conversation before the first turn (5)

class Invalid extends Error { constructor(public reasons: string[]) { super(reasons.join("\n")); } }
class TrialError extends Error { constructor(public kind: Kind, message: string) { super(message); } }

const isObj = (v: any): v is Obj => v !== null && typeof v === "object" && !Array.isArray(v);
const J = (v: any) => JSON.stringify(v);
const J2 = (v: any) => JSON.stringify(v, null, 2);
const log = (s: string) => process.stderr.write(s + "\n");
const tail = (s: string, n = 600) => (s.length > n ? "..." + s.slice(-n) : s).trim();
const mean = (v: number[]) => (v.length ? v.reduce((a, b) => a + b, 0) / v.length : null);
const round = (x: number | null) => (x === null ? null : +x.toPrecision(12));
const list = (v: any) => (Array.isArray(v) ? v : [v]);
const isRunScorer = (s: Obj) => BUILTIN_RUN.includes(s.check) || s.scope === "run";
const judgeModel = (j: Obj): string | null => j.model ?? env.OES_JUDGE_MODEL ?? null;
const userModel = (): string | null => env.OES_USER_MODEL ?? null;

function deepEq(a: any, b: any): boolean {
  if (a === b) return true;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => deepEq(x, b[i]));
  if (isObj(a) && isObj(b)) {
    const ka = Object.keys(a);
    return ka.length === Object.keys(b).length && ka.every((k) => Object.hasOwn(b, k) && deepEq(a[k], b[k]));
  }
  return false;
}

// Output paths (6): a number segment indexes a list, and is a key on an object.
function getPath(out: Obj, p: string): any {
  let cur: any = out;
  for (const s of p.split(".")) {
    if (Array.isArray(cur)) { if (!/^(0|[1-9]\d*)$/.test(s) || +s >= cur.length) return MISSING; cur = cur[+s]; }
    else if (isObj(cur) && Object.hasOwn(cur, s)) cur = cur[s];
    else return MISSING;
  }
  return cur;
}
const matches = (m: Obj, out: Obj) => Object.entries(m).every(([p, v]) => { const g = getPath(out, p); return g !== MISSING && deepEq(g, v); });

// ---------- files in inputs (4.2) ----------
const isFile = (v: any) => isObj(v) && v.type === "file" && typeof v.path === "string";
const mapContent = (c: any, fn: (p: string) => string) => (Array.isArray(c) ? c.map((p) => (isFile(p) ? { ...p, path: fn(p.path) } : p)) : c);
function mapData(v: any, fn: (p: string) => string): any {
  if (Array.isArray(v)) return v.map((x) => mapData(x, fn));
  if (!isObj(v)) return v;
  if (isFile(v)) return { ...v, path: fn(v.path) };
  return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, mapData(x, fn)]));
}
function mapInputFiles(inp: Obj, fn: (p: string) => string): Obj {
  const o = structuredClone(inp);
  if (o.message !== undefined) o.message = mapContent(o.message, fn);
  if (o.messages) o.messages = o.messages.map((m: Obj) => ({ ...m, content: mapContent(m.content, fn) }));
  if (o.data) o.data = mapData(o.data, fn);
  if (o.script) o.script = o.script.map((it: any) => isObj(it)
    ? { ...it, ...(it.message !== undefined && { message: mapContent(it.message, fn) }), ...(it.data && { data: mapData(it.data, fn) }) }
    : mapContent(it, fn));
  return o;
}
// Every regular file under p (or p itself), for the eval hash (8.2).
function listFiles(p: string): string[] {
  if (HASH_SKIP(path.basename(p))) return [];
  const st = fs.statSync(p);
  if (st.isDirectory()) return fs.readdirSync(p).flatMap((n) => listFiles(path.join(p, n)));
  return st.isFile() ? [p] : [];
}

// ---------- loading and validation (3, 7, 9) ----------
interface Loaded { file: string; dir: string; ev: Obj; cases: Obj[]; casesFile?: string; judges: Record<string, Obj> }

// YAML 1.2, core schema; duplicate keys and more than one document are errors (3).
// A value JSON can't hold, such as .inf or .nan (9.2).
const nonFinite = (v: any): boolean => typeof v === "number" ? !Number.isFinite(v) : v !== null && typeof v === "object" && Object.values(v).some(nonFinite);

function readYaml(file: string, what: string): any {
  let text: string;
  try { text = fs.readFileSync(file, "utf8"); } catch (e: any) { throw new Invalid([`${what}: cannot read ${file}: ${e.message}`]); }
  const docs = parseAllDocuments(text, { version: "1.2", schema: "core", uniqueKeys: true, merge: false }) as any;
  if (!Array.isArray(docs)) return null;
  if (docs.length > 1) throw new Invalid([`${what}: ${file} holds ${docs.length} YAML documents; only one is allowed`]);
  const errs = docs.flatMap((d: any) => d.errors);
  if (errs.length) throw new Invalid(errs.map((e: any) => `${what}: YAML error in ${file}: ${e.message}`));
  const v = docs.length ? docs[0].toJS() : null;
  if (nonFinite(v)) throw new Invalid([`${what}: ${file} holds a value JSON can't hold, such as .inf or .nan`]);
  return v;
}

function schemaDir(): string {
  const dirs = env.OES_SCHEMA_DIR ? [env.OES_SCHEMA_DIR] : [path.resolve(HERE, "../schemas")];
  const d = dirs.find((d) => d && fs.existsSync(path.join(d, "eval.schema.json")));
  if (!d) throw new Error(`cannot find eval.schema.json (looked in ${dirs.filter(Boolean).join(", ")}); set OES_SCHEMA_DIR`);
  return d;
}

let validators: { evalV: any; caseV: any; judgeV: any } | undefined;
function getValidators() {
  if (!validators) {
    const dir = schemaDir(), read = (f: string) => JSON.parse(fs.readFileSync(path.join(dir, f), "utf8"));
    const schema = read("eval.schema.json");
    const Ajv: any = (Ajv2020 as any).default ?? Ajv2020;
    const ajv = new Ajv({ allErrors: true, strict: false });
    ajv.addSchema(schema);
    validators = { evalV: ajv.getSchema(schema.$id), caseV: ajv.compile({ $ref: schema.$id + "#/$defs/case" }), judgeV: ajv.compile(read("judge.schema.json")) };
  }
  return validators;
}
const fmtErrs = (errs: any[], where: string) =>
  [...new Set(errs.map((e) => `${where}${e.instancePath || ""}: ${e.message}${e.params && Object.keys(e.params).length ? " " + J(e.params) : ""}`))];

// A built-in check's expected entry must have the right shape (6).
function shapeError(check: string, exp: any): string | null {
  const strList = Array.isArray(exp) && exp.length > 0 && exp.every((x) => typeof x === "string");
  switch (check) {
    case "equals":
      if (!isObj(exp) || !Object.keys(exp).length) return "must be a map of output paths to values";
      for (const k of Object.keys(exp)) if (!PATH_RE.test(k)) return `"${k}" is not an output path (it must start with reply, data, state, tool_calls or turns)`;
      return null;
    case "reply_contains": case "reply_not_contains": case "tool_not_called":
      return strList ? null : `must be a non-empty list of ${check === "tool_not_called" ? "tool names" : "texts"}`;
    case "tool_called":
      return Array.isArray(exp) && exp.length > 0 && exp.every((x) => typeof x === "string" || (isObj(x) && typeof x.name === "string"
        && (x.args === undefined || isObj(x.args)) && Object.keys(x).every((k) => k === "name" || k === "args")))
        ? null : "must be a non-empty list of tool names or {name, args}";
  }
  return null;
}

function loadJudge(dir: string, name: string, errs: string[]): Obj | undefined {
  const f = path.join(dir, "judges", `${name}.judge.yaml`);
  if (!fs.existsSync(f)) { errs.push(`judge "${name}": file not found: ${f}`); return; }
  let j: any;
  try { j = readYaml(f, `judge "${name}"`); } catch (e: any) { errs.push(...e.reasons); return; }
  const { judgeV } = getValidators();
  if (!judgeV(j)) { errs.push(...fmtErrs(judgeV.errors, `judge "${name}"`)); return; }
  if (j.name !== name) errs.push(`judge "${name}": field name must be "${name}" (got ${J(j.name)})`);
  return { ...j, choices: j.choices ?? { pass: 1, fail: 0 }, file: f };
}

function load(evalPath: string): Loaded {
  const file = path.resolve(evalPath), dir = path.dirname(file), errs: string[] = [];
  const ev = readYaml(file, "eval");
  const { evalV, caseV } = getValidators();
  if (!evalV(ev)) throw new Invalid(fmtErrs(evalV.errors, "eval"));
  let cases: Obj[] = ev.cases, casesFile: string | undefined;
  if (!Array.isArray(ev.cases)) {
    casesFile = path.resolve(dir, ev.cases.file);
    let text: string;
    try { text = fs.readFileSync(casesFile, "utf8"); } catch (e: any) { throw new Invalid([`cases file: cannot read ${casesFile}: ${e.message}`]); }
    cases = [];
    text.split(/\r?\n/).forEach((line, i) => {
      if (!line.trim()) return;
      let c: any;
      try { c = JSON.parse(line); } catch (e: any) { errs.push(`${ev.cases.file}:${i + 1}: invalid JSON: ${e.message}`); return; }
      // JSON is YAML 1.2, so the YAML parser finds duplicate keys that JSON.parse would drop.
      if (parseAllDocuments(line, { uniqueKeys: true } as any).some?.((d: any) => d.errors.length)) { errs.push(`${ev.cases.file}:${i + 1}: duplicate key`); return; }
      if (!caseV(c)) errs.push(...fmtErrs(caseV.errors, `${ev.cases.file}:${i + 1}`)); else cases.push(c);
    });
    if (!cases.length && !errs.length) errs.push(`cases file ${ev.cases.file} has no test cases`);
  }
  const dups = (xs: string[], what: string) => [...new Set(xs.filter((x, i) => xs.indexOf(x) !== i))].forEach((x) => errs.push(`two ${what}s named "${x}"`));
  dups(cases.map((c) => c.id), "test case");
  dups(ev.scorers.map((s: Obj) => s.name), "scorer");
  const scorers: Record<string, Obj> = Object.fromEntries(ev.scorers.map((s: Obj) => [s.name, s]));
  const judges: Record<string, Obj> = {};
  for (const s of ev.scorers) if (s.judge && !(s.judge in judges)) { const j = loadJudge(dir, s.judge, errs); if (j) judges[s.judge] = j; }
  for (const c of cases) {
    for (const [k, exp] of Object.entries(c.expected ?? {})) {
      if (!scorers[k]) { errs.push(`case "${c.id}": expected key "${k}" names no scorer`); continue; }
      const bad = typeof scorers[k].check === "string" && exp != null ? shapeError(scorers[k].check, exp) : null;
      if (bad) errs.push(`case "${c.id}": expected.${k} ${bad}`);
    }
    for (const m of c.input.stop_when === undefined ? [] : list(c.input.stop_when))
      for (const k of Object.keys(m)) if (!PATH_RE.test(k)) errs.push(`case "${c.id}": stop_when key "${k}" is not an output path`);
    mapInputFiles(c.input, (p) => { if (!fs.existsSync(path.resolve(dir, p))) errs.push(`case "${c.id}": file not found: ${p}`); return p; });
  }
  if (errs.length) throw new Invalid(errs);
  return { file, dir, ev, cases, casesFile, judges };
}

// eval_hash (8.2): "sha256:" + SHA-256 over (path \0 length \0 bytes) for every file used, sorted by path bytes.
function evalHash(L: Loaded): string {
  const set = new Set<string>([L.file]);
  if (L.casesFile) set.add(L.casesFile);
  for (const j of Object.values(L.judges)) set.add(j.file);
  for (const c of L.cases) mapInputFiles(c.input, (p) => { listFiles(path.resolve(L.dir, p)).forEach((f) => set.add(f)); return p; });
  const checks = path.join(L.dir, "checks");
  if (fs.existsSync(checks)) listFiles(checks).forEach((f) => set.add(f));
  const items = [...set].map((f) => ({ rel: Buffer.from(path.relative(L.dir, f).split(path.sep).join("/"), "utf8"), f }))
    .sort((a, b) => Buffer.compare(a.rel, b.rel));
  const h = crypto.createHash("sha256");
  for (const { rel, f } of items) { const b = fs.readFileSync(f); h.update(rel); h.update(`\0${b.length}\0`); h.update(b); }
  return "sha256:" + h.digest("hex");
}

// ---------- calling things (4.1) ----------
interface Proc { code: number | null; stdout: string; stderr: string; timedOut: boolean }
function runProc(cmd: string, stdin: string, timeoutS: number, cwd: string): Promise<Proc> {
  return new Promise((resolve, reject) => {
    const child = spawn("/bin/sh", ["-c", cmd], { cwd, detached: true });
    let stdout = "", stderr = "", timedOut = false;
    child.stdout.setEncoding("utf8").on("data", (d) => (stdout += d));
    child.stderr.setEncoding("utf8").on("data", (d) => (stderr += d));
    const timer = setTimeout(() => { timedOut = true; try { process.kill(-child.pid!, "SIGKILL"); } catch { child.kill("SIGKILL"); } }, timeoutS * 1000);
    child.on("error", (e) => { clearTimeout(timer); reject(e); });
    child.on("close", (code) => { clearTimeout(timer); resolve({ code, stdout, stderr, timedOut }); });
    child.stdin.on("error", () => {});
    child.stdin.end(stdin);
  });
}
// The whole of stdout is one JSON value, or else its last non-empty line is.
function parseJsonOut(text: string): any {
  try { return JSON.parse(text); } catch {}
  const last = text.split("\n").filter((l) => l.trim()).pop();
  try { return last === undefined ? undefined : JSON.parse(last); } catch { return undefined; }
}

// node:http rather than fetch, whose built-in 300 s header timeout would cap timeout_s.
function httpPost(url: string, body: string, timeoutS: number): Promise<{ status: number; text: string }> {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const req = (u.protocol === "https:" ? https : http).request(u, { method: "POST", headers: { "content-type": "application/json", "content-length": Buffer.byteLength(body) } }, (res) => {
      let text = "";
      res.setEncoding("utf8").on("data", (d) => (text += d)).on("error", reject).on("end", () => { clearTimeout(timer); resolve({ status: res.statusCode!, text }); });
    });
    const timer = setTimeout(() => req.destroy(Object.assign(new Error("timed out"), { name: "TimeoutError" })), timeoutS * 1000);
    req.on("error", (e) => { clearTimeout(timer); reject(e); });
    req.end(body);
  });
}

// One call to a target, custom check or the LLM command: JSON in, one JSON object out.
async function callEndpoint(ep: Obj, payload: any, kind: Kind, cwd: string): Promise<{ json: Obj; ms: number }> {
  const timeoutS = ep.timeout_s ?? DEFAULT_TIMEOUT_S, body = J(payload), t0 = performance.now();
  let text: string;
  if (ep.command) {
    const r = await runProc(ep.command, body, timeoutS, cwd).catch((e) => { throw new TrialError(kind, `cannot start command: ${e.message}`); });
    if (r.timedOut) throw new TrialError("timeout", `${kind} command timed out after ${timeoutS}s`);
    if (r.code !== 0) throw new TrialError(kind, `${kind} command exited with code ${r.code}: ${tail(r.stderr || r.stdout)}`);
    text = r.stdout;
  } else {
    const res = await httpPost(ep.http, body, timeoutS).catch((e) => {
      throw e.name === "TimeoutError" ? new TrialError("timeout", `${kind} HTTP call timed out after ${timeoutS}s`) : new TrialError(kind, `${kind} HTTP call failed: ${e.message}`);
    });
    if (res.status < 200 || res.status > 299) throw new TrialError(kind, `${kind} HTTP ${res.status}: ${tail(res.text)}`);
    text = res.text;
  }
  const ms = performance.now() - t0;
  const json = parseJsonOut(text);
  if (!isObj(json)) throw new TrialError(kind, `${kind} did not return a JSON object: ${tail(text) || "(empty output)"}`);
  return { json, ms };
}

// The LLM command protocol: OES_LLM_COMMAND gets {role, model, prompt} on stdin and prints {text, cost_usd?}.
async function llm(role: "judge" | "user", model: string | null, prompt: string, cwd: string): Promise<{ text: string; cost: number | null }> {
  const { json } = await callEndpoint({ command: env.OES_LLM_COMMAND }, { role, model, prompt }, role, cwd);
  if (typeof json.text !== "string") throw new TrialError(role, `LLM command returned no text: ${tail(J(json), 300)}`);
  if (json.cost_usd !== undefined && typeof json.cost_usd !== "number") throw new TrialError(role, `LLM command returned a cost_usd that is not a number: ${J(json.cost_usd)}`);
  return { text: json.text, cost: json.cost_usd ?? null };
}

// Runs fn up to 1 + RETRIES times (8.1). Returns the value and the number of attempts.
async function withRetry<T>(what: string, kind: Kind, fn: () => Promise<T>): Promise<{ value: T; attempts: number }> {
  for (let a = 0; ; a++) {
    try { return { value: await fn(), attempts: a + 1 }; } catch (e: any) {
      const err = e instanceof TrialError ? e : new TrialError(kind, e?.message ?? String(e));
      (err as any).attempts = a + 1;
      if (a >= RETRIES) throw err;
      log(`  retry ${a + 1}/${RETRIES} (${what}): ${err.kind}: ${err.message}`);
    }
  }
}

// ---------- prompts (5, 7) ----------
const render = (c: any) => (typeof c === "string" ? c : list(c).map((p: Obj) => (p.type === "text" ? p.text : `[file: ${p.path}${p.mime ? ` (${p.mime})` : ""}]`)).join("\n"));
const renderTranscript = (tr: Obj[]) => (tr.length ? tr.map((m) => `${m.role.toUpperCase()}: ${render(m.content)}`).join("\n\n") : "(empty)");

function userPrompt(persona: string, transcript: Obj[]): string {
  return [
    "You are role-playing a user who talks to an AI agent, as part of an automated test. Stay in character as this user.",
    "", "<persona>", persona.trim(), "</persona>",
    "", "<transcript>", renderTranscript(transcript), "</transcript>",
    "", transcript.length ? "Write the user's next message." : "The conversation has not started: you speak first. Write the user's first message.",
    "Reply with the message text only: no quotes, labels or commentary.",
    "If this user would end the conversation now (their goal is met, or the persona says they stop), reply with exactly [done] and nothing else.",
  ].join("\n");
}

function judgePrompt(j: Obj, row: Obj, exp: any): string {
  const o = row.output, choices = Object.keys(j.choices);
  const out = { reply: o.reply, data: o.data, state: o.state, tool_calls: o.tool_calls, ...(o.turns.length > 1 && { turns: o.turns }) };
  return [
    "You are a judge grading the output of an AI agent in an automated evaluation.",
    "", "<instructions>", j.prompt.trim(), "</instructions>",
    "", "<input>", "The test case input (files are given by path):", J2(row.input), "</input>",
    "", "<transcript>", renderTranscript(o.transcript), "</transcript>",
    "", "<output>", "The agent's output: its last turn's reply, data and state, and every tool call (a missing field means the agent did not return it):", J2(out), "</output>",
    "", exp == null ? "There is no expected entry for this test case." : `<expected>\nWhat the test author expects (criteria or a reference answer):\n${J2(exp)}\n</expected>`,
    "", `Reply with only a JSON object, giving your reason first: {"reason": "<one or two sentences>", "choice": "<one of ${choices.map((c) => J(c)).join(", ")}>"}`,
  ].join("\n");
}

// The judge answers {reason, choice} in JSON, read from the first { to the last }; the choice matches ignoring case (7).
function parseJudge(text: string, choices: Obj): { reason: any; choice: string } | null {
  const a = text.indexOf("{"), b = text.lastIndexOf("}");
  let o: any;
  try { o = JSON.parse(text.slice(a, b + 1)); } catch { return null; }
  if (a < 0) return null;
  if (!isObj(o) || typeof o.choice !== "string") return null;
  const keys = Object.keys(choices), want = o.choice.trim().toLowerCase();
  const key = keys.find((k) => k === o.choice) ?? keys.find((k) => k.toLowerCase() === want);
  return key === undefined ? null : { choice: key, reason: o.reason ?? null };
}

// ---------- one trial (4, 5) ----------
function buildOutput(ctx: Obj): Obj {
  const last = ctx.turns[ctx.turns.length - 1] ?? {};
  const o: Obj = { transcript: ctx.transcript, tool_calls: ctx.toolCalls, turns: ctx.turns };
  for (const k of ["reply", "data", "state"]) if (Object.hasOwn(last, k)) o[k] = last[k];
  return o;
}

function checkResponse(r: Obj) {
  const bad = (m: string) => { throw new TrialError("target", `response ${m}`); };
  if (r.reply !== undefined && typeof r.reply !== "string") bad("reply must be text");
  if (r.state !== undefined && !isObj(r.state)) bad("state must be a JSON object");
  if (r.tool_calls !== undefined && !(Array.isArray(r.tool_calls) && r.tool_calls.every((t: any) => isObj(t) && typeof t.name === "string")))
    bad("tool_calls must be a list of objects with a text name");
  if (r.cost_usd !== undefined && typeof r.cost_usd !== "number") bad("cost_usd must be a number");
}

async function execTrial(L: Loaded, c: Obj, ci: number, trial: number, runDir: string, cwd: string, ctx: Obj) {
  ctx.session_id = crypto.randomUUID();
  const dest = path.join(runDir, "files", `${ci + 1}-${c.id.replace(/[^A-Za-z0-9._-]/g, "_")}`, `t${trial}`);
  fs.rmSync(dest, { recursive: true, force: true });
  const copies = new Map<string, string>();
  const input = (ctx.input = mapInputFiles(c.input, (p) => {
    const src = path.resolve(L.dir, p);
    if (!copies.has(src)) { const d = path.join(dest, String(copies.size + 1), path.basename(src)); fs.cpSync(src, d, { recursive: true }); copies.set(src, d); }
    return copies.get(src)!;
  }));
  const tr: Obj[] = (ctx.transcript = input.messages ? [...input.messages] : input.message !== undefined ? [{ role: "user", content: input.message }] : []);
  const firstFromInput = tr.length > 0 || input.data !== undefined;
  const stops = input.stop_when === undefined ? [] : list(input.stop_when);
  let state = input.state ?? {};
  for (let t = 0; t < (input.max_turns ?? Infinity); t++) {
    let item: Obj;
    if (input.script) {
      const k = firstFromInput ? t - 1 : t;
      if (k >= input.script.length) break;
      item = k < 0 ? {} : isObj(input.script[k]) ? input.script[k] : { message: input.script[k] };
    } else if (input.persona) {
      if (t === 0 && tr.length && tr[tr.length - 1].role === "user") item = {};
      else {
        const r = await llm("user", userModel(), userPrompt(input.persona, tr), cwd);
        if (r.cost !== null) ctx.userCost = (ctx.userCost ?? 0) + r.cost;
        if (r.text.trim() === "[done]") { if (t === 0) ctx.notRun = true; break; }
        item = { message: r.text };
      }
    } else {
      if (t > 0) break;
      item = {};
    }
    if (item.message !== undefined) tr.push({ role: "user", content: item.message });
    const req = { session_id: ctx.session_id, messages: structuredClone(tr), data: { ...(input.data ?? {}), ...(item.data ?? {}) }, state };
    const { json: raw, ms } = await callEndpoint(L.ev.target, req, "target", cwd);
    const resp = Object.fromEntries(Object.entries(raw).filter(([, v]) => v !== null)); // a field set to null counts as absent (4.1)
    checkResponse(resp); // an invalid response is not logged as a turn
    ctx.turns.push(resp);
    ctx.latency.push(Math.round(ms));
    if (typeof resp.cost_usd === "number") ctx.agentCost = (ctx.agentCost ?? 0) + resp.cost_usd;
    for (const tc of resp.tool_calls ?? []) ctx.toolCalls.push({ ...tc, turn: t + 1 });
    if (typeof resp.reply === "string") tr.push({ role: "assistant", content: resp.reply });
    state = resp.state ?? {};
    if (stops.some((m) => matches(m, buildOutput(ctx)))) break;
  }
}

function builtinScore(check: string, exp: any, out: Obj): Obj {
  if (exp == null) return { score: null, reason: "no expected entry: skipped" };
  const replies = out.turns.map((t: Obj) => t.reply).filter((r: any) => typeof r === "string").map((r: string) => r.toLowerCase());
  const said = (t: string) => replies.some((r: string) => r.includes(t.toLowerCase()));
  const nameOf = (x: any) => (typeof x === "string" ? x : x.name);
  const argsOk = (x: any, c: Obj) => typeof x === "string" || x.args === undefined ||
    (isObj(c.args) && Object.entries(x.args).every(([k, v]) => Object.hasOwn(c.args, k) && deepEq(c.args[k], v)));
  let bad: string[] = [];
  if (check === "equals") bad = Object.entries(exp).flatMap(([p, v]) => { const g = getPath(out, p); return g !== MISSING && deepEq(g, v) ? [] : [`${p}: expected ${J(v)}, got ${g === MISSING ? "nothing" : J(g)}`]; });
  if (check === "reply_contains") bad = replies.length ? exp.filter((t: string) => !said(t)).map((t: string) => `no reply contains ${J(t)}`) : ["the agent gave no reply"];
  if (check === "reply_not_contains") bad = exp.filter(said).map((t: string) => `a reply contains ${J(t)}`);
  if (check === "tool_called") bad = exp.filter((x: any) => !out.tool_calls.some((c: Obj) => c.name === nameOf(x) && argsOk(x, c))).map((x: any) => `not called: ${J(x)}`);
  if (check === "tool_not_called") bad = exp.filter((x: string) => out.tool_calls.some((c: Obj) => c.name === x)).map((x: string) => `called: ${x}`);
  return { score: bad.length ? 0 : 1, reason: bad.length ? bad.join("; ") : "ok" };
}

function checkResult(j: Obj, run: boolean): Obj {
  if (!Object.hasOwn(j, "score")) throw new TrialError("check", `custom check returned no score: ${tail(J(j), 300)}`);
  const sc = j.score;
  if (sc !== null && (typeof sc !== "number" || !Number.isFinite(sc) || (!run && (sc < 0 || sc > 1))))
    throw new TrialError("check", `custom check returned an invalid score ${J(sc)}${run ? "" : " (must be 0 to 1 or null)"}`);
  return { score: sc, reason: j.reason ?? null, ...(!run && j.value !== undefined && { value: j.value }) };
}

async function scoreOne(L: Loaded, s: Obj, row: Obj, cwd: string): Promise<Obj> {
  const exp = row.expected[s.name];
  if (typeof s.check === "string") return builtinScore(s.check, exp, row.output);
  if (s.check) {
    const payload = { input: row.input, output: row.output, expected: exp ?? null, params: s.params ?? {}, session_id: row.session_id };
    return checkResult((await callEndpoint(s.check, payload, "check", cwd)).json, false);
  }
  const j = L.judges[s.judge];
  const r = await llm("judge", judgeModel(j), judgePrompt(j, row, exp), cwd);
  const p = parseJudge(r.text, j.choices);
  if (!p) throw new TrialError("judge", `judge answer is not JSON {reason, choice} naming one of ${Object.keys(j.choices).join(", ")}: ${tail(r.text, 300)}`);
  return { score: j.choices[p.choice], reason: p.reason, choice: p.choice, cost: r.cost };
}

async function runTrial(L: Loaded, c: Obj, ci: number, trial: number, runDir: string, cwd: string): Promise<Obj> {
  let ctx: Obj = {}, error: Obj | undefined, attempts = 0;
  const fresh = () => ({ input: c.input, transcript: [], turns: [], toolCalls: [], latency: [], agentCost: null, userCost: null });
  try { attempts = (await withRetry(`${c.id} trial ${trial}`, "target", () => execTrial(L, c, ci, trial, runDir, cwd, (ctx = fresh())))).attempts; }
  catch (e: any) { error = { kind: e.kind, message: e.message }; attempts = e.attempts ?? 1; }
  const row: Obj = {
    case_id: c.id, trial, session_id: ctx.session_id ?? null, attempts, tags: c.tags ?? [], input: ctx.input, expected: c.expected ?? {},
    output: buildOutput(ctx), scores: {}, latency_ms: ctx.latency, cost_usd: { agent: ctx.agentCost, judges: null, user: ctx.userCost },
  };
  if (ctx.notRun) NOT_RUN.add(row);
  for (const s of error || ctx.notRun ? [] : L.ev.scorers.filter((s: Obj) => !isRunScorer(s))) {
    try {
      const { cost, ...r } = (await withRetry(`${c.id} trial ${trial} scorer ${s.name}`, s.judge ? "judge" : "check", () => scoreOne(L, s, row, cwd))).value;
      if (typeof cost === "number") row.cost_usd.judges = (row.cost_usd.judges ?? 0) + cost;
      row.scores[s.name] = r;
    } catch (e: any) { error = { kind: e.kind, message: `scorer ${s.name}: ${e.message}` }; row.scores = {}; break; }
  }
  for (const k of ["agent", "judges", "user"]) row.cost_usd[k] = round(row.cost_usd[k]);
  if (error) row.error = error;
  log(`  ${c.id} trial ${trial}: ${error ? `error (${error.kind}): ${error.message}` : ctx.notRun ? "did not run" : Object.entries(row.scores).map(([k, v]: any) => `${k}=${v.score}`).join(" ")}`);
  return row;
}

// ---------- run-level scoring and result (6, 8) ----------
function percentile(vals: number[], p: number): number | null {
  if (!vals.length) return null;
  const s = [...vals].sort((a, b) => a - b);
  return s[Math.max(0, Math.ceil((p / 100) * s.length) - 1)];
}
const okRows = (rows: Obj[]) => rows.filter((r) => !r.error && !NOT_RUN.has(r));

function runBuiltin(check: string, rows: Obj[]): Obj {
  const ok = okRows(rows);
  if (check === "latency_p95_ms") {
    const lat = ok.flatMap((r) => r.latency_ms), v = percentile(lat, 95);
    return { score: v, reason: v === null ? "no turns" : `p95 over ${lat.length} turns` };
  }
  const costs = ok.map((r) => r.cost_usd.agent).filter((x) => typeof x === "number"), v = round(mean(costs));
  return { score: v, reason: v === null ? "the agent reported no cost" : `mean agent cost over ${costs.length} trials` };
}

function aggregate(L: Loaded, rows: Obj[], runRes: Obj): Obj {
  const scores: Obj = {};
  const below = (v: number, x: number) => v < x - EPS;
  for (const s of L.ev.scorers) {
    const [rk, x]: [string?, number?] = s.pass ? (Object.entries(s.pass)[0] as any) : [];
    if (isRunScorer(s)) {
      const r = runRes[s.name] ?? {}, v = typeof r.score === "number" ? r.score : null;
      scores[s.name] = { value: v, passed: !rk || v === null ? null : rk === "min" ? v >= x! - EPS : v <= x! + EPS, reason: r.reason ?? null, ...(r.error && { error: r.error }) };
      continue;
    }
    const byCase = new Map<string, number[]>();
    let skipped = 0;
    for (const r of okRows(rows)) {
      const sc = r.scores[s.name]?.score;
      if (typeof sc === "number") byCase.set(r.case_id, [...(byCase.get(r.case_id) ?? []), sc]); else skipped++;
    }
    const all = [...byCase.values()].flat(), value = mean(all);
    const fails = (vs: number[]) => (rk === "each" ? vs.some((v) => below(v, x!)) : rk === "mean" ? below(mean(vs)!, x!) : vs.some((v) => below(v, 1)));
    scores[s.name] = {
      value,
      passed: !rk || value === null ? null : rk === "each" ? !all.some((v) => below(v, x!)) : !below(value, x!),
      scored: all.length, skipped,
      failing_cases: L.cases.map((c) => c.id).filter((id) => byCase.has(id) && fails(byCase.get(id)!)),
    };
  }
  return scores;
}

function statusOf(L: Loaded, scores: Obj, rows: Obj[], errored: string[], stopped: boolean): string {
  const ruled = L.ev.scorers.filter((s: Obj) => s.pass);
  if (stopped || errored.length || Object.values(scores).some((s: any) => s.error)) return "error";
  if (rows.some((r) => NOT_RUN.has(r)) || ruled.some((s: Obj) => scores[s.name].passed === null)) return "not_evaluated";
  return ruled.some((s: Obj) => scores[s.name].passed === false) ? "failed" : "passed";
}

// Mean cost of one trial (8). The agent's covers only trials that reported a cost; for judges and
// the user a trial with no such call counts as 0, and the value is null if no trial had one.
function costMean(rows: Obj[], k: string): number | null {
  const vals = rows.map((r) => r.cost_usd[k]);
  if (!vals.some((v) => typeof v === "number")) return null;
  return round(mean(k === "agent" ? vals.filter((v) => typeof v === "number") : vals.map((v) => v ?? 0)));
}

async function run(L: Loaded, opts: Obj): Promise<{ runDir: string; result: Obj }> {
  const cwd = process.cwd(), started_at = new Date().toISOString();
  const eval_hash = evalHash(L);
  let run_id: string, runDir: string;
  do {
    run_id = `${started_at.replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z")}-${crypto.randomBytes(4).toString("hex")}`;
    runDir = path.join(cwd, ".oes", "runs", run_id);
  } while (fs.existsSync(runDir));
  fs.mkdirSync(runDir, { recursive: true });
  log(`oes: running ${L.ev.name} (${L.cases.length} cases x ${L.ev.trial_count ?? 1} trials) -> ${runDir}`);
  const rows: Obj[] = [], runRes: Obj = {};
  let stopped: string | null = null;
  try {
    for (const [ci, c] of L.cases.entries())
      for (let t = 1; t <= (L.ev.trial_count ?? 1); t++) rows.push(await runTrial(L, c, ci, t, runDir, cwd));
    for (const s of L.ev.scorers.filter(isRunScorer)) {
      try {
        runRes[s.name] = typeof s.check === "string" ? runBuiltin(s.check, rows)
          : (await withRetry(`run scorer ${s.name}`, "check", async () => checkResult((await callEndpoint(s.check, { rows, params: s.params ?? {} }, "check", cwd)).json, true))).value;
      } catch (e: any) { runRes[s.name] = { score: null, reason: null, error: { kind: e.kind, message: e.message } }; }
      log(`  run scorer ${s.name}: ${runRes[s.name].error ? "error: " + runRes[s.name].error.message : runRes[s.name].score}`);
    }
  } catch (e: any) { stopped = e?.stack ?? String(e); log(`oes: run stopped: ${stopped}`); }
  const noErr = rows.filter((r) => !r.error), lat = okRows(rows).flatMap((r) => r.latency_ms);
  const errored = L.cases.map((c) => c.id).filter((id) => rows.some((r) => r.case_id === id && r.error));
  const scores = aggregate(L, rows, runRes);
  const judgeModels = [...new Set(L.ev.scorers.filter((s: Obj) => s.judge).map((s: Obj) => judgeModel(L.judges[s.judge])).filter(Boolean))];
  const result: Obj = {
    eval: L.ev.name, run_id, started_at, runner: RUNNER, tags: L.ev.tags ?? [], metadata: L.ev.metadata ?? {},
    agent_version: opts.agentVersion ?? env.OES_AGENT_VERSION ?? gitVersion(cwd),
    models: {
      agent: opts.agentModel ?? env.OES_AGENT_MODEL ?? null,
      judge: judgeModels.length > 1 ? judgeModels : judgeModels[0] ?? null,
      user: L.cases.some((c) => c.input.persona) ? userModel() : null,
    },
    eval_hash, status: statusOf(L, scores, rows, errored, !!stopped), scores,
    latency_ms: { p50: percentile(lat, 50), p95: percentile(lat, 95) },
    cost_usd: { agent: costMean(noErr, "agent"), judges: costMean(noErr, "judges"), user: costMean(noErr, "user") },
    cases: { total: L.cases.length, errored },
    ...(stopped && { error: stopped }),
  };
  fs.writeFileSync(path.join(runDir, "rows.jsonl"), rows.map((r) => J(r) + "\n").join(""));
  fs.writeFileSync(path.join(runDir, "result.json"), J2(result) + "\n");
  return { runDir, result };
}

function gitVersion(cwd: string): string | null {
  const r = spawnSync("git", ["describe", "--always", "--dirty"], { cwd, encoding: "utf8" });
  return r.status === 0 && r.stdout.trim() ? r.stdout.trim() : null;
}

// ---------- CLI (8.4) ----------
const USAGE = "usage: oes run <eval file> [--agent-version LABEL] [--agent-model LABEL]\n       oes validate <eval file>";

async function main(argv: string[]): Promise<number> {
  const [cmd, ...rest] = argv, opts: Obj = {}, pos: string[] = [];
  for (let i = 0; i < rest.length; i++) {
    const m = rest[i].match(/^--(agent-version|agent-model)(?:=(.*))?$/);
    if (m) { const v = m[2] ?? rest[++i]; if (v === undefined) { log(USAGE); return 2; } opts[m[1] === "agent-version" ? "agentVersion" : "agentModel"] = v; }
    else if (rest[i].startsWith("--")) { log(`unknown option ${rest[i]}\n${USAGE}`); return 2; }
    else pos.push(rest[i]);
  }
  if (!["run", "validate"].includes(cmd) || pos.length !== 1) { log(USAGE); return 2; }
  let L: Loaded;
  try { L = load(pos[0]); } catch (e: any) {
    if (!(e instanceof Invalid)) throw e;
    log(`invalid eval ${pos[0]}:`);
    for (const r of e.reasons) log(`  - ${r}`);
    return 2;
  }
  if (cmd === "validate") { process.stdout.write(`valid: ${L.ev.name} (${L.cases.length} test cases, ${L.ev.scorers.length} scorers)\n`); return 0; }
  const needs = [L.ev.scorers.some((s: Obj) => s.judge) && "a judge", L.cases.some((c) => c.input.persona) && "a simulated user"].filter(Boolean);
  if (needs.length && !env.OES_LLM_COMMAND) {
    log(`cannot run ${pos[0]}: it needs ${needs.join(" and ")}, and OES_LLM_COMMAND is not set (see README.md, "The LLM command")`);
    return 2;
  }
  const { runDir, result } = await run(L, opts);
  const lines = [`eval ${result.eval}: ${result.status}`];
  for (const [k, v] of Object.entries<any>(result.scores))
    lines.push(`  ${k}: value=${v.value === null ? "null" : +v.value.toFixed(4)} passed=${v.passed}${v.failing_cases?.length ? ` failing=${v.failing_cases.join(",")}` : ""}`);
  if (result.cases.errored.length) lines.push(`  errored cases: ${result.cases.errored.join(", ")}`);
  process.stdout.write(lines.join("\n") + "\n" + runDir + "\n");
  return result.status === "passed" ? 0 : 1;
}

main(process.argv.slice(2)).then(
  (code) => process.stdout.write("", () => process.exit(code)),
  (e) => { log(`oes: fatal: ${e?.stack ?? e}`); process.exit(1); },
);
