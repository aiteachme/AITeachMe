// Prevents an extra console window on Windows in release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
  fs::{self, OpenOptions},
  io::{Read, Write},
  net::{TcpListener, TcpStream},
  path::{Path, PathBuf},
  process::{Child, Command, Stdio},
  sync::Mutex,
  thread,
  time::{Duration, Instant},
};

use tauri::{Manager, WebviewWindowBuilder};

#[derive(Default)]
struct BackendState(Mutex<Option<Child>>);

#[derive(Default)]
struct DesktopRuntime {
  api_base_url: Option<String>,
}

enum BackendStartupStatus {
  Ready,
  Exited(String),
  TimedOut,
}

fn configured_backend_port() -> Option<u16> {
  std::env::var("AITEACHME_BACKEND_PORT")
    .ok()
    .filter(|value| !value.trim().is_empty())
    .and_then(|value| value.parse::<u16>().ok())
    .filter(|port| *port > 0)
}

#[cfg(feature = "local-backend")]
fn allocate_backend_port() -> Result<u16, Box<dyn std::error::Error>> {
  if let Some(port) = configured_backend_port() {
    return Ok(port);
  }

  let listener = TcpListener::bind(("127.0.0.1", 0))?;
  let port = listener.local_addr()?.port();
  drop(listener);
  Ok(port)
}

fn frontend_port() -> String {
  std::env::var("AITEACHME_FRONTEND_PORT")
    .ok()
    .filter(|value| !value.trim().is_empty())
    .unwrap_or_else(|| "5180".to_owned())
}

#[cfg(feature = "local-backend")]
fn check_backend_health(port: u16) -> bool {
  let Ok(mut stream) = TcpStream::connect(("127.0.0.1", port)) else {
    return false;
  };
  let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
  let _ = stream.set_write_timeout(Some(Duration::from_millis(500)));

  let request = b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n";
  if stream.write_all(request).is_err() {
    return false;
  }

  let mut response = [0_u8; 64];
  match stream.read(&mut response) {
    Ok(count) if count > 0 => response.starts_with(b"HTTP/1.1 200") || response.starts_with(b"HTTP/1.0 200"),
    _ => false,
  }
}

#[cfg(feature = "local-backend")]
fn wait_for_backend_ready(child: &mut Child, port: u16, timeout: Duration) -> BackendStartupStatus {
  let deadline = Instant::now() + timeout;
  while Instant::now() < deadline {
    match child.try_wait() {
      Ok(Some(status)) => return BackendStartupStatus::Exited(status.to_string()),
      Ok(None) => {}
      Err(error) => return BackendStartupStatus::Exited(error.to_string()),
    }

    if check_backend_health(port) {
      return BackendStartupStatus::Ready;
    }
    thread::sleep(Duration::from_millis(250));
  }

  BackendStartupStatus::TimedOut
}

#[cfg(feature = "local-backend")]
fn backend_executable_name() -> &'static str {
  if cfg!(windows) {
    "aiteachme-backend.bin"
  } else {
    "aiteachme-backend"
  }
}

#[cfg(feature = "local-backend")]
fn resolve_backend_executable(app: &tauri::App) -> Result<PathBuf, Box<dyn std::error::Error>> {
  let resource_path = app
    .path()
    .resource_dir()?
    .join("backend")
    .join(backend_executable_name());
  if resource_path.exists() {
    return Ok(resource_path);
  }

  if let Some(manifest_dir) = option_env!("CARGO_MANIFEST_DIR") {
    let dev_path = Path::new(manifest_dir)
      .join("resources")
      .join("backend")
      .join(backend_executable_name());
    if dev_path.exists() {
      return Ok(dev_path);
    }
  }

  Err(format!(
    "AiTeachMe backend executable was not found at {}",
    resource_path.display()
  )
  .into())
}

#[cfg(feature = "local-backend")]
fn cleanup_legacy_install_root_files() {
  let current_exe = match std::env::current_exe() {
    Ok(path) => path,
    Err(_) => return,
  };
  let Some(install_dir) = current_exe.parent() else {
    return;
  };

  for file_name in ["aiteachme-backend.exe", "backend.log"] {
    let path = install_dir.join(file_name);
    if path != current_exe {
      let _ = fs::remove_file(path);
    }
  }

  let _ = fs::remove_file(
    install_dir
      .join("resources")
      .join("backend")
      .join("aiteachme-backend.exe"),
  );
}

