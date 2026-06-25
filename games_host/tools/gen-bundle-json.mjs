#!/usr/bin/env node
// Generate bundle.json (the file list the app downloads for offline play) for
// each game version folder. Run from games_host/:
//
//   node tools/gen-bundle-json.mjs            # all games/*/*/
//   node tools/gen-bundle-json.mjs games/quiz-rush/1
//
// CI should run this before `aws s3 sync` so every bundle ships its manifest.
import { readdirSync, statSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";

function listFiles(dir, root = dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    if (name === "bundle.json") continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...listFiles(p, root));
    else out.push(relative(root, p).split("\\").join("/"));
  }
  return out.sort();
}

function targets(argv) {
  if (argv.length) return argv;
  // default: every games/<slug>/<version>/ that has an index.html
  const found = [];
  for (const slug of readdirSync("games")) {
    const slugDir = join("games", slug);
    if (!statSync(slugDir).isDirectory()) continue;
    for (const ver of readdirSync(slugDir)) {
      const verDir = join(slugDir, ver);
      if (statSync(verDir).isDirectory()) found.push(verDir);
    }
  }
  return found;
}

for (const dir of targets(process.argv.slice(2))) {
  const files = listFiles(dir);
  if (!files.includes("index.html")) {
    console.error(`! ${dir}: no index.html, skipping`);
    continue;
  }
  writeFileSync(join(dir, "bundle.json"), JSON.stringify({ files }, null, 2) + "\n");
  console.log(`✓ ${dir}/bundle.json (${files.length} file${files.length === 1 ? "" : "s"})`);
}
