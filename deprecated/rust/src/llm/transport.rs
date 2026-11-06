use super::Cancellation;
use crate::{Error, Result};
use std::{
    io::{BufRead, BufReader, Read, Write},
    process::{Child, Command, Stdio},
    sync::mpsc,
    thread,
    time::Duration,
};

/// Deliberately has no Debug implementation: headers may contain credentials.
pub struct HttpRequest {
    pub url: String,
    pub bearer: String,
    pub body: Vec<u8>,
    pub timeout_ms: u64,
}
pub enum TransportEvent {
    Headers { status: u16, content_type: String },
    Data(Vec<u8>),
}
pub trait HttpTransport: Send + Sync {
    fn post(
        &self,
        request: &HttpRequest,
        cancellation: &Cancellation,
        receive: &mut dyn FnMut(TransportEvent) -> Result<()>,
    ) -> Result<()>;
}

pub struct CurlTransport;
struct Process(Child);
impl Drop for Process {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn quoted(value: &str) -> String {
    format!(
        "\"{}\"",
        value
            .replace('\\', "\\\\")
            .replace('"', "\\\"")
            .replace('\n', "\\n")
            .replace('\r', "\\r")
            .replace('\t', "\\t")
    )
}

impl HttpTransport for CurlTransport {
    fn post(
        &self,
        request: &HttpRequest,
        cancellation: &Cancellation,
        receive: &mut dyn FnMut(TransportEvent) -> Result<()>,
    ) -> Result<()> {
        post_with_program(std::ffi::OsStr::new("curl"), request, cancellation, receive)
    }
}

fn post_with_program(
    program: &std::ffi::OsStr,
    request: &HttpRequest,
    cancellation: &Cancellation,
    receive: &mut dyn FnMut(TransportEvent) -> Result<()>,
) -> Result<()> {
    cancellation.check()?;
    if request.bearer.chars().any(char::is_control) {
        return Err(Error::invalid("Invalid credential"));
    }
    if request.body.len() > 8 * 1024 * 1024 {
        return Err(Error::invalid("Model request exceeds 8 MiB"));
    }
    let mut process = Process(
        Command::new(program)
            .args([
                "--disable",
                "--config",
                "-",
                "--silent",
                "--no-buffer",
                "--include",
                "--suppress-connect-headers",
                "--http1.1",
                "--proto",
                "=https,http",
                "--connect-timeout",
                "10",
            ])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| {
                Error::new(
                    "TRANSPORT_ERROR",
                    "Could not start curl; install curl for API requests",
                )
            })?,
    );
    // Both body and credentials travel over stdin, never argv or temporary files.
    let body = std::str::from_utf8(&request.body)
        .map_err(|_| Error::invalid("Request must be UTF-8 JSON"))?;
    let config = format!(
        "url = {}\nheader = {}\nheader = \"Content-Type: application/json\"\nheader = \"Accept: text/event-stream\"\nheader = \"Expect:\"\ndata-binary = {}\nmax-time = {:.3}\n",
        quoted(&request.url),
        quoted(&format!("Authorization: Bearer {}", request.bearer)),
        quoted(body),
        request.timeout_ms as f64 / 1000.0
    );
    process
        .0
        .stdin
        .take()
        .unwrap()
        .write_all(config.as_bytes())?;
    let stdout = process.0.stdout.take().unwrap();
    let (sender, receiver) = mpsc::sync_channel(8);
    let reader = thread::spawn(move || {
        let result = read_response(stdout, &sender);
        let _ = sender.send(result.map(|_| None));
    });
    let result = (|| {
        loop {
            cancellation.check()?;
            match receiver.recv_timeout(Duration::from_millis(40)) {
                Ok(Ok(Some(event))) => receive(event)?,
                Ok(Ok(None)) => break,
                Ok(Err(error)) => return Err(error),
                Err(mpsc::RecvTimeoutError::Timeout) => continue,
                Err(_) => {
                    return Err(Error::new(
                        "TRANSPORT_ERROR",
                        "HTTP reader stopped unexpectedly",
                    ));
                }
            }
        }
        let status = process.0.wait()?;
        match status.code() {
            Some(0) => Ok(()),
            Some(28) => Err(Error::new("TIMEOUT", "Model request timed out").retryable()),
            _ => Err(Error::new(
                "TRANSPORT_ERROR",
                "HTTP connection failed or ended unexpectedly",
            )
            .retryable()),
        }
    })();
    // Drop receiver before joining: the reader may be blocked by backpressure.
    drop(receiver);
    drop(process);
    let _ = reader.join();
    result
}

