// CYR@ desktop shell (Tauri 2).
//
// Launches the local agent backend as a sidecar process bound
// to 127.0.0.1 only, then opens the CYR@ console. The sidecar
// is killed on app exit (no orphan processes). Loopback-only.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::{Command, Child};
use std::sync::Mutex;

static SIDECAR: Mutex<Option<Child>> = Mutex::new(None);

fn sidecar_workspace() -> String {
    if let Ok(root) = std::env::var("VERITAS_ENV_ROOT") {
        return root;
    }
    let base = std::env::var("APPDATA")
        .map(|a| std::path::PathBuf::from(a)
             .join("cyr")
             .join("workspace"))
        .unwrap_or_else(|_| {
            std::path::PathBuf::from("workspace") });
    base.to_string_lossy().to_string()
}

fn spawn_sidecar() {
    let exe_dir = match std::env::current_exe() {
        Ok(p) => match p.parent() {
            Some(d) => d.to_path_buf(),
            None => return,
        },
        Err(_) => return,
    };
    let mut found: Option<std::path::PathBuf> = None;
    if let Ok(entries) = std::fs::read_dir(&exe_dir) {
        for e in entries.flatten() {
            let name = e.file_name().to_string_lossy().to_string();
            if name.starts_with("veritas-backend") && name.ends_with(".exe") {
                found = Some(e.path());
                break;
            }
        }
    }
    let path = match found {
        Some(p) => p,
        None => {
            eprintln!("sidecar not found next to exe; \
                       run `python -m environment.server` in dev");
            return;
        }
    };
    match Command::new(&path)
        .env("VERITAS_ENV_ROOT", sidecar_workspace())
        .spawn() {
        Ok(child) => {
            if let Ok(mut guard) = SIDECAR.lock() {
                *guard = Some(child);
            }
        }
        Err(e) => eprintln!("sidecar spawn failed: {}", e),
    }
}

fn kill_sidecar() {
    if let Ok(mut guard) = SIDECAR.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
        }
    }
}

fn main() {
    spawn_sidecar();
    tauri::Builder::default()
        .build(tauri::generate_context!())
        .expect("error while running CYR@")
        .run(|_app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                kill_sidecar();
            }
        });
}