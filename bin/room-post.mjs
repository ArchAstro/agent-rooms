#!/usr/bin/env node
// The `room-post` CLI. Published as a bin so `npm i -g @archastro/agent-rooms`
// (or `npx @archastro/agent-rooms-cli`) puts `room-post` on PATH for the
// human bootstrap (init, login) and interactive use. It's a thin exec of
// the bundled Python — the kit stays one auditable stdlib-only file.
import { spawnSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const pkgRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const script = join(pkgRoot, "skills", "team-room", "room_post.py");
const r = spawnSync("python3", [script, ...process.argv.slice(2)], {
  stdio: "inherit",
});
if (r.error) {
  console.error("room-post: python3 is required but was not found on PATH");
  process.exit(127);
}
process.exit(r.status ?? 1);