#[cfg(feature = "local-backend")]
fn directory_is_writable(path: &Path) -> bool {
  if fs::create_dir_all(path).is_err() {
    return false;
  }

  let probe = path.join(format!(".aiteachme-write-test-{}", std::process::id()));
  match OpenOptions::new().write(true).create_new(true).open(&probe) {
    Ok(_) => {
      let _ = fs::remove_file(probe);
      true
    }
    Err(_) => false,
  }
}

#[cfg(feature = "local-backend")]
fn copy_directory_if_missing(source: &Path, target: &Path) -> std::io::Result<()> {
  if !source.exists() || target.exists() {
    return Ok(());
  }

  fs::create_dir_all(target)?;
  for entry in fs::read_dir(source)? {
    let entry = entry?;
    let source_path = entry.path();
    let target_path = target.join(entry.file_name());
    if source_path.is_dir() {
      copy_directory_if_missing(&source_path, &target_path)?;
    } else if source_path.is_file() && !target_path.exists() {
      fs::copy(&source_path, &target_path)?;
    }
  }
  Ok(())
}

#[cfg(feature = "local-backend")]
fn migrate_legacy_backend_data(source: &Path, target: &Path) -> std::io::Result<()> {
  if !source.exists() || source == target {
    return Ok(());
  }

  fs::create_dir_all(target)?;
  for file_name in ["aiteachme.db", "aiteachme.db-wal", "aiteachme.db-shm"] {
    let source_file = source.join(file_name);
    let target_file = target.join(file_name);
    if source_file.exists() && !target_file.exists() {
      fs::copy(source_file, target_file)?;
    }
  }
  copy_directory_if_missing(&source.join("users"), &target.join("users"))?;
  Ok(())
}

#[cfg(feature = "local-backend")]
fn resolve_backend_data_dir(app: &tauri::App) -> Result<PathBuf, Box<dyn std::error::Error>> {
  let app_data_backend_dir = app.path().app_data_dir()?.join("backend-data");

  if !cfg!(debug_assertions) {
    if let Ok(current_exe) = std::env::current_exe() {
      if let Some(install_dir) = current_exe.parent() {
        let install_data_dir = install_dir.join("data");
        if directory_is_writable(&install_data_dir) {
          let _ = migrate_legacy_backend_data(&app_data_backend_dir, &install_data_dir);
          return Ok(install_data_dir);
        }
      }
    }
  }

  fs::create_dir_all(&app_data_backend_dir)?;
  Ok(app_data_backend_dir)
}

#[cfg(feature = "local-backend")]
fn spawn_local_backend_on_port(
  app: &mut tauri::App,
  port: u16,
) -> Result<(Child, PathBuf), Box<dyn std::error::Error>> {
  let port_string = port.to_string();
  let dev_frontend_port = frontend_port();
  let backend_data_dir = resolve_backend_data_dir(app)?;
  fs::create_dir_all(&backend_data_dir)?;
  let backend_log_file = backend_data_dir.join("backend.log");
  let backend_executable = resolve_backend_executable(app)?;

  let cors_origins = vec![
    format!("http://localhost:{dev_frontend_port}"),
    format!("http://127.0.0.1:{dev_frontend_port}"),
    "http://tauri.localhost".to_owned(),
    "https://tauri.localhost".to_owned(),
    "tauri://localhost".to_owned(),
    "null".to_owned(),
    "file://".to_owned(),
  ]
  .join(",");

  let mut log_stream = OpenOptions::new()
    .create(true)
    .append(true)
    .open(&backend_log_file)?;
  writeln!(
    log_stream,
    "\n=== AiTeachMe backend starting: exe={}, port={}, data_dir={} ===",
    backend_executable.display(),
    port_string,
    backend_data_dir.display()
  )?;
  let stderr_stream = log_stream.try_clone()?;

  let child = Command::new(&backend_executable)
    .current_dir(&backend_data_dir)
    .stdin(Stdio::null())
    .stdout(Stdio::from(log_stream))
    .stderr(Stdio::from(stderr_stream))
    .env("APP_MODE", "local")
    .env("AUTH_ENABLED", "false")
    .env("AITEACHME_ENABLE_BUILTIN_PDF", "false")
    .env("STORAGE_BACKEND", "local")
    .env("AITEACHME_BACKEND_PORT", &port_string)
    .env("AITEACHME_DATA_DIR", backend_data_dir.to_string_lossy().to_string())
    .env("AITEACHME_BACKEND_LOG_FILE", backend_log_file.to_string_lossy().to_string())
    .env("CORS_ALLOWED_ORIGINS", cors_origins)
    .spawn()?;

  Ok((child, backend_log_file))
}

