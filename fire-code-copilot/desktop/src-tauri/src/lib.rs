//! Fire Code CoPilot desktop wrapper.
//!
//! This is a thin native shell around the same React UI you get in the browser. Its one
//! extra job is to **manage the Python backend for you**: on launch it starts the FastAPI
//! server (uvicorn on :8000) as a child process, and on quit it shuts that process down —
//! so "open the app" is the whole workflow, no separate terminal.
//!
//! Everything stays local. The wrapper spawns a process on your own machine and loads a
//! localhost URL; nothing about this shell sends data anywhere.
//!
//! Escape hatches (env vars):
//!   FCC_ROOT=/path/to/fire-code-copilot   pin the project root (otherwise auto-detected)
//!   FCC_API_PORT=8000                      backend port (must match the UI's VITE_API_BASE)
//!   FCC_NO_BACKEND=1                       don't spawn the backend (you run launch.sh yourself)

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

/// Resolve the project root: FCC_ROOT wins; otherwise search up from the current dir and
/// from the executable's location (covers both `tauri dev` and a bundled `.app`).
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

/// Start the FastAPI backend as a child process. Prefers the project venv's uvicorn; falls
/// back to `python3 -m uvicorn`. Returns None if we can't find the repo or shouldn't spawn.
fn spawn_backend(port: &str) -> Option<Child> {
    if std::env::var("FCC_NO_BACKEND").is_ok() {
        eprintln!("[fcc] FCC_NO_BACKEND set — not spawning the backend.");
        return None;
    }
    let root = match resolve_root() {
        Some(r) => r,
        None => {
            eprintln!("[fcc] Could not locate the project root (no backend/app/main.py found). \
                       Set FCC_ROOT, or start the backend yourself and set FCC_NO_BACKEND=1.");
            return None;
        }
    };

    // Prefer the project venv's uvicorn so we get the exact pinned dependencies.
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
        // Fall back to a system python. `launch.sh` normally creates the venv on first run,
        // so this path mostly matters if the user manages their own environment.
        eprintln!("[fcc] venv uvicorn not found at {venv_uvicorn:?}; falling back to `python3 -m uvicorn`.");
        let mut c = Command::new("python3");
        c.args(["-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--port", port]);
        c
    };

    cmd.current_dir(&root);
    eprintln!("[fcc] Starting backend on :{port} (cwd {root:?}) …");
    match cmd.spawn() {
        Ok(child) => Some(child),
        Err(e) => {
            eprintln!("[fcc] Failed to start the backend: {e}. \
                       Run `bash scripts/launch.sh` once to create the venv, then reopen the app.");
            None
        }
    }
}

pub fn run() {
    let port = std::env::var("FCC_API_PORT").unwrap_or_else(|_| "8000".to_string());

    tauri::Builder::default()
        .manage(Backend::default())
        .setup(move |app| {
            let child = spawn_backend(&port);
            *app.state::<Backend>().0.lock().unwrap() = child;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the Fire Code CoPilot desktop app")
        .run(|app_handle, event| {
            // When the app is exiting, make sure the backend child goes with it — no orphaned
            // uvicorn left holding :8000 after the window closes.
            if let RunEvent::Exit = event {
                if let Some(mut child) = app_handle.state::<Backend>().0.lock().unwrap().take() {
                    eprintln!("[fcc] Stopping backend (pid {}) …", child.id());
                    let _ = child.kill();
                    let _ = child.wait();
                }
            }
        });
}