type Packet = Result<Option<TransportEvent>>;
fn read_response(stdout: impl Read, sender: &mpsc::SyncSender<Packet>) -> Result<()> {
    let mut reader = BufReader::new(stdout);
    let mut header_bytes = 0;
    loop {
        let mut status_line = String::new();
        reader.by_ref().take(8193).read_line(&mut status_line)?;
        // curl may fail (including timeout) before receiving any headers. Let
        // the caller inspect its exit status rather than masking that error.
        if status_line.is_empty() {
            return Ok(());
        }
        let status: u16 = status_line
            .split_whitespace()
            .nth(1)
            .and_then(|s| s.parse().ok())
            .ok_or_else(|| {
                Error::new(
                    "TRANSPORT_ERROR",
                    "HTTP response headers missing or invalid",
                )
            })?;
        let mut content_type = String::new();
        loop {
            let mut line = String::new();
            let count = reader.by_ref().take(8193).read_line(&mut line)?;
            header_bytes += count;
            if count == 0 || count > 8192 || header_bytes > 65536 {
                return Err(Error::new(
                    "TRANSPORT_ERROR",
                    "Invalid or oversized response headers",
                ));
            }
            if line == "\r\n" || line == "\n" {
                break;
            }
            if let Some((name, value)) = line.split_once(':')
                && name.eq_ignore_ascii_case("content-type")
            {
                content_type = value.trim().into();
            }
        }
        if (100..200).contains(&status) {
            continue;
        }
        sender
            .send(Ok(Some(TransportEvent::Headers {
                status,
                content_type,
            })))
            .map_err(|_| Error::new("DISCONNECTED", "Response receiver closed"))?;
        break;
    }
    let mut buffer = [0; 8192];
    loop {
        let count = reader.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        if sender
            .send(Ok(Some(TransportEvent::Data(buffer[..count].to_vec()))))
            .is_err()
        {
            break;
        }
    }
    Ok(())
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::{fs, os::unix::fs::PermissionsExt, time::Instant};
    struct Program {
        directory: std::path::PathBuf,
        script: std::path::PathBuf,
    }
    impl Program {
        fn new(body: &str) -> Self {
            let directory =
                std::env::temp_dir().join(crate::interaction::new_id("ariadne-curl-test"));
            fs::create_dir(&directory).unwrap();
            let script = directory.join("curl-test");
            fs::write(
                &script,
                format!("#!/usr/bin/python3\nimport sys, json, time\n{body}\n"),
            )
            .unwrap();
            fs::set_permissions(&script, fs::Permissions::from_mode(0o700)).unwrap();
            Self { directory, script }
        }
    }
    impl Drop for Program {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.directory);
        }
    }
    fn request() -> HttpRequest {
        HttpRequest {
            url: "https://openrouter.ai/api/v1/chat/completions".into(),
            bearer: "secret-from-stdin".into(),
            body: br#"{"messages":[{"content":"a \"quote\" and \n newline"}]}"#.to_vec(),
            timeout_ms: 1000,
        }
    }
    #[test]
    fn subprocess_receives_secrets_and_escaped_json_only_over_stdin() {
        let program = Program::new(
            r#"config=sys.stdin.read()
assert not any('secret-from-stdin' in arg for arg in sys.argv)
assert 'Authorization: Bearer secret-from-stdin' in config
body=[line.split(' = ',1)[1] for line in config.splitlines() if line.startswith('data-binary = ')][0]
decoded=json.loads(body)
assert json.loads(decoded)['messages'][0]['content']=='a "quote" and \n newline'
sys.stdout.write('HTTP/1.1 100 Continue\r\n\r\nHTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n\r\ndata: [DONE]\n\n')
sys.stdout.flush()"#,
        );
        let mut data = vec![];
        let mut status = 0;
        post_with_program(
            program.script.as_os_str(),
            &request(),
            &Cancellation::default(),
            &mut |event| {
                match event {
                    TransportEvent::Headers { status: s, .. } => status = s,
                    TransportEvent::Data(bytes) => data.extend(bytes),
                }
                Ok(())
            },
        )
        .unwrap();
        assert_eq!(status, 200);
        assert_eq!(data, b"data: [DONE]\n\n");
    }
    #[test]
    fn cancellation_kills_and_reaps_a_stalled_subprocess_without_sockets() {
        let program = Program::new(
            "sys.stdin.read()\nsys.stdout.write('HTTP/1.1 200 OK\\r\\nContent-Type: text/event-stream\\r\\n\\r\\n')\nsys.stdout.flush()\ntime.sleep(30)",
        );
        let cancel = Cancellation::default();
        let worker_cancel = cancel.clone();
        let script = program.script.clone();
        let (ready, started) = mpsc::channel();
        let worker = thread::spawn(move || {
            post_with_program(
                script.as_os_str(),
                &request(),
                &worker_cancel,
                &mut |event| {
                    if matches!(event, TransportEvent::Headers { .. }) {
                        ready.send(()).unwrap();
                    }
                    Ok(())
                },
            )
        });
        started.recv_timeout(Duration::from_secs(3)).unwrap();
        let before = Instant::now();
        cancel.cancel();
        assert_eq!(worker.join().unwrap().unwrap_err().code, "CANCELLED");
        assert!(before.elapsed() < Duration::from_secs(2));
    }
    #[test]
    fn curl_failure_before_headers_retains_timeout_and_transport_error_categories() {
        for (status, code) in [(28, "TIMEOUT"), (6, "TRANSPORT_ERROR")] {
            let program = Program::new(&format!("sys.stdin.read()\nsys.exit({status})"));
            let error = post_with_program(
                program.script.as_os_str(),
                &request(),
                &Cancellation::default(),
                &mut |_| Ok(()),
            )
            .unwrap_err();
            assert_eq!(error.code, code);
            assert!(error.retryable);
        }
    }
}
