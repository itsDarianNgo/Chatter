#!/usr/bin/env node
import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Ajv from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..", "..");

const schemaMap = {
  StreamContext: path.join(
    repoRoot,
    "packages/protocol/jsonschema/stream_context.schema.json"
  ),
  ChatMessage: path.join(
    repoRoot,
    "packages/protocol/jsonschema/chat_message.schema.json"
  ),
  TrendsSnapshot: path.join(
    repoRoot,
    "packages/protocol/jsonschema/trends_snapshot.schema.json"
  ),
};

const parseArgs = () => {
  const args = process.argv.slice(2);
  const options = { version: "1.0.0", only: null };
  for (let i = 0; i < args.length; i += 1) {
    if (args[i] === "--only" && args[i + 1]) {
      options.only = args[i + 1];
      i += 1;
    } else if (args[i] === "--version" && args[i + 1]) {
      options.version = args[i + 1];
      i += 1;
    }
  }
  return options;
};

const loadJson = async (filePath) => {
  const content = await fs.readFile(filePath, "utf-8");
  return JSON.parse(content);
};

const listJsonFiles = async (directory) => {
  const entries = await fs.readdir(directory).catch(() => []);
  return entries
    .filter((entry) => entry.endsWith(".json"))
    .sort()
    .map((entry) => path.join(directory, entry));
};

const validateSchema = async (name, schemaPath, ajv) => {
  console.log(`Checking schema for ${name}: ${schemaPath}`);
  try {
    const schema = await loadJson(schemaPath);
    ajv.compile(schema);
    console.log("  [OK] Schema is valid and compiled");
    return schema;
  } catch (error) {
    console.error(`  [FAIL] Schema error for ${name}: ${error.message}`);
    return null;
  }
};

const validateFixtures = async (name, version, schema, ajv) => {
  const validator = ajv.compile(schema);
  const baseDir = path.join(repoRoot, "data/schemas", name, version);
  const validDir = path.join(baseDir, "valid");
  const invalidDir = path.join(baseDir, "invalid");

  let passed = 0;
  let failed = 0;

  const validDirExists = await fs
    .access(baseDir)
    .then(() => true)
    .catch(() => false);

  if (!validDirExists) {
    console.warn(
      `[WARN] Fixture directory missing for ${name} ${version}: ${baseDir}`
    );
    return { passed, failed };
  }

  const scenarios = [
    { label: "valid", directory: validDir, expectValid: true },
    { label: "invalid", directory: invalidDir, expectValid: false },
  ];

  for (const { label, directory, expectValid } of scenarios) {
    const files = await listJsonFiles(directory);
    if (files.length === 0) {
      console.warn(
        `[WARN] ${label} fixtures missing or empty for ${name} ${version}: ${directory}`
      );
      continue;
    }

    console.log(`Validating ${label} fixtures for ${name} ${version}: ${directory}`);
    for (const filePath of files) {
      try {
        const data = await loadJson(filePath);
        const isValid = validator(data);
        if (isValid && expectValid) {
          console.log(`  [OK] ${filePath}`);
          passed += 1;
        } else if (!isValid && !expectValid) {
          console.log(
            `  [OK] ${filePath}: correctly failed validation (${ajv.errorsText(validator.errors)})`
          );
          passed += 1;
        } else if (isValid && !expectValid) {
          console.error(
            `  [FAIL] ${filePath}: expected failure but validation succeeded`
          );
          failed += 1;
        } else {
          console.error(
            `  [FAIL] ${filePath}: validation failed (${ajv.errorsText(validator.errors)})`
          );
          failed += 1;
        }
      } catch (error) {
        console.error(`  [FAIL] ${filePath}: unable to validate (${error.message})`);
        failed += 1;
      }
    }
  }

  return { passed, failed };
};

const main = async () => {
  const { only, version } = parseArgs();
  const ajv = new Ajv({ strict: false });
  addFormats(ajv);

  const targets = only ? [only] : Object.keys(schemaMap).sort();

  let totalPassed = 0;
  let totalFailed = 0;

  for (const name of targets) {
    const schemaPath = schemaMap[name];
    if (!schemaPath) {
      console.error(`[FAIL] Unknown schema: ${name}`);
      totalFailed += 1;
      continue;
    }
    const schemaExists = await fs
      .access(schemaPath)
      .then(() => true)
      .catch(() => false);

    if (!schemaExists) {
      console.error(`[FAIL] Missing schema for ${name}: ${schemaPath}`);
      totalFailed += 1;
      continue;
    }

    const schema = await validateSchema(name, schemaPath, ajv);
    if (!schema) {
      totalFailed += 1;
      continue;
    }

    const { passed, failed } = await validateFixtures(name, version, schema, ajv);
    totalPassed += passed;
    totalFailed += failed;
  }

  console.log("\nSummary:");
  console.log(`  Passed: ${totalPassed}`);
  console.log(`  Failed: ${totalFailed}`);

  if (totalFailed > 0) {
    process.exitCode = 1;
  }
};

main();
