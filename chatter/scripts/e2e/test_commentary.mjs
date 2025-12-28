#!/usr/bin/env node
import net from "node:net";
import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import http from "node:http";
import https from "node:https";

import { formatAjvErrors, validateStreamObservationV1 } from "../../packages/protocol/typescript/validators/index.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..", "..");

const env = (name, fallback) => (process.env[name] && process.env[name].trim() ? process.env[name].trim() : fallback);

const REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0");
const STREAM_OBSERVATIONS_KEY = env("STREAM_OBSERVATIONS_KEY", "stream:observations");
const FIREHOSE_STREAM = env("FIREHOSE_STREAM", "stream:chat.firehose");

const PERSONA_STATS_URL = env("PERSONA_STATS_URL", "http://localhost:8090/stats");
const E2E_ROOM_ID = env("E2E_ROOM_ID", "");
const E2E_AUTO_PREFIX = env("E2E_AUTO_PREFIX", "AUTO_OBS:");

const FIXTURE_HOST_PATH = path.join(repoRoot, "fixtures/stream/frame_fixture_1.png");

const OBS_TEXT = "E2E_AUTO_OBS: dragon appears!!! @ClipGoblin";

const assertNoObsDump = (content, label) => {
  if (content.includes("obs: OBS:")) {
    throw new Error(`${label} contains debug obs dump: ${content}`);
  }
  const withoutAutoPrefix = content.startsWith(E2E_AUTO_PREFIX)
    ? content.slice(E2E_AUTO_PREFIX.length)
    : content;
  if (withoutAutoPrefix.includes("OBS:")) {
    throw new Error(`${label} contains obs prefix: OBS:`);
  }
  if (content.includes("Z |")) {
    throw new Error(`${label} contains timestamp chunk: Z |`);
  }
};

const sha256File = (filePath) => {
  const bytes = fs.readFileSync(filePath);
  return createHash("sha256").update(bytes).digest("hex");
};

const encodeCommand = (args) => {
  const parts = [`*${args.length}\r\n`];
  for (const arg of args) {
    const str = String(arg);
    const byteLen = Buffer.byteLength(str, "utf-8");
    parts.push(`$${byteLen}\r\n${str}\r\n`);
  }
  return Buffer.from(parts.join(""), "utf-8");
};

const parseLine = (buf, offset) => {
  const end = buf.indexOf("\r\n", offset);
  if (end === -1) return null;
  const line = buf.slice(offset, end).toString("utf-8");
  return { line, next: end + 2 };
};

const parseResp = (buf, offset = 0) => {
  if (offset >= buf.length) return null;
  const prefix = String.fromCharCode(buf[offset]);

  if (prefix === "+" || prefix === "-" || prefix === ":") {
    const res = parseLine(buf, offset + 1);
    if (!res) return null;
    const { line, next } = res;
    if (prefix === "+") return { value: line, next };
    if (prefix === ":") return { value: Number.parseInt(line, 10), next };
    const err = new Error(line);
    err.name = "RedisError";
    return { value: err, next };
  }

  if (prefix === "$") {
    const res = parseLine(buf, offset + 1);
    if (!res) return null;
    const len = Number.parseInt(res.line, 10);
    if (Number.isNaN(len)) throw new Error(`Invalid bulk length: ${res.line}`);
    if (len === -1) return { value: null, next: res.next };
    const end = res.next + len;
    if (end + 2 > buf.length) return null;
    const data = buf.slice(res.next, end).toString("utf-8");
    if (buf.toString("utf-8", end, end + 2) !== "\r\n") {
      throw new Error("Invalid bulk terminator");
    }
    return { value: data, next: end + 2 };
  }

  if (prefix === "*") {
    const res = parseLine(buf, offset + 1);
    if (!res) return null;
    const len = Number.parseInt(res.line, 10);
    if (Number.isNaN(len)) throw new Error(`Invalid array length: ${res.line}`);
    if (len === -1) return { value: null, next: res.next };
    const items = [];
    let cursor = res.next;
    for (let i = 0; i < len; i += 1) {
      const parsed = parseResp(buf, cursor);
      if (!parsed) return null;
      items.push(parsed.value);
      cursor = parsed.next;
    }
    return { value: items, next: cursor };
  }

  throw new Error(`Unsupported RESP prefix: ${prefix}`);
};

class RedisClient {
  constructor({ host, port }) {
    this.host = host;
    this.port = port;
    this.socket = null;
    this.buffer = Buffer.alloc(0);
    this.pending = [];
  }

