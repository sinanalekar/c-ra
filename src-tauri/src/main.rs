// VERITAS environment desktop shell (Tauri 2).
// The backend is the local Python research server: the shell
// launches it as a sidecar process bound to 127.0.0.1 only -
// no network exposure; the window talks to loopback.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            // sidecar launch of the local backend is configured
            // in tauri.conf.json externalBin at packaging time;
            // in dev the backend runs via
            //   python -m environment.server
            // and the UI proxies /api to 127.0.0.1:8765.
            let _ = app;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running veritas environment");
}
