use serde::Serialize;
use std::fs;
use std::io::{Read, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Manager, RunEvent, WindowEvent};

const SIDECAR_NAME: &str = "forming_grinder_cad_sidecar";

#[derive(Default)]
struct EngineState {
    child: Option<Child>,
    port: Option<u16>,
    error: Option<String>,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct EngineStatus {
    running: bool,
    api_base_url: Option<String>,
    error: Option<String>,
}

impl EngineState {
    fn public_status(&mut self) -> EngineStatus {
        let running = self
            .child
            .as_mut()
            .is_some_and(|child| child.try_wait().ok().flatten().is_none());
        if !running && self.child.is_some() && self.error.is_none() {
            self.error = Some("本地 CAD 引擎已异常退出，可在设置页重新启动。".into());
        }
        EngineStatus {
            running,
            api_base_url: self.port.map(|port| format!("http://127.0.0.1:{port}")),
            error: self.error.clone(),
        }
    }

    fn stop(&mut self) {
        if let Some(mut child) = self.child.take() {
            if let Some(port) = self.port {
                let _ = http_request(port, "POST", "/api/desktop/shutdown");
                let deadline = Instant::now() + Duration::from_secs(5);
                while Instant::now() < deadline {
                    if child.try_wait().ok().flatten().is_some() {
                        break;
                    }
                    std::thread::sleep(Duration::from_millis(100));
                }
            }
            if child.try_wait().ok().flatten().is_none() {
                let _ = child.kill();
            }
            let _ = child.wait();
        }
        self.port = None;
    }
}

#[tauri::command]
fn engine_status(state: tauri::State<'_, Mutex<EngineState>>) -> EngineStatus {
    state.lock().expect("engine state poisoned").public_status()
}

#[tauri::command]
fn restart_engine(
    app: AppHandle,
    state: tauri::State<'_, Mutex<EngineState>>,
) -> Result<EngineStatus, String> {
    let mut engine = state
        .lock()
        .map_err(|_| "本地引擎状态不可用。".to_string())?;
    engine.stop();
    *engine = start_engine(&app)?;
    Ok(engine.public_status())
}

#[tauri::command]
fn prepare_for_update(state: tauri::State<'_, Mutex<EngineState>>) -> Result<(), String> {
    let mut engine = state
        .lock()
        .map_err(|_| "本地引擎状态不可用。".to_string())?;
    engine.stop();
    Ok(())
}

fn sidecar_path(app: &AppHandle) -> Result<PathBuf, String> {
    let executable = if cfg!(target_os = "windows") {
        format!("{SIDECAR_NAME}.exe")
    } else {
        SIDECAR_NAME.to_string()
    };
    let resource = app
        .path()
        .resource_dir()
        .map_err(|error| format!("无法定位应用资源目录：{error}"))?
        .join("sidecar")
        .join(&executable);
    if resource.is_file() {
        return Ok(resource);
    }
    let development = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../dist/forming_grinder_cad_sidecar")
        .join(executable);
    if development.is_file() {
        return Ok(development);
    }
    Err("未找到 Python CAD sidecar，请先运行 PyInstaller 构建。".into())
}

fn start_engine(app: &AppHandle) -> Result<EngineState, String> {
    let executable = sidecar_path(app)?;
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let status_file = std::env::temp_dir().join(format!(
        "forming-grinder-cad-{}-{nonce}.json",
        std::process::id()
    ));
    let _ = fs::remove_file(&status_file);
    let mut command = Command::new(&executable);
    command
        .arg("--port")
        .arg("0")
        .arg("--status-file")
        .arg(&status_file)
        .env("CAD_DESKTOP_MODE", "1")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let mut child = command
        .spawn()
        .map_err(|_| "Python CAD sidecar 无法启动。".to_string())?;
    let deadline = Instant::now() + Duration::from_secs(60);
    while !status_file.is_file() && Instant::now() < deadline {
        if child.try_wait().ok().flatten().is_some() {
            return Err("Python CAD sidecar 在启动前异常退出。".into());
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    let status =
        fs::read_to_string(&status_file).map_err(|_| "sidecar 未返回端口状态文件。".to_string())?;
    let _ = fs::remove_file(&status_file);
    let payload: serde_json::Value =
        serde_json::from_str(&status).map_err(|_| "sidecar 未返回有效的启动协议。".to_string())?;
    let port = payload
        .get("port")
        .and_then(|value| value.as_u64())
        .and_then(|value| u16::try_from(value).ok())
        .ok_or_else(|| "sidecar 未返回有效端口。".to_string())?;
    if let Err(error) = wait_for_health(port, Duration::from_secs(60)) {
        let _ = child.kill();
        let _ = child.wait();
        return Err(error);
    }
    Ok(EngineState {
        child: Some(child),
        port: Some(port),
        error: None,
    })
}

fn wait_for_health(port: u16, timeout: Duration) -> Result<(), String> {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if health_check(port) {
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    Err("Python CAD sidecar 启动超时，/api/health 未就绪。".into())
}

fn health_check(port: u16) -> bool {
    http_request(port, "GET", "/api/health").is_some_and(|response| {
        response.starts_with("HTTP/1.1 200") && response.contains("\"status\":\"ok\"")
    })
}

fn http_request(port: u16, method: &str, path: &str) -> Option<String> {
    let address = ("127.0.0.1", port)
        .to_socket_addrs()
        .ok()
        .and_then(|mut addresses| addresses.next());
    let address = address?;
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(300)) else {
        return None;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    let request = format!("{method} {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");
    stream.write_all(request.as_bytes()).ok()?;
    let mut response = String::new();
    stream.read_to_string(&mut response).ok()?;
    Some(response)
}

pub fn run() {
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(Mutex::new(EngineState::default()))
        .invoke_handler(tauri::generate_handler![
            engine_status,
            restart_engine,
            prepare_for_update
        ])
        .setup(|app| {
            let engine = start_engine(app.handle());
            let state = app.state::<Mutex<EngineState>>();
            let mut current = state.lock().expect("engine state poisoned");
            match engine {
                Ok(started) => *current = started,
                Err(error) => current.error = Some(error),
            }
            Ok(())
        });

    let app = builder
        .build(tauri::generate_context!())
        .expect("failed to build desktop application");
    app.run(|handle, event| match event {
        RunEvent::Exit | RunEvent::ExitRequested { .. } => {
            if let Ok(mut engine) = handle.state::<Mutex<EngineState>>().lock() {
                engine.stop();
            }
        }
        RunEvent::WindowEvent {
            event: WindowEvent::Destroyed,
            ..
        } => {
            if handle.webview_windows().is_empty() {
                if let Ok(mut engine) = handle.state::<Mutex<EngineState>>().lock() {
                    engine.stop();
                }
            }
        }
        _ => {}
    });
}
