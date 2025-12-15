import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Ajv from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..", "..", "..", "..");

const schemaPaths = {
  StreamFrameV1: path.join(
    repoRoot,
    "packages/protocol/jsonschema/stream_frame.v1.schema.json"
  ),
  StreamTranscriptSegmentV1: path.join(
    repoRoot,
    "packages/protocol/jsonschema/stream_transcript_segment.v1.schema.json"
  ),
  StreamObservationV1: path.join(
    repoRoot,
    "packages/protocol/jsonschema/stream_observation.v1.schema.json"
  ),
};

const loadSchema = (schemaPath) =>
  JSON.parse(fs.readFileSync(schemaPath, "utf-8"));

const ajv = new Ajv({ strict: false, allErrors: true });
addFormats(ajv);

const streamFrameSchema = loadSchema(schemaPaths.StreamFrameV1);
const streamTranscriptSegmentSchema = loadSchema(schemaPaths.StreamTranscriptSegmentV1);
const streamObservationSchema = loadSchema(schemaPaths.StreamObservationV1);

export const validateStreamFrameV1 = ajv.compile(streamFrameSchema);
export const validateStreamTranscriptSegmentV1 = ajv.compile(
  streamTranscriptSegmentSchema
);
export const validateStreamObservationV1 = ajv.compile(streamObservationSchema);

export const streamSchemaPaths = schemaPaths;

export const formatAjvErrors = (errors) => ajv.errorsText(errors, { separator: "; " });

