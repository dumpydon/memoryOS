import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";

const clientUrl = new URL("./client.ts", import.meta.url).href;
function inspectClient(env) {
  return spawnSync(
    process.execPath,
    [
      "--experimental-strip-types",
      "--input-type=module",
      "-e",
      `const { API_BASE_URL } = await import(${JSON.stringify(clientUrl)}); process.stdout.write(API_BASE_URL);`,
    ],
    { env, encoding: "utf8" },
  );
}

test("production cannot silently call localhost when its public API origin is missing", () => {
  const result = inspectClient({ NODE_ENV: "production" });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /NEXT_PUBLIC_API_BASE_URL must be set/);
});

test("production uses the explicit backend origin", () => {
  const result = inspectClient({
    NODE_ENV: "production",
    NEXT_PUBLIC_API_BASE_URL: "https://api.example.test",
  });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, "https://api.example.test");
});

test("local development retains the default API origin", () => {
  const result = inspectClient({ NODE_ENV: "development" });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, "http://127.0.0.1:8000");
});
