use crate::{
    Error, Result,
    configuration::ConfigurationStore,
    interaction::CommandKind,
    llm::{CredentialResolver, EnvironmentCredentials},
    orchestrator::Application,
};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    collections::HashMap,
    io::{BufRead, BufReader, Read, Write},
    net::TcpListener,
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
    thread,
    time::Duration,
};

const HTML: &str = include_str!("index.html");
const CSS: &str = include_str!("style.css");
const JS: &str = include_str!("app.js");

pub fn serve(app: Arc<Application>, port: u16) -> Result<()> {
    let listener = TcpListener::bind(("127.0.0.1", port))?;
    println!("Ariadne chat: http://{}", listener.local_addr()?);
    serve_listener(app, listener)
}
pub fn serve_listener(app: Arc<Application>, listener: TcpListener) -> Result<()> {
    let address = listener.local_addr()?;
    if !address.ip().is_loopback() {
        return Err(Error::invalid("Chat UI must listen on loopback"));
    }
    let host = address.to_string();
    let connections = Arc::new(AtomicUsize::new(0));
    for socket in listener.incoming() {
        let mut socket = socket?;
        if connections.fetch_add(1, Ordering::SeqCst) >= 64 {
            connections.fetch_sub(1, Ordering::SeqCst);
            let _=respond(&mut socket,503,"application/json",b"{\"ok\":false,\"error\":{\"code\":\"BUSY\",\"message\":\"Too many connections\"}}");
            continue;
        }
        let app = app.clone();
        let host = host.clone();
        let connections = connections.clone();
        thread::spawn(move || {
            let _ = socket.set_read_timeout(Some(Duration::from_secs(5)));
            let _ = socket.set_write_timeout(Some(Duration::from_secs(10)));
            let result = (|| {
                let request = read_request(&mut socket)?;
                request.validate_origin(&host)?;
                route(&app, &request, &mut socket)
            })();
            if let Err(error) = result {
                let _ = respond(
                    &mut socket,
                    status_for(&error),
                    "application/json",
                    json!({"ok":false,"error":error}).to_string().as_bytes(),
                );
            }
            connections.fetch_sub(1, Ordering::SeqCst);
        });
    }
    Ok(())
}
fn status_for(error: &Error) -> u16 {
    match error.code.as_str() {
        "NOT_FOUND" => 404,
        "FORBIDDEN" => 403,
        "ALREADY_SUBSCRIBED" | "BUSY" | "VERSION_CONFLICT" => 409,
        "IO_ERROR" | "DATABASE_ERROR" => 500,
        _ => 400,
    }
}