  async connect() {
    if (this.socket) return;
    this.socket = net.createConnection({ host: this.host, port: this.port });
    this.socket.setNoDelay(true);
    this.socket.on("data", (chunk) => this._onData(chunk));
    this.socket.on("error", (err) => this._onError(err));
    await new Promise((resolve, reject) => {
      this.socket.once("connect", resolve);
      this.socket.once("error", reject);
    });
  }

  async quit() {
    if (!this.socket) return;
    try {
      await this.send(["QUIT"]);
    } catch {
      // ignore
    }
    this.socket.destroy();
    this.socket = null;
  }

  _onError(err) {
    while (this.pending.length > 0) {
      this.pending.shift().reject(err);
    }
  }

  _onData(chunk) {
    this.buffer = Buffer.concat([this.buffer, chunk]);
    while (this.pending.length > 0) {
      const parsed = parseResp(this.buffer, 0);
      if (!parsed) return;
      this.buffer = this.buffer.slice(parsed.next);
      const { resolve, reject } = this.pending.shift();
      if (parsed.value instanceof Error) reject(parsed.value);
      else resolve(parsed.value);
    }
  }

  send(args) {
    if (!this.socket) throw new Error("Redis socket not connected");
    const payload = encodeCommand(args);
    return new Promise((resolve, reject) => {
      this.pending.push({ resolve, reject });
      this.socket.write(payload);
    });
  }
}

const parseRedisUrl = (raw) => {
  const url = new URL(raw);
  const host = url.hostname || "localhost";
  const port = url.port ? Number.parseInt(url.port, 10) : 6379;
  const db = url.pathname && url.pathname !== "/" ? Number.parseInt(url.pathname.slice(1), 10) : 0;
  return { host, port, db: Number.isFinite(db) ? db : 0 };
};

const extractDataField = (kv) => {
  if (!Array.isArray(kv)) return null;
  for (let i = 0; i + 1 < kv.length; i += 2) {
    if (kv[i] === "data" && typeof kv[i + 1] === "string") {
      return kv[i + 1];
    }
  }
  return null;
};

const xgroupCreate = async (redis, stream, group, id) => {
  try {
    await redis.send(["XGROUP", "CREATE", stream, group, id, "MKSTREAM"]);
  } catch (err) {
    if (err && typeof err.message === "string" && err.message.includes("BUSYGROUP")) return;
    throw err;
  }
};

