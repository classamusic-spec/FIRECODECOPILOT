//! Fire Code CoPilot desktop wrapper.
//!
//! A thin native shell around the same React UI you get in the browser. Its job is to **run the
//! backend for you** so "open the app" is the whole workflow.
//!
//! Two ways it finds a backend, in order:
//!   1. **Standalone (shipped .app):** a frozen, self-contained backend bundled as a resource at
//!      `<resources>/fcc-backend/fcc-backend`. No repo or venv required. All mutable data is
//!      written to the OS app-data dir (macOS: ~/Library/Application Support/…), never inside the
//!      read-only, code-signed bundle.
//!   2. **Dev fallback:** if no frozen backend is bundled (e.g. `npm run dev` before building the
//!      sidecar), it starts `backend/.venv/bin/uvicorn` from the repo, auto-detecting the root.
//!
//! Everything stays local: the shell spawns a process on your own machine and loads a localhost
//! URL. Nothing about this wrapper sends data anywhere.
//!
//! Escape hatches (env vars):
//!   FCC_ROOT=/path/to/fire-code-copilot   pin the repo root for the dev fallback
//!   FCC_API_PORT=8001                      backend port (must match the UI's VITE_API_BASE)
//!   FCC_CODE_BOOKS_DIR=/path/to/pdfs       where the standalone app reads your code books
//!   FCC_NO_BACKEND=1                       don't spawn a backend (you run one yourself)

use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::Mutex;

use tauri::{Manager, RunEvent};

/// Holds the backend child process so we can terminate it when the app exits.
#[derive(Default)]
struct Backend(Mutex<Option<Child>>);

/// Walk up from `start` looking for the repo marker `backend/app/main.py`.
fn find_root_from(start: &Path) -> Option<PathBuf> {
    let mut dir = Some(start);
    while let Some(d) = dir {
        if d.join("backend").join("app").join("main.py").is_file() {
            return Some(d.to_path_buf());
        }
        dir = d.parent();
    }
    None
}

/// Resolve the repo root for the dev fallback: FCC_ROOT wins; else search up from the current dir
/// and from the executable's location.
fn resolve_root() -> Option<PathBuf> {
    if let Ok(explicit) = std::env::var("FCC_ROOT") {
        let p = PathBuf::from(explicit);
        if p.join("backend").join("app").join("main.py").is_file() {
            return Some(p);
        }
        eprintln!("[fcc] FCC_ROOT set but no backend/app/main.py under it: {p:?}");
    }
    if let Ok(cwd) = std::env::current_dir() {
        if let Some(r) = find_root_from(&cwd) {
            return Some(r);
        }
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(r) = exe.parent().and_then(find_root_from) {
            return Some(r);
        }
    }
    None
}

/// Parse a simple KEY=VALUE .env file (ignoring blanks/comments) into (key, value) pairs, so the
/// standalone app can be configured by dropping a `.env` next to its data dir — no rebuild needed.
fn read_env_file(path: &Path) -> Vec<(String, String)> {
    let mut out = Vec::new();
    let Ok(text) = std::fs::read_to_string(path) else { return out };
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if let Some((k, v)) = line.split_once('=') {
            let v = v.trim().trim_matches('"').trim_matches('\'');
            out.push((k.trim().to_string(), v.to_string()));
        }
    }
    out
}

