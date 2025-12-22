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
  persona: path.join(repoRoot, "configs/schemas/persona.schema.json"),
  room: path.join(repoRoot, "configs/schemas/room.schema.json"),
  moderation: path.join(repoRoot, "configs/schemas/moderation.schema.json"),
  observation_context: path.join(repoRoot, "configs/schemas/observation_context.schema.json"),
};

const fixtureMap = {
  persona: [{ directory: path.join(repoRoot, "configs/personas"), expectValid: true }],
  room: [{ directory: path.join(repoRoot, "configs/rooms"), expectValid: true }],
  moderation: [{ directory: path.join(repoRoot, "configs/moderation"), expectValid: true }],
  observation_context: [
    { directory: path.join(repoRoot, "configs/observation_context"), expectValid: true },
  ],
};

const parseArgs = () => {
  const args = process.argv.slice(2);
  const options = { only: null };
  for (let i = 0; i < args.length; i += 1) {
    if (args[i] === "--only" && args[i + 1]) {
      options.only = args[i + 1];
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

const validateFixtureFile = async (filePath, validator, expectValid, ajv) => {
  try {
    const data = await loadJson(filePath);
    const isValid = validator(data);
    if (isValid && expectValid) {
      console.log(`  [OK] ${filePath}`);
      return { passed: 1, failed: 0 };
    }
    if (!isValid && !expectValid) {
      console.log(
        `  [OK] ${filePath}: correctly failed validation (${ajv.errorsText(validator.errors)})`
      );
      return { passed: 1, failed: 0 };
    }
    if (isValid && !expectValid) {
      console.error(`  [FAIL] ${filePath}: expected failure but validation succeeded`);
      return { passed: 0, failed: 1 };
    }
    console.error(
      `  [FAIL] ${filePath}: validation failed (${ajv.errorsText(validator.errors)})`
    );
    return { passed: 0, failed: 1 };
  } catch (error) {
    console.error(`  [FAIL] ${filePath}: unable to validate (${error.message})`);
    return { passed: 0, failed: 1 };
  }
};

const validateFixtureDir = async (name, { directory, expectValid }, validator, ajv) => {
  let passed = 0;
  let failed = 0;
  const files = await listJsonFiles(directory);
  const label = expectValid ? "valid" : "invalid";

  if (files.length === 0) {
    console.warn(`[WARN] No ${label} fixtures found for ${name}: ${directory}`);
    return { passed, failed };
  }

  console.log(`Validating ${label} fixtures for ${name}: ${directory}`);
  for (const filePath of files) {
    const result = await validateFixtureFile(filePath, validator, expectValid, ajv);
    passed += result.passed;
    failed += result.failed;
  }

  return { passed, failed };
};

const main = async () => {
  const { only } = parseArgs();
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

    const validator = ajv.compile(schema);
    const fixtureConfigs = fixtureMap[name] ?? [];
    for (const fixtureConfig of fixtureConfigs) {
      const { passed, failed } = await validateFixtureDir(
        name,
        fixtureConfig,
        validator,
        ajv
      );
      totalPassed += passed;
      totalFailed += failed;
    }
  }

  console.log("\nSummary:");
  console.log(`  Passed: ${totalPassed}`);
  console.log(`  Failed: ${totalFailed}`);

  if (totalFailed > 0) {
    process.exitCode = 1;
  }
};

main();
