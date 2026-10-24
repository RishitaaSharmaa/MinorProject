// Runs the DecisionWatch backend inside the browser with Pyodide (Python compiled to WebAssembly).
// Everything here is environment-agnostic: the page and the Node verification script pass in how
// to load Pyodide, read bundled files and persist the database, so the same code is tested in both.

const DB_PATH = "/tmp/dw.db";
const PYODIDE_PACKAGES = ["micropip", "sqlalchemy", "pydantic", "sqlite3", "anyio"];

function writeTree(py, files) {
  const made = new Set();
  for (const [path, text] of Object.entries(files)) {
    const parts = `/engine/${path}`.split("/");
    for (let i = 2; i < parts.length; i += 1) {
      const dir = parts.slice(0, i).join("/");
      if (!made.has(dir)) {
        try { py.FS.mkdir(dir); } catch { /* already exists */ }
        made.add(dir);
      }
    }
    py.FS.writeFile(`/engine/${path}`, text);
  }
}

export async function createEngine({ loadPyodide, indexURL, readJson, readBinary, storage, onStatus = () => {} }) {
  onStatus("Starting the Python runtime…");
  const py = await loadPyodide({ indexURL });
  await py.loadPackage(PYODIDE_PACKAGES);

  onStatus("Installing libraries…");
  const wheels = await readJson("wheels/wheels.json");
  for (const name of wheels) py.FS.writeFile(`/tmp/${name}`, await readBinary(`wheels/${name}`));
  py.globals.set("wheel_paths", wheels.map((name) => `emfs:/tmp/${name}`));
  await py.runPythonAsync("import micropip\nawait micropip.install(wheel_paths.to_py(), deps=False)");

  onStatus("Loading DecisionWatch…");
  const source = await readJson("src.json");
  writeTree(py, source.files);
  const saved = await storage.load();
  if (saved) py.FS.writeFile(DB_PATH, saved);
  py.runPython(`
import os, sys
os.environ["DATABASE_URL"] = "sqlite:///${DB_PATH}"
os.environ["LOCAL_MODE"] = "true"
os.environ["GROQ_API_KEY"] = ""
sys.path.insert(0, "/engine")
import app.local as _local
_local.init()
`);
  const local = py.pyimport("app.local");

  let pending = Promise.resolve();
  const snapshot = () => {
    pending = pending.then(() => storage.save(py.FS.readFile(DB_PATH))).catch(() => {});
    return pending;
  };

  onStatus("");
  return {
    // Mirrors fetch(): resolves to { status, body } for any API path, entirely in-process.
    async request(method, target, body) {
      const raw = await local.handle(method, target, body ?? null);
      const result = JSON.parse(raw);
      if (method.toUpperCase() !== "GET") await snapshot();
      return result;
    },
    snapshot,
  };
}
