#!/usr/bin/env node
import net from "node:net";

const env = (name, fallback) => (process.env[name] && process.env[name].trim() ? process.env[name].trim() : fallback);

const DEFAULT_REDIS_URL = env("REDIS_URL_HOST", env("REDIS_URL", "redis://127.0.0.1:6379/0"));
const DEFAULT_STREAM = env("STREAM_OBSERVATIONS_KEY", "stream:observations");

const usage = () => {
  console.log(`Usage: node scripts/dev/tail_observations.mjs [options]

Options:
  --redis-url <url>   Redis URL (default: REDIS_URL_HOST or redis://127.0.0.1:6379/0)
  --stream <key>      Redis stream key (default: STREAM_OBSERVATIONS_KEY or stream:observations)
  --room-id <id>      Filter by room_id
  --since <id|now>    Start ID (default: now when following, else 0-0)
  --count <n>         Print N observations then exit
  --follow            Keep tailing (default when --count is absent)
  --no-follow         Exit after current read
  --help              Show this help
`);
};

const parseArgs = (argv) => {
  const options = {
    redisUrl: DEFAULT_REDIS_URL,
    stream: DEFAULT_STREAM,
    roomId: null,
    since: null,
    count: null,
    follow: null,
  };

  const takeValue = (arg, name, idx) => {
    if (arg === name) {
      if (idx + 1 >= argv.length) throw new Error(`Missing value for ${name}`);
      return { value: argv[idx + 1], next: idx + 1 };
    }
    if (arg.startsWith(`${name}=`)) {
      return { value: arg.slice(name.length + 1), next: idx };
    }
    return null;
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--help" || arg === "-h") {
      usage();
      process.exit(0);
    }

    const redisUrl = takeValue(arg, "--redis-url", i);
    if (redisUrl) {
      options.redisUrl = redisUrl.value;
      i = redisUrl.next;
      continue;
    }

    const stream = takeValue(arg, "--stream", i);
    if (stream) {
      options.stream = stream.value;
      i = stream.next;
      continue;
    }

    const roomId = takeValue(arg, "--room-id", i);
    if (roomId) {
      options.roomId = roomId.value;
      i = roomId.next;
      continue;
    }

    const since = takeValue(arg, "--since", i);
    if (since) {
      options.since = since.value;
      i = since.next;
      continue;
    }

    const count = takeValue(arg, "--count", i);
    if (count) {
      const parsed = Number.parseInt(count.value, 10);
      if (!Number.isFinite(parsed) || parsed <= 0) throw new Error("--count must be a positive integer");
      options.count = parsed;
      i = count.next;
      continue;
    }

    if (arg === "--follow") {
      options.follow = true;
      continue;
    }

    if (arg === "--no-follow") {
      options.follow = false;
      continue;
    }

    throw new Error(`Unknown argument: ${arg}`);
  }

  return options;
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

const normalizeSince = (value) => {
  if (!value) return null;
  const trimmed = String(value).trim();
  if (!trimmed) return null;
  if (trimmed === "now") return "now";
  if (trimmed === "$") return "now";
  if (trimmed === "0") return "0-0";
  return trimmed;
};

const resolveStartId = async (redis, stream, since) => {
  if (since === "now") {
    const reply = await redis.send(["XREVRANGE", stream, "+", "-", "COUNT", "1"]);
    if (Array.isArray(reply) && reply.length > 0 && Array.isArray(reply[0]) && reply[0][0]) {
      return reply[0][0];
    }
    return "0-0";
  }
  return since || "0-0";
};

const formatList = (items) => {
  if (!Array.isArray(items) || items.length === 0) return "-";
  return items.map((item) => String(item)).join(",");
};

const formatSummary = (summary) => {
  if (typeof summary !== "string" || !summary.trim()) return "-";
  const collapsed = summary.replace(/\s+/g, " ").trim();
  if (collapsed.length <= 200) return collapsed;
  return `${collapsed.slice(0, 197)}...`;
};

const formatHype = (value) => {
  const num = Number(value);
  if (!Number.isFinite(num)) return "-";
  return num.toFixed(2);
};

const main = async () => {
  const opts = parseArgs(process.argv.slice(2));
  const follow = opts.follow ?? opts.count === null;
  const normalizedSince = normalizeSince(opts.since ?? (follow ? "now" : "0-0"));
  const targetCount = opts.count ?? Number.POSITIVE_INFINITY;

  const { host, port, db } = parseRedisUrl(opts.redisUrl);
  const redis = new RedisClient({ host, port });
  let stopping = false;

  const requestStop = () => {
    stopping = true;
  };

  process.once("SIGINT", requestStop);
  process.once("SIGTERM", requestStop);

  try {
    await redis.connect();
    await redis.send(["PING"]);
    if (db !== 0) await redis.send(["SELECT", String(db)]);

    let lastId = await resolveStartId(redis, opts.stream, normalizedSince);
    let printed = 0;
    const blockMs = follow ? 2000 : 0;

    while (!stopping && printed < targetCount) {
      const batch = Math.min(200, targetCount - printed);
      const args = ["XREAD", "COUNT", String(batch)];
      if (blockMs > 0) {
        args.push("BLOCK", String(blockMs));
      }
      args.push("STREAMS", opts.stream, lastId);

      const reply = await redis.send(args);
      if (!reply) {
        if (!follow) break;
        continue;
      }

      for (const [streamName, entries] of reply) {
        if (streamName !== opts.stream || !Array.isArray(entries)) continue;
        for (const [entryId, kv] of entries) {
          lastId = entryId;
          const rawData = extractDataField(kv);
          if (!rawData) continue;

          let obs;
          try {
            obs = JSON.parse(rawData);
          } catch {
            continue;
          }
          if (!obs || typeof obs !== "object") continue;
          if (opts.roomId && obs.room_id !== opts.roomId) continue;

          const ts = typeof obs.ts === "string" ? obs.ts : "-";
          const roomId = typeof obs.room_id === "string" ? obs.room_id : "-";
          const tags = formatList(obs.tags);
          const entities = formatList(obs.entities);
          const hype = formatHype(obs.hype_level);
          const summary = formatSummary(obs.summary);

          console.log(`${ts} ${roomId} hype=${hype} tags=[${tags}] entities=[${entities}] | ${summary}`);
          printed += 1;
          if (printed >= targetCount) break;
        }
      }
    }
  } finally {
    await redis.quit();
  }
};

main().catch((err) => {
  console.error(err && err.stack ? err.stack : String(err));
  process.exitCode = 1;
});