const xaddJson = async (redis, stream, jsonObj) => {
  const data = JSON.stringify(jsonObj);
  await redis.send(["XADD", stream, "*", "data", data]);
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const httpGetJson = async (urlStr) => {
  const u = new URL(urlStr);
  const lib = u.protocol === "https:" ? https : http;

  return await new Promise((resolve, reject) => {
    const req = lib.request(
      {
        hostname: u.hostname,
        port: u.port ? Number.parseInt(u.port, 10) : u.protocol === "https:" ? 443 : 80,
        path: `${u.pathname}${u.search}`,
        method: "GET",
      },
      (res) => {
        let body = "";
        res.setEncoding("utf-8");
        res.on("data", (chunk) => (body += chunk));
        res.on("end", () => {
          try {
            resolve(JSON.parse(body));
          } catch (e) {
            reject(new Error(`Failed to parse JSON from ${urlStr}: ${String(e)} body=${body.slice(0, 200)}`));
          }
        });
      }
    );
    req.on("error", reject);
    req.end();
  });
};

const getPersonaRoomId = async () => {
  if (E2E_ROOM_ID) return E2E_ROOM_ID;
  try {
    const stats = await httpGetJson(PERSONA_STATS_URL);
    if (stats && typeof stats.room_id === "string" && stats.room_id.trim()) return stats.room_id.trim();
  } catch {
    // ignore
  }
  return "room:demo";
};

const ensureAutoCommentaryEnabled = async () => {
  try {
    const stats = await httpGetJson(PERSONA_STATS_URL);
    if (stats && stats.auto_commentary_enabled) return;
  } catch (err) {
    throw new Error(`Failed to reach persona_workers stats at ${PERSONA_STATS_URL}: ${err.message || err}`);
  }
  throw new Error(
    "AUTO_COMMENTARY is disabled. Set AUTO_COMMENTARY_ENABLED=1 (or use an enabled config) before running this test."
  );
};

const waitForAutoReply = async ({ redis, group, consumer, roomId }) => {
  const deadline = Date.now() + 25_000;
  while (Date.now() < deadline) {
    const reply = await redis
      .send(["XREADGROUP", "GROUP", group, consumer, "COUNT", "10", "BLOCK", "1000", "STREAMS", FIREHOSE_STREAM, ">"])
      .catch((err) => {
        throw new Error(`XREADGROUP firehose failed: ${err.message || err}`);
      });

    if (!reply) {
      await sleep(50);
      continue;
    }

    for (const [streamName, entries] of reply) {
      if (streamName !== FIREHOSE_STREAM) continue;
      for (const [entryId, kv] of entries) {
        const rawData = extractDataField(kv);
        if (!rawData) {
          await redis.send(["XACK", FIREHOSE_STREAM, group, entryId]);
          continue;
        }

        let msg;
        try {
          msg = JSON.parse(rawData);
        } catch {
          await redis.send(["XACK", FIREHOSE_STREAM, group, entryId]);
          continue;
        }

        await redis.send(["XACK", FIREHOSE_STREAM, group, entryId]);

        if (!msg || typeof msg !== "object") continue;
        if (msg.room_id !== roomId) continue;
        if (msg.origin !== "bot") continue;

        const content = String(msg.content || "");
        const producer = msg.trace && typeof msg.trace === "object" ? msg.trace.producer : null;
        if (producer !== "persona_worker_auto") {
          continue;
        }
        if (!content.startsWith(E2E_AUTO_PREFIX)) continue;
        if (!content.includes("E2E_AUTO_OBS")) continue;
        assertNoObsDump(content, "Auto reply");
        return msg;
      }
    }

    await sleep(50);
  }

  throw new Error("Timed out waiting for auto commentary bot reply");
};

const main = async () => {
  if (!fs.existsSync(FIXTURE_HOST_PATH)) {
    throw new Error(`Missing fixture image: ${FIXTURE_HOST_PATH}`);
  }

  await ensureAutoCommentaryEnabled();

  const frameSha256 = sha256File(FIXTURE_HOST_PATH);
  const stamp = Date.now();
  const roomId = await getPersonaRoomId();
  const ts = new Date(stamp).toISOString();

  const transcriptId = `seg_commentary_${stamp}`;
  const frameId = `frame_commentary_${stamp}`;
  const observationId = `obs_commentary_${stamp}`;

  const observationEvent = {
    schema_name: "StreamObservation",
    schema_version: "1.0.0",
    id: observationId,
    ts,
    room_id: roomId,
    frame_id: frameId,
    frame_sha256: frameSha256,
    transcript_ids: [transcriptId],
    summary: OBS_TEXT,
    tags: ["e2e", "hype", "mentions"],
    entities: ["ClipGoblin"],
    hype_level: 0.9,
    safety: {
      sexual_content: false,
      violence: false,
      self_harm: false,
      hate: false,
      harassment: false,
    },
    trace: {
      provider: "stub",
      model: "stub",
      latency_ms: 1,
      prompt_id: "stream_observation_v1",
      prompt_sha256: "0".repeat(64),
    },
  };

  const obsOk = validateStreamObservationV1(observationEvent);
  if (!obsOk) {
    throw new Error(`StreamObservation schema invalid: ${formatAjvErrors(validateStreamObservationV1.errors)}`);
  }

  const { host, port, db } = parseRedisUrl(REDIS_URL);
  const redis = new RedisClient({ host, port });
  await redis.connect();

  try {
    await redis.send(["PING"]);
    if (db !== 0) await redis.send(["SELECT", String(db)]);

    const firehoseGroup = `e2e_commentary_firehose_${stamp}`;
    const firehoseConsumer = `c_firehose_${stamp}`;
    await xgroupCreate(redis, FIREHOSE_STREAM, firehoseGroup, "$");

    await xaddJson(redis, STREAM_OBSERVATIONS_KEY, observationEvent);

    const botMsg = await waitForAutoReply({
      redis,
      group: firehoseGroup,
      consumer: firehoseConsumer,
      roomId,
    });

    console.log(
      JSON.stringify(
        {
          ok: true,
          room_id: roomId,
          observation_id: observationId,
          bot_message_id: botMsg.id,
        },
        null,
        2
      )
    );
  } finally {
    await redis.quit();
  }
};

main().catch((err) => {
  console.error(err && err.stack ? err.stack : String(err));
  process.exitCode = 1;
});