#[cfg(feature = "local-backend")]
fn start_local_backend(app: &mut tauri::App) -> Result<DesktopRuntime, Box<dyn std::error::Error>> {
  cleanup_legacy_install_root_files();

  let configured_port = configured_backend_port();
  let max_attempts = if configured_port.is_some() { 1 } else { 8 };
  let startup_timeout = Duration::from_secs(60);
  let mut last_error = String::new();

  for attempt in 1..=max_attempts {
    let port = configured_port.unwrap_or(allocate_backend_port()?);
    let (mut child, backend_log_file) = spawn_local_backend_on_port(app, port)?;

    match wait_for_backend_ready(&mut child, port, startup_timeout) {
      BackendStartupStatus::Ready => {
        *app.state::<BackendState>().0.lock().expect("backend state poisoned") = Some(child);
        return Ok(DesktopRuntime {
          api_base_url: Some(format!("http://127.0.0.1:{port}")),
        });
      }
      BackendStartupStatus::Exited(status) => {
        last_error = format!(
          "backend exited before becoming ready on port {port}: {status}. log={}",
          backend_log_file.display()
        );
      }
      BackendStartupStatus::TimedOut => {
        let _ = child.kill();
        let _ = child.wait();
        return Err(format!(
          "AiTeachMe backend did not become ready within {} seconds on port {port}. log={}",
          startup_timeout.as_secs(),
          backend_log_file.display()
        )
        .into());
      }
    }

    let _ = child.kill();
    let _ = child.wait();
    if attempt < max_attempts {
      thread::sleep(Duration::from_millis(150));
    }
  }

  Err(format!(
    "AiTeachMe backend failed to start after {max_attempts} attempt(s). {last_error}"
  )
  .into())
}

#[cfg(not(feature = "local-backend"))]
fn start_local_backend(_app: &mut tauri::App) -> Result<DesktopRuntime, Box<dyn std::error::Error>> {
  Ok(DesktopRuntime::default())
}

fn js_string_literal(value: &str) -> String {
  let mut escaped = String::with_capacity(value.len() + 2);
  escaped.push('"');
  for ch in value.chars() {
    match ch {
      '\\' => escaped.push_str("\\\\"),
      '"' => escaped.push_str("\\\""),
      '\n' => escaped.push_str("\\n"),
      '\r' => escaped.push_str("\\r"),
      '\t' => escaped.push_str("\\t"),
      '\u{2028}' => escaped.push_str("\\u2028"),
      '\u{2029}' => escaped.push_str("\\u2029"),
      _ => escaped.push(ch),
    }
  }
  escaped.push('"');
  escaped
}

fn build_runtime_init_script(runtime: &DesktopRuntime) -> String {
  let api_base_url = runtime.api_base_url.as_deref().unwrap_or("");
  format!(
    "window.aiteachmeDesktop = Object.assign({{}}, window.aiteachmeDesktop || {{}}, {{ apiBaseUrl: {} }});",
    js_string_literal(api_base_url)
  )
}

fn create_main_window(
  app: &mut tauri::App,
  runtime: &DesktopRuntime,
) -> Result<(), Box<dyn std::error::Error>> {
  let window_config = app
    .config()
    .app
    .windows
    .get(0)
    .cloned()
    .ok_or_else(|| std::io::Error::new(std::io::ErrorKind::NotFound, "missing main window config"))?;

  WebviewWindowBuilder::from_config(app.handle(), &window_config)?
    .initialization_script(build_runtime_init_script(runtime))
    .build()?;
  Ok(())
}

fn stop_local_backend(app: &tauri::AppHandle) {
  let state = app.state::<BackendState>();
  let child = {
    state.0.lock().expect("backend state poisoned").take()
  };

  if let Some(child) = child {
    let mut child = child;
    let _ = child.kill();
    let _ = child.wait();
  }
}

fn main() {
  tauri::Builder::default()
    .manage(BackendState::default())
    .setup(|app| {
      let runtime = start_local_backend(app)?;
      create_main_window(app, &runtime)?;
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
