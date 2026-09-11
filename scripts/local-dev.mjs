#!/usr/bin/env node

import { createInterface } from "node:readline";
import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const API_DIR = path.join(ROOT, "apps", "api");
const WEB_DIR = path.join(ROOT, "apps", "web");
const ENV_FILE = path.join(ROOT, ".env");

const PNPM = process.platform === "win32" ? "pnpm.cmd" : "pnpm";
const DOCKER = "docker";
const UV = "uv";

function log(prefix, message) {
  process.stdout.write(`[${prefix}] ${message}\n`);
}

function errorMessage(error) {
  return error instanceof Error ? error.message : String(error);
}

function compactOutput(value) {
  return String(value || "")
    .trim()
    .replace(/\s+/g, " ")
    .slice(0, 280);
}

function assertCommand(command, label) {
  const result = spawnSync(command, ["--version"], {
    cwd: ROOT,
    stdio: "ignore",
  });
  if (result.error?.code === "ENOENT" || result.status === null) {
    throw new Error(
      `[${label}] ${command} was not found. Install it and try again.`,
    );
  }
  if (result.status !== 0) {
    throw new Error(
      `[${label}] ${command} is installed but could not be executed.`,
    );
  }
}

function requireEnvironment() {
  if (!existsSync(ENV_FILE)) {
    throw new Error(
      "[setup] Missing .env. Run `cp .env.example .env` from the repository root first.",
    );
  }
}

function requirePreparedDependencies() {
  if (!existsSync(path.join(API_DIR, ".venv"))) {
    throw new Error(
      "[setup] apps/api/.venv is missing. Run `pnpm setup` first.",
    );
  }
  if (!existsSync(path.join(WEB_DIR, "node_modules"))) {
    throw new Error(
      "[setup] apps/web/node_modules is missing. Run `pnpm setup` first.",
    );
  }
}

function checkDockerDaemon() {
  const version = spawnSync(DOCKER, ["--version"], {
    cwd: ROOT,
    stdio: "ignore",
  });
  if (version.error?.code === "ENOENT" || version.status === null) {
    throw new Error(
      "[db] Docker CLI was not found. Install Docker Desktop and try again.",
    );
  }
  if (version.status !== 0) {
    throw new Error("[db] Docker CLI is installed but could not be executed.");
  }
  const result = spawnSync(DOCKER, ["info"], {
    cwd: ROOT,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
  if (result.error?.code === "ENOENT" || result.status === null) {
    throw new Error(
      "[db] Docker CLI was not found. Install Docker Desktop and try again.",
    );
  }
  if (result.status !== 0) {
    const detail = compactOutput(result.stderr) || compactOutput(result.stdout);
    throw new Error(
      `[db] Docker is unavailable. Start Docker Desktop and try again.${detail ? ` (${detail})` : ""}`,
    );
  }
}

function prefixStream(stream, prefix) {
  if (!stream) return;
  const reader = createInterface({ input: stream });
  reader.on("line", (line) => log(prefix, line));
}

function runCommand(
  command,
  args,
  { cwd = ROOT, prefix = "cmd", env = process.env } = {},
) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd,
      env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    prefixStream(child.stdout, prefix);
    prefixStream(child.stderr, prefix);
    child.once("error", (error) => reject(error));
    child.once("close", (code, signal) => resolve({ code: code ?? 1, signal }));
  });
}

async function runChecked(command, args, options) {
  const result = await runCommand(command, args, options);
  if (result.code !== 0) {
    const commandText = [command, ...args].join(" ");
    throw new Error(
      `[${options?.prefix || "cmd"}] ${commandText} exited with code ${result.code}.`,
    );
  }
}

function wait(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function waitForPostgres() {
  const deadline = Date.now() + 60_000;
  let lastFailure = "";
  while (Date.now() < deadline) {
    const result = spawnSync(
      DOCKER,
      [
        "compose",
        "exec",
        "-T",
        "postgres",
        "pg_isready",
        "-U",
        "memoryos",
        "-d",
        "memoryos",
      ],
      {
        cwd: ROOT,
        encoding: "utf8",
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
    if (result.status === 0) {
      log("db", "PostgreSQL/pgvector is ready.");
      return;
    }
    lastFailure = compactOutput(result.stderr) || compactOutput(result.stdout);
    await wait(500);
  }
  throw new Error(
    `[db] PostgreSQL did not become ready within 60 seconds.${lastFailure ? ` (${lastFailure})` : ""}`,
  );
}

async function ensurePostgres() {
  checkDockerDaemon();
  await runChecked(DOCKER, ["compose", "up", "-d", "postgres"], {
    prefix: "db",
  });
  await waitForPostgres();
}

async function runMigrations() {
  await runChecked(UV, ["run", "--no-sync", "alembic", "upgrade", "head"], {
    cwd: API_DIR,
    prefix: "db",
  });
}

async function setup() {
  requireEnvironment();
  assertCommand(PNPM, "setup");
  assertCommand(UV, "setup");
  checkDockerDaemon();

  await runChecked(PNPM, ["install", "--frozen-lockfile"], { prefix: "setup" });
  await runChecked(UV, ["sync", "--extra", "dev"], {
    cwd: API_DIR,
    prefix: "setup",
  });
  await ensurePostgres();
  await runMigrations();
  await runChecked(UV, ["run", "--no-sync", "memoryos-seed"], {
    cwd: API_DIR,
    prefix: "setup",
  });
  log(
    "setup",
    "Local environment is ready. Run `pnpm dev` for daily development.",
  );
}

async function prepare() {
  requireEnvironment();
  requirePreparedDependencies();
  assertCommand(PNPM, "dev");
  assertCommand(UV, "dev");

  await ensurePostgres();
  await runMigrations();
  log("dev", "Database is ready. Starting API and web with concurrently.");
}

async function stopDatabase() {
  checkDockerDaemon();
  await runChecked(DOCKER, ["compose", "stop", "postgres"], { prefix: "db" });
  log("db", "PostgreSQL stopped; its volume was preserved.");
}

async function main() {
  const command = process.argv[2] || "dev";
  if (command === "setup") return setup();
  if (command === "prepare") return prepare();
  if (command === "stop") return stopDatabase();
  throw new Error(`Unknown command ${command}. Use setup, prepare, or stop.`);
}

main().catch((error) => {
  process.stderr.write(`${errorMessage(error)}\n`);
  process.exitCode = 1;
});
