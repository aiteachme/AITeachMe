// Prevents an extra console window on Windows in release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::Mutex;

use tauri::Manager;
use tauri_plugin_shell::{process::CommandChild, ShellExt};

#[derive(Default)]
struct BackendState(Mutex<Option<CommandChild>>);

fn backend_port() -> String {
  std::env::var("AITEACHME_BACKEND_PORT")
    .ok()
    .filter(|value| !value.trim().is_empty())
    .or_else(|| option_env!("AITEACHME_TAURI_BACKEND_PORT").map(str::to_owned))
    .unwrap_or_else(|| "9020".to_owned())
}

#[cfg(feature = "local-backend")]
fn start_local_backend(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
  let port = backend_port();
  let backend_data_dir = app.path().app_data_dir()?.join("backend-data");
  std::fs::create_dir_all(&backend_data_dir)?;

  let cors_origins = [
    "http://localhost:5180",
    "http://127.0.0.1:5180",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "tauri://localhost",
    "null",
    "file://",
  ]
  .join(",");

  let (mut receiver, child) = app
    .shell()
    .sidecar("aiteachme-backend")?
    .env("APP_MODE", "local")
    .env("AUTH_ENABLED", "false")
    .env("AITEACHME_ENABLE_BUILTIN_PDF", "false")
    .env("AITEACHME_BACKEND_PORT", &port)
    .env("AITEACHME_DATA_DIR", backend_data_dir.to_string_lossy().to_string())
    .env("AITEACHME_BACKEND_LOG_FILE", backend_data_dir.join("backend.log").to_string_lossy().to_string())
    .env("CORS_ALLOWED_ORIGINS", cors_origins)
    .spawn()?;

  *app.state::<BackendState>().0.lock().expect("backend state poisoned") = Some(child);

  tauri::async_runtime::spawn(async move {
    while let Some(event) = receiver.recv().await {
      match event {
        tauri_plugin_shell::process::CommandEvent::Stdout(line) => {
          println!("[aiteachme-backend] {}", String::from_utf8_lossy(&line));
        }
        tauri_plugin_shell::process::CommandEvent::Stderr(line) => {
          eprintln!("[aiteachme-backend] {}", String::from_utf8_lossy(&line));
        }
        tauri_plugin_shell::process::CommandEvent::Terminated(_) => {
          eprintln!("[aiteachme-backend] terminated");
        }
        _ => {}
      }
    }
  });

  Ok(())
}

#[cfg(not(feature = "local-backend"))]
fn start_local_backend(_app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
  Ok(())
}

fn stop_local_backend(app: &tauri::AppHandle) {
  let state = app.state::<BackendState>();
  let child = {
    state.0.lock().expect("backend state poisoned").take()
  };

  if let Some(child) = child {
    let _ = child.kill();
  }
}

fn main() {
  tauri::Builder::default()
    .plugin(tauri_plugin_shell::init())
    .manage(BackendState::default())
    .setup(|app| {
      start_local_backend(app)?;
      Ok(())
    })
    .on_window_event(|window, event| {
      if matches!(event, tauri::WindowEvent::CloseRequested { .. }) {
        stop_local_backend(window.app_handle());
      }
    })
    .run(tauri::generate_context!())
    .expect("error while running AiTeachMe Tauri application");
}
