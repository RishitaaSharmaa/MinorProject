// Assembles the in-browser engine under public/engine/ so the page never fetches code from a
// third party at runtime: the Pyodide runtime and its packages, a few pinned pure-Python wheels
// (checked against PyPI's published hashes) and the backend's own Python source.
import { createHash } from "node:crypto";
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const ui = join(here, "..");
const root = join(ui, "..");
const out = join(ui, "public", "engine");
const pyodideOut = join(out, "pyodide");
const wheelsOut = join(out, "wheels");

const PYODIDE_VERSION = "0.27.7";
const CDN = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
// Packages Pyodide ships itself (the runtime closure is resolved from its lock file).
const PYODIDE_PACKAGES = ["micropip", "sqlalchemy", "pydantic", "sqlite3", "anyio"];
// Pure-Python wheels, pinned to versions compatible with the libraries Pyodide bundles.
const WHEELS = [
  ["fastapi", "0.115.6"],
  ["starlette", "0.41.3"],
  ["pydantic-settings", "2.7.0"],
  ["python-dotenv", "1.0.1"],
];

const sha256 = (buffer) => createHash("sha256").update(buffer).digest("hex");
const ensure = (dir) => mkdirSync(dir, { recursive: true });
const canonical = (name) => name.toLowerCase().replace(/_/g, "-");

async function download(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  return Buffer.from(await response.arrayBuffer());
}

async function preparePyodide() {
  ensure(pyodideOut);
  // The UI package is an ES module; Pyodide's runtime script is not, so Node needs this marker to load it.
  writeFileSync(join(pyodideOut, "package.json"), JSON.stringify({ type: "commonjs" }));
  const dist = join(ui, "node_modules", "pyodide");
  for (const file of ["pyodide.mjs", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"]) {
    copyFileSync(join(dist, file), join(pyodideOut, file));
  }
  const packages = JSON.parse(readFileSync(join(dist, "pyodide-lock.json"), "utf8")).packages;
  const byName = new Map(Object.values(packages).map((p) => [canonical(p.name), p]));
  const wanted = new Map();
  const visit = (name) => {
    const pkg = byName.get(canonical(name));
    if (!pkg || wanted.has(pkg.name)) return;
    wanted.set(pkg.name, pkg);
    pkg.depends.forEach(visit);
  };
  PYODIDE_PACKAGES.forEach(visit);
  for (const pkg of wanted.values()) {
    const target = join(pyodideOut, pkg.file_name);
    if (existsSync(target) && sha256(readFileSync(target)) === pkg.sha256) continue;
    const data = await download(CDN + pkg.file_name);
    if (sha256(data) !== pkg.sha256) throw new Error(`Hash mismatch for ${pkg.file_name}`);
    writeFileSync(target, data);
    console.log("  fetched", pkg.file_name);
  }
}

async function prepareWheels() {
  ensure(wheelsOut);
  const names = [];
  for (const [name, version] of WHEELS) {
    const meta = await (await fetch(`https://pypi.org/pypi/${name}/${version}/json`)).json();
    const wheel = meta.urls.find((u) => u.packagetype === "bdist_wheel" && u.filename.endsWith("-py3-none-any.whl"));
    if (!wheel) throw new Error(`No pure-Python wheel for ${name} ${version}`);
    names.push(wheel.filename);
    const target = join(wheelsOut, wheel.filename);
    if (existsSync(target) && sha256(readFileSync(target)) === wheel.digests.sha256) continue;
    const data = await download(wheel.url);
    if (sha256(data) !== wheel.digests.sha256) throw new Error(`Hash mismatch for ${wheel.filename}`);
    writeFileSync(target, data);
    console.log("  fetched", wheel.filename);
  }
  writeFileSync(join(wheelsOut, "wheels.json"), JSON.stringify(names));
}

function walk(dir) {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (entry === "__pycache__") return [];
    if (statSync(full).isDirectory()) return walk(full);
    return full.endsWith(".py") ? [full] : [];
  });
}

function prepareSource() {
  const files = {};
  for (const folder of ["app", "llm"]) {
    for (const file of walk(join(root, folder))) {
      files[relative(root, file).split("\\").join("/")] = readFileSync(file, "utf8");
    }
  }
  writeFileSync(join(out, "src.json"), JSON.stringify({ files }));
  console.log(`  bundled ${Object.keys(files).length} Python files`);
}

ensure(out);
if (!existsSync(join(root, "app"))) {
  console.log("prepare-engine: backend source not found; skipping the in-browser engine");
  process.exit(0);
}
// The backend source is always refreshed (it changes with the code); the large downloads are cached.
prepareSource();
try {
  await preparePyodide();
  await prepareWheels();
} catch (error) {
  if (existsSync(join(wheelsOut, "wheels.json"))) {
    console.warn(`prepare-engine: could not refresh downloads (${error.message}); using the cached copy`);
  } else {
    console.error(`prepare-engine: ${error.message}`);
    process.exit(1);
  }
}
console.log("prepare-engine: done");