struct HttpRequest {
    method: String,
    path: String,
    headers: HashMap<String, String>,
    body: Vec<u8>,
}
impl HttpRequest {
    fn validate_origin(&self, host: &str) -> Result<()> {
        if self.headers.get("host").map(String::as_str) != Some(host) {
            return Err(Error::new("FORBIDDEN", "Unexpected Host header"));
        }
        if self
            .headers
            .get("origin")
            .is_some_and(|origin| origin != &format!("http://{host}"))
        {
            return Err(Error::new(
                "FORBIDDEN",
                "Cross-origin access is not allowed",
            ));
        }
        if self.method == "POST"
            && (self
                .headers
                .get("content-type")
                .and_then(|v| v.split(';').next())
                .map(str::trim)
                != Some("application/json")
                || self.headers.get("x-ariadne-client").map(String::as_str) != Some("ui"))
        {
            return Err(Error::new(
                "FORBIDDEN",
                "POST requests require JSON and X-Ariadne-Client: ui",
            ));
        }
        Ok(())
    }
}
fn read_request(input: impl Read) -> Result<HttpRequest> {
    let mut reader = BufReader::new(input);
    let mut first = String::new();
    reader.by_ref().take(8193).read_line(&mut first)?;
    let parts = first.split_whitespace().collect::<Vec<_>>();
    if parts.len() != 3
        || parts[2] != "HTTP/1.1"
        || !matches!(parts[0], "GET" | "POST")
        || !parts[1].starts_with('/')
        || parts[1].len() > 2048
    {
        return Err(Error::invalid("Invalid HTTP request"));
    }
    let (method, path) = (parts[0].into(), parts[1].into());
    let mut headers = HashMap::new();
    let mut total = first.len();
    loop {
        let mut line = String::new();
        let count = reader.by_ref().take(8193).read_line(&mut line)?;
        total += count;
        if count == 0 || count > 8192 || total > 16384 {
            return Err(Error::invalid("Invalid or oversized HTTP headers"));
        }
        if line == "\r\n" || line == "\n" {
            break;
        }
        let (name, value) = line
            .split_once(':')
            .ok_or_else(|| Error::invalid("Malformed HTTP header"))?;
        if headers
            .insert(name.to_ascii_lowercase(), value.trim().to_string())
            .is_some()
        {
            return Err(Error::invalid("Duplicate HTTP header"));
        }
    }
    if headers.contains_key("transfer-encoding") {
        return Err(Error::invalid("Chunked request bodies are not supported"));
    }
    let length = headers
        .get("content-length")
        .map(|v| v.parse::<usize>())
        .transpose()
        .map_err(|_| Error::invalid("Invalid Content-Length"))?
        .unwrap_or(0);
    if length > 128 * 1024 {
        return Err(Error::invalid("Request body exceeds 128 KiB"));
    }
    let mut body = vec![0; length];
    reader.read_exact(&mut body)?;
    Ok(HttpRequest {
        method,
        path,
        headers,
        body,
    })
}
fn respond(output: &mut impl Write, status: u16, content_type: &str, body: &[u8]) -> Result<()> {
    let reason = match status {
        200 => "OK",
        201 => "Created",
        400 => "Bad Request",
        403 => "Forbidden",
        404 => "Not Found",
        409 => "Conflict",
        503 => "Service Unavailable",
        _ => "Internal Server Error",
    };
    write!(
        output,
        "HTTP/1.1 {status} {reason}\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\nContent-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'\r\nConnection: close\r\n\r\n",
        body.len()
    )?;
    output.write_all(body)?;
    output.flush()?;
    Ok(())
}
fn json_response(output: &mut impl Write, value: Value) -> Result<()> {
    respond(
        output,
        200,
        "application/json",
        json!({"ok":true,"result":value}).to_string().as_bytes(),
    )
}
fn route(app: &Application, request: &HttpRequest, output: &mut impl Write) -> Result<()> {
    match (request.method.as_str(), request.path.as_str()) {
        ("GET", "/") => respond(output, 200, "text/html; charset=utf-8", HTML.as_bytes()),
        ("GET", "/style.css") => respond(output, 200, "text/css; charset=utf-8", CSS.as_bytes()),
        ("GET", "/app.js") => respond(output, 200, "text/javascript; charset=utf-8", JS.as_bytes()),
        ("GET", "/api/status") => {
            let store = ConfigurationStore::open(&app.options.root)?;
            let config = store.load()?.1;
            let profile = config
                .profiles
                .get(&app.options.profile_id)
                .ok_or_else(|| {
                    Error::new(
                        "NOT_FOUND",
                        "Configured orchestrator profile no longer exists",
                    )
                })?;
            let provider = profile
                .provider_id
                .as_ref()
                .and_then(|id| config.providers.get(id));
            let credentials_ready =
                provider.is_some_and(|p| EnvironmentCredentials.resolve(&p.credential_ref).is_ok());
            json_response(
                output,
                json!({"project_id":app.options.project_id,"profile_id":profile.id,"model":profile.model,"provider":provider.map(|p|p.adapter.as_str()),"credentials_ready":credentials_ready}),
            )
        }
        ("GET", "/api/conversations") => json_response(
            output,
            json!(
                app.conversations()?
                    .iter()
                    .map(ConversationView::summary)
                    .collect::<Vec<_>>()
            ),
        ),
        ("POST", "/api/conversations") => {
            let _: Empty = serde_json::from_slice(&request.body)?;
            json_response(output, app.create_conversation()?.view())
        }
        ("GET", "/api/tasks") => json_response(output, app.tasks()?),
        ("POST", "/api/commands") => {
            let command: IncomingCommand = serde_json::from_slice(&request.body)?;
            json_response(
                output,
                json!({"command_id":app.submit(&command.session_id,command.payload)?}),
            )
        }
        ("GET", path) if path.starts_with("/api/conversations/") => {
            json_response(output, app.conversation(&path[19..])?.view())
        }
        ("GET", path) if path.starts_with("/api/events/") => {
            let session = &path[12..];
            app.conversation(session)?;
            let events = app.interface.subscribe(session)?;
            write!(
                output,
                "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\nConnection: close\r\n\r\n: connected\n\n"
            )?;
            output.flush()?;
            loop {
                match events.recv_timeout(Duration::from_secs(10)) {
                    Ok(event) => {
                        writeln!(output, "data: {}\n", serde_json::to_string(&event)?)?;
                    }
                    Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {
                        writeln!(output, ": heartbeat\n")?
                    }
                    Err(_) => break,
                }
                output.flush()?;
            }
            Ok(())
        }
        _ => Err(Error::new("NOT_FOUND", "Route does not exist")),
    }
}
struct ConversationView;
impl ConversationView {
    fn summary(conversation: &crate::orchestrator::Conversation) -> Value {
        json!({"id":conversation.id,"title":conversation.title,"updated_at":conversation.updated_at,"state":conversation.state})
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Empty {}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct IncomingCommand {
    session_id: String,
    payload: CommandKind,
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn chat_routes_use_the_shared_interface_and_restore_public_conversation_data() {
        struct Echo;
        impl crate::llm::Adapter for Echo {
            fn generate(
                &self,
                _: &crate::llm::Binding,
                _: &crate::llm::Request,
                _: &dyn crate::llm::CredentialResolver,
                _: &crate::llm::Cancellation,
                emit: &mut dyn FnMut(crate::llm::EventKind) -> Result<()>,
            ) -> Result<crate::llm::Response> {
                emit(crate::llm::EventKind::TextDelta {
                    text: "Hello from Ariadne".into(),
                })?;
                let mut message =
                    crate::llm::Message::text(crate::llm::Role::Assistant, "Hello from Ariadne");
                message
                    .continuation
                    .insert("reasoning".into(), json!("HIDDEN-DATA"));
                Ok(crate::llm::Response {
                    message,
                    finish_reason: "stop".into(),
                    usage: Default::default(),
                    provider_request_id: None,
                    model: None,
                })
            }
        }
        let root = std::env::temp_dir().join(crate::interaction::new_id("ariadne-http-test"));
        std::fs::create_dir(&root).unwrap();
        crate::orchestrator::cli::initialize(&root, "example/model").unwrap();
        let mut gateway = crate::llm::Gateway::default();
        gateway.register_adapter("openrouter", Arc::new(Echo));
        let app = Application::start(
            crate::orchestrator::Options {
                root: root.clone(),
                task_path: root.join("tasks.sqlite"),
                ..Default::default()
            },
            Arc::new(gateway),
        )
        .unwrap();
        let call = |method: &str, path: &str, body: Value| {
            let request = HttpRequest {
                method: method.into(),
                path: path.into(),
                headers: HashMap::new(),
                body: body.to_string().into_bytes(),
            };
            let mut output = vec![];
            route(&app, &request, &mut output).unwrap();
            let body = output.windows(4).position(|w| w == b"\r\n\r\n").unwrap() + 4;
            serde_json::from_slice::<Value>(&output[body..]).unwrap()["result"].clone()
        };
        let created = call("POST", "/api/conversations", json!({}));
        let id = created["id"].as_str().unwrap();
        assert_eq!(created["model"], "example/model");
        let events = app.interface.subscribe(id).unwrap();
        let ack = call(
            "POST",
            "/api/commands",
            json!({"session_id":id,"payload":{"type":"send_message","text":"Hello"}}),
        );
        assert!(ack["command_id"].is_string());
        loop {
            let event = events.recv_timeout(Duration::from_secs(3)).unwrap();
            if matches!(
                event.payload,
                crate::interaction::EventKind::RunFinished { .. }
            ) {
                break;
            }
        }
        let restored = call("GET", &format!("/api/conversations/{id}"), Value::Null);
        assert_eq!(restored["messages"][0]["content"], "Hello");
        assert_eq!(restored["messages"][1]["content"], "Hello from Ariadne");
        assert!(!restored.to_string().contains("HIDDEN-DATA"));
        assert_eq!(
            call("GET", "/api/conversations", Value::Null)
                .as_array()
                .unwrap()
                .len(),
            1
        );
        assert_eq!(call("GET", "/api/tasks", Value::Null), json!([]));
        drop(events);
        drop(app);
        std::fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn http_parser_and_origin_checks_reject_ambiguous_or_cross_origin_requests() {
        let request=read_request(b"POST /api/commands HTTP/1.1\r\nHost: 127.0.0.1:8787\r\nContent-Type: application/json\r\nX-Ariadne-Client: ui\r\nContent-Length: 2\r\n\r\n{}".as_slice()).unwrap();
        request.validate_origin("127.0.0.1:8787").unwrap();
        assert!(request.validate_origin("evil.test").is_err());
        for raw in [
            "GET / HTTP/1.1\r\nHost: evil.test\r\n\r\n",
            "POST /api/commands HTTP/1.1\r\nHost: 127.0.0.1:8787\r\n\r\n",
            "GET / HTTP/1.1\r\nHost: 127.0.0.1:8787\r\nOrigin: https://evil.test\r\n\r\n",
        ] {
            assert!(
                read_request(raw.as_bytes())
                    .unwrap()
                    .validate_origin("127.0.0.1:8787")
                    .is_err()
            );
        }
        for raw in [
            "POST / HTTP/1.1\r\nContent-Length: 2\r\nContent-Length: 3\r\n\r\n{}",
            "POST / HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n",
            "POST / HTTP/1.1\r\nContent-Length: 200000\r\n\r\n",
            "POST / HTTP/1.1\r\nContent-Length: 3\r\n\r\n{}",
        ] {
            assert!(read_request(raw.as_bytes()).is_err());
        }
    }
}