/// Point the backend's mutable paths at a writable app-data dir and apply the user's `.env`.
/// Nothing is written inside the bundle; the vector store, feedback DB, and ingested data all live
/// under the OS app-data directory.
fn apply_standalone_env(cmd: &mut Command, data_root: &Path) {
    let data = data_root.join("data");
    let books = std::env::var("FCC_CODE_BOOKS_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| data_root.join("code_books"));
    let _ = std::fs::create_dir_all(&data);
    let _ = std::fs::create_dir_all(&books);

    cmd.env("DATA_DIR", &data);
    cmd.env("CHROMA_DIR", data.join("chroma"));
    cmd.env("FEEDBACK_DB", data.join("feedback.sqlite"));
    cmd.env("CODE_BOOKS_DIR", &books);

    // Prefer a user-supplied code-cycle config dropped alongside the data dir; otherwise the
    // backend uses the copy frozen into the bundle (which falls back to the committed example).
    let cycles = data_root.join("code_cycles.yaml");
    if cycles.is_file() {
        cmd.env("CODE_CYCLES_CONFIG", cycles);
    }

    // Model provider + API keys: read from <app-data>/.env if the user created one.
    for (k, v) in read_env_file(&data_root.join(".env")) {
        cmd.env(k, v);
    }
}

/// Start the backend. Prefers the frozen standalone backend bundled as a resource; falls back to
/// the repo's venv uvicorn for development. Returns None if we shouldn't/can't spawn one.
fn spawn_backend(app: &tauri::App, port: &str) -> Option<Child> {
    if std::env::var("FCC_NO_BACKEND").is_ok() {
        eprintln!("[fcc] FCC_NO_BACKEND set — not spawning a backend.");
        return None;
    }

    // 1) Standalone: the frozen backend bundled into the .app.
    let exe_name = if cfg!(windows) { "fcc-backend.exe" } else { "fcc-backend" };
    if let Ok(res_dir) = app.path().resource_dir() {
        let frozen = res_dir.join("fcc-backend").join(exe_name);
        if frozen.is_file() {
            let data_root = app
                .path()
                .app_data_dir()
                .expect("no OS app-data dir available");
            let _ = std::fs::create_dir_all(&data_root);

            #[cfg(unix)]
            {
                // Resource copying can drop the executable bit; restore it before spawning.
                use std::os::unix::fs::PermissionsExt;
                if let Ok(meta) = std::fs::metadata(&frozen) {
                    let mut perms = meta.permissions();
                    perms.set_mode(perms.mode() | 0o755);
                    let _ = std::fs::set_permissions(&frozen, perms);
                }
            }

            let mut cmd = Command::new(&frozen);
            cmd.arg(port);
            apply_standalone_env(&mut cmd, &data_root);
            eprintln!("[fcc] Starting standalone backend on :{port} (data {data_root:?}) …");
            match cmd.spawn() {
                Ok(child) => return Some(child),
                Err(e) => eprintln!("[fcc] Frozen backend failed to start: {e}; trying dev fallback…"),
            }
        }
    }

    // 2) Dev fallback: the repo venv's uvicorn.
    let root = match resolve_root() {
        Some(r) => r,
        None => {
            eprintln!("[fcc] No bundled backend and no repo found. Set FCC_ROOT, or run \
                       `bash scripts/launch.sh` once, or start the backend yourself with \
                       FCC_NO_BACKEND=1.");
            return None;
        }
    };
    let venv_uvicorn = if cfg!(windows) {
        root.join("backend").join(".venv").join("Scripts").join("uvicorn.exe")
    } else {
        root.join("backend").join(".venv").join("bin").join("uvicorn")
    };
    let mut cmd = if venv_uvicorn.is_file() {
        let mut c = Command::new(&venv_uvicorn);
        c.args(["app.main:app", "--app-dir", "backend", "--port", port]);
        c
    } else {
        eprintln!("[fcc] venv uvicorn not found at {venv_uvicorn:?}; falling back to `python3 -m uvicorn`.");
        let mut c = Command::new("python3");
        c.args(["-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--port", port]);
        c
    };
    cmd.current_dir(&root);
    eprintln!("[fcc] Starting dev backend on :{port} (cwd {root:?}) …");
    match cmd.spawn() {
        Ok(child) => Some(child),
        Err(e) => {
            eprintln!("[fcc] Failed to start the backend: {e}. \
                       Run `bash scripts/launch.sh` once to create the venv, then reopen the app.");
            None
        }
    }
}

/// The workstation defaults to releasing model memory when Fire Code CoPilot quits. Set
/// `FCC_STOP_OMLX_ON_EXIT=0` only when another local workload intentionally owns oMLX.
fn stop_omlx_on_exit(value: Option<&str>) -> bool {
    !matches!(value.map(str::trim), Some("0" | "false" | "False" | "FALSE" | "no" | "No" | "NO"))
}

/// Ask oMLX to stop through its own managed-service command rather than killing a process by
/// port. This releases all loaded weights and avoids touching unrelated local processes.
fn stop_managed_omlx() {
    if !stop_omlx_on_exit(std::env::var("FCC_STOP_OMLX_ON_EXIT").ok().as_deref()) {
        eprintln!("[fcc] FCC_STOP_OMLX_ON_EXIT=0 — leaving oMLX running.");
        return;
    }
    let binary = std::env::var("OMLX_BIN").unwrap_or_else(|_| "omlx".to_string());
    match Command::new(binary).args(["stop", "--timeout", "30"]).output() {
        Ok(output) if output.status.success() => eprintln!("[fcc] Stopped managed oMLX on exit."),
        Ok(output) => eprintln!("[fcc] oMLX stop returned {} on exit.", output.status),
        Err(e) => eprintln!("[fcc] Could not stop oMLX on exit: {e}"),
    }
}

pub fn run() {
    let port = std::env::var("FCC_API_PORT").unwrap_or_else(|_| "8001".to_string());

    tauri::Builder::default()
        .manage(Backend::default())
        .setup(move |app| {
            let child = spawn_backend(app, &port);
            *app.state::<Backend>().0.lock().unwrap() = child;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the Fire Code CoPilot desktop app")
        .run(|app_handle, event| {
            // When the app exits, make sure the backend child goes with it — no orphaned process
            // left holding the port after the window closes.
            if let RunEvent::Exit = event {
                if let Some(mut child) = app_handle.state::<Backend>().0.lock().unwrap().take() {
                    eprintln!("[fcc] Stopping backend (pid {}) …", child.id());
                    let _ = child.kill();
                    let _ = child.wait();
                }
                stop_managed_omlx();
            }
        });
}

#[cfg(test)]
mod tests {
    use super::stop_omlx_on_exit;

    #[test]
    fn model_server_stops_on_quit_unless_explicitly_disabled() {
        assert!(stop_omlx_on_exit(None));
        assert!(stop_omlx_on_exit(Some("true")));
        assert!(!stop_omlx_on_exit(Some("0")));
        assert!(!stop_omlx_on_exit(Some("false")));
    }
}
