use ariadne_tasks::{Result, configuration::Provider, llm::*};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    io::{Read, Write},
    net::TcpListener,
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant},
};

struct Credentials;
impl CredentialResolver for Credentials {
    fn resolve(&self, _: &str) -> Result<String> {
        Ok("test-secret".into())
    }
}
struct Mock {
    chunks: Vec<Vec<u8>>,
    status: u16,
    requests: Mutex<Vec<Value>>,
}
impl HttpTransport for Mock {
    fn post(
        &self,
        request: &HttpRequest,
        cancel: &Cancellation,
        receive: &mut dyn FnMut(TransportEvent) -> Result<()>,
    ) -> Result<()> {
        cancel.check()?;
        self.requests
            .lock()
            .unwrap()
            .push(serde_json::from_slice(&request.body).unwrap());
        assert_eq!(request.bearer, "test-secret");
        receive(TransportEvent::Headers {
            status: self.status,
            content_type: "text/event-stream; charset=utf-8".into(),
        })?;
        for bytes in &self.chunks {
            receive(TransportEvent::Data(bytes.clone()))?;
        }
        Ok(())
    }
}
fn binding() -> Binding {
    Binding {
        provider: Provider {
            id: "api".into(),
            adapter: "openrouter".into(),
            base_url: "https://openrouter.ai/api/v1".into(),
            credential_ref: "env:TEST_KEY".into(),
        },
        model: "example/model".into(),
        snapshot_id: "snapshot-1".into(),
        settings: BTreeMap::new(),
    }
}
fn context() -> CallContext {
    CallContext {
        call_id: "call-1".into(),
        caller_id: "tool-search".into(),
        snapshot_id: "snapshot-1".into(),
        session_id: None,
        run_id: None,
        task_id: None,
        parent_call_id: Some("parent-1".into()),
    }
}
fn setup(stream: &str, status: u16) -> (Gateway, Arc<Mock>) {
    let transport = Arc::new(Mock {
        chunks: stream.as_bytes().chunks(1).map(<[u8]>::to_vec).collect(),
        status,
        requests: Mutex::new(vec![]),
    });
    let mut gateway = Gateway::new(Arc::new(Credentials));
    gateway.register_adapter("openrouter", Arc::new(OpenRouter::new(transport.clone())));
    (gateway, transport)
}
fn request() -> Request {
    Request {
        messages: vec![Message::text(Role::User, "hello")],
        tools: vec![],
    }
}
fn event(value: Value) -> String {
    format!("data: {value}\r\n\r\n")
}
fn text_stream(text: &str) -> String {
    format!(
        "{}{}data: [DONE]\n\n",
        event(
            json!({"id":"generation-1","model":"example/model","choices":[{"delta":{"content":text},"finish_reason":null}]})
        ),
        event(
            json!({"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":5,"completion_tokens":3,"cost":0.01}})
        )
    )
}

#[test]
fn fragmented_unicode_comments_usage_and_context_are_normalized() {
    let (gateway, transport) = setup(
        &format!(": keepalive\r\n\r\n{}", text_stream("héllo 🌍")),
        200,
    );
    let mut events = vec![];
    let response = gateway
        .generate(
            &binding(),
            &request(),
            &context(),
            &Cancellation::default(),
            &mut |event| {
                events.push(event);
                Ok(())
            },
        )
        .unwrap();
    assert_eq!(response.message.content.as_deref(), Some("héllo 🌍"));
    assert_eq!(response.usage.input_tokens, Some(5));
    assert_eq!(response.usage.cost, Some(0.01));
    assert!(
        events
            .iter()
            .all(|event| event.context.parent_call_id.as_deref() == Some("parent-1"))
    );
    assert!(matches!(events.first().unwrap().kind, EventKind::Started));
    assert!(matches!(
        events.last().unwrap().kind,
        EventKind::Finished { .. }
    ));
    let requests = transport.requests.lock().unwrap();
    assert_eq!(requests[0]["provider"]["require_parameters"], true);
    assert_eq!(requests[0]["provider"]["allow_fallbacks"], false);
    assert!(!requests[0].to_string().contains("test-secret"));
}

#[test]
fn tool_arguments_and_continuation_data_survive_a_second_call() {
    let stream = format!(
        "{}{}{}data: [DONE]\n\n",
        event(
            json!({"choices":[{"delta":{"tool_calls":[{"index":0,"id":"tool-1","type":"function","function":{"name":"get_task","arguments":"{\"id\":"}}],"reasoning_details":[{"type":"reasoning.encrypted","data":"opaque","index":0}]}}]})
        ),
        event(
            json!({"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\"abc\"}"}}]}}]})
        ),
        event(json!({"choices":[{"delta":{},"finish_reason":"tool_calls"}]}))
    );
    let (gateway, transport) = setup(&stream, 200);
    let mut events = vec![];
    let first = gateway
        .generate(
            &binding(),
            &request(),
            &context(),
            &Cancellation::default(),
            &mut |event| {
                events.push(event);
                Ok(())
            },
        )
        .unwrap();
    assert_eq!(first.message.tool_calls[0].arguments, "{\"id\":\"abc\"}");
    assert_eq!(
        events
            .iter()
            .filter(|event| matches!(event.kind, EventKind::ToolCallReady { .. }))
            .count(),
        1
    );
    assert!(
        !events
            .iter()
            .any(|event| matches!(event.kind, EventKind::TextDelta { .. }))
    );
    let mut second = request();
    second.messages.push(first.message);
    second
        .messages
        .push(Message::tool("tool-1", &json!({"ok":true})));
    gateway
        .generate(
            &binding(),
            &second,
            &context(),
            &Cancellation::default(),
            &mut |_| Ok(()),
        )
        .unwrap();
    let captured = transport.requests.lock().unwrap();
    assert_eq!(
        captured[1]["messages"][1]["reasoning_details"][0]["data"],
        "opaque"
    );
    assert_eq!(captured[1]["messages"][2]["tool_call_id"], "tool-1");
}

#[test]
fn truncated_invalid_and_error_streams_fail_without_ready_tools() {
    let bad_streams = vec![
        "data: {invalid}\n\n".to_string(),
        event(json!({"choices":[{"delta":{"content":"partial"},"finish_reason":"stop"}]})),
        format!(
            "{}data: [DONE]\n\n",
            event(
                json!({"choices":[{"delta":{"tool_calls":[{"index":0,"id":"tool","function":{"name":"create_task","arguments":"{"}}]},"finish_reason":"tool_calls"}]})
            )
        ),
        format!(
            "{}{}data: [DONE]\n\n",
            event(json!({"choices":[{"delta":{"content":"partial"}}]})),
            event(json!({"error":{"code":503,"message":"test-secret must not leak"}}))
        ),
    ];
    for stream in bad_streams {
        let (gateway, _) = setup(&stream, 200);
        let mut events = vec![];
        let error = gateway
            .generate(
                &binding(),
                &request(),
                &context(),
                &Cancellation::default(),
                &mut |event| {
                    events.push(event);
                    Ok(())
                },
            )
            .unwrap_err();
        assert!(!error.to_string().contains("test-secret"));
        assert!(matches!(
            events.last().unwrap().kind,
            EventKind::Failed { .. }
        ));
        assert!(!events.iter().any(|event| matches!(
            event.kind,
            EventKind::ToolCallReady { .. } | EventKind::Finished { .. }
        )));
    }
}

#[test]
fn http_errors_missing_credentials_unknown_adapters_and_cancellation_are_explicit() {
    for (status, code) in [
        (401, "AUTHENTICATION_ERROR"),
        (402, "PAYMENT_REQUIRED"),
        (429, "RATE_LIMITED"),
        (503, "PROVIDER_ERROR"),
    ] {
        let (gateway, _) = setup("", status);
        assert_eq!(
            gateway
                .generate(
                    &binding(),
                    &request(),
                    &context(),
                    &Cancellation::default(),
                    &mut |_| Ok(())
                )
                .unwrap_err()
                .code,
            code
        );
    }
    assert_eq!(
        EnvironmentCredentials
            .resolve("env:ARIADNE_MISSING_TEST_KEY_765124")
            .unwrap_err()
            .code,
        "AUTHENTICATION_ERROR"
    );
    let (gateway, transport) = setup(&text_stream("hello"), 200);
    let cancel = Cancellation::default();
    cancel.cancel();
    assert_eq!(
        gateway
            .generate(&binding(), &request(), &context(), &cancel, &mut |_| Ok(()))
            .unwrap_err()
            .code,
        "CANCELLED"
    );
    assert!(transport.requests.lock().unwrap().is_empty());
    let mut other = binding();
    other.provider.adapter = "other".into();
    assert_eq!(
        gateway
            .generate(
                &other,
                &request(),
                &context(),
                &Cancellation::default(),
                &mut |_| Ok(())
            )
            .unwrap_err()
            .code,
        "UNSUPPORTED_ADAPTER"
    );
}

#[test]
fn one_gateway_is_safe_for_concurrent_orchestrator_agent_and_nested_tool_calls() {
    struct Echo;
    impl HttpTransport for Echo {
        fn post(
            &self,
            request: &HttpRequest,
            _: &Cancellation,
            receive: &mut dyn FnMut(TransportEvent) -> Result<()>,
        ) -> Result<()> {
            let body: Value = serde_json::from_slice(&request.body)?;
            let text = format!(
                "{}:{}",
                body["model"].as_str().unwrap(),
                body["messages"][0]["content"].as_str().unwrap()
            );
            receive(TransportEvent::Headers {
                status: 200,
                content_type: "text/event-stream".into(),
            })?;
            for chunk in text_stream(&text).as_bytes().chunks(7) {
                thread::yield_now();
                receive(TransportEvent::Data(chunk.to_vec()))?;
            }
            Ok(())
        }
    }
    let mut gateway = Gateway::new(Arc::new(Credentials));
    gateway.register_adapter("openrouter", Arc::new(OpenRouter::new(Arc::new(Echo))));
    let gateway = Arc::new(gateway);
    let workers = ["orchestrator", "agent", "nested-tool"]
        .into_iter()
        .map(|caller| {
            let gateway = gateway.clone();
            thread::spawn(move || {
                let mut binding = binding();
                binding.model = format!("example/{caller}");
                let mut context = context();
                context.caller_id = caller.into();
                context.call_id = format!("call-{caller}");
                let request = Request {
                    messages: vec![Message::text(Role::User, caller)],
                    tools: vec![],
                };
                let mut observed = String::new();
                let response = gateway
                    .generate(
                        &binding,
                        &request,
                        &context,
                        &Cancellation::default(),
                        &mut |event| {
                            assert_eq!(event.context.call_id, context.call_id);
                            assert_eq!(event.context.caller_id, caller);
                            if let EventKind::TextDelta { text } = event.kind {
                                observed.push_str(&text);
                            }
                            Ok(())
                        },
                    )
                    .unwrap();
                assert_eq!(observed, format!("example/{caller}:{caller}"));
                assert_eq!(response.message.content.as_deref(), Some(observed.as_str()));
            })
        })
        .collect::<Vec<_>>();
    for worker in workers {
        worker.join().unwrap();
    }
}

#[test]
#[ignore = "requires loopback sockets; run with cargo test --test llm -- --ignored outside the restricted sandbox"]
fn real_curl_transport_streams_json_and_keeps_credentials_out_of_arguments() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let server = thread::spawn(move || {
        let (mut socket, _) = listener.accept().unwrap();
        socket
            .set_read_timeout(Some(Duration::from_secs(3)))
            .unwrap();
        let mut bytes = vec![];
        let mut buffer = [0; 4096];
        loop {
            let n = socket.read(&mut buffer).unwrap();
            assert_ne!(n, 0);
            bytes.extend_from_slice(&buffer[..n]);
            if let Some(end) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
                let headers = String::from_utf8_lossy(&bytes[..end]);
                let length = headers
                    .lines()
                    .find_map(|line| {
                        line.to_ascii_lowercase()
                            .strip_prefix("content-length:")
                            .and_then(|v| v.trim().parse::<usize>().ok())
                    })
                    .unwrap();
                if bytes.len() >= end + 4 + length {
                    break;
                }
            }
        }
        let received = String::from_utf8(bytes).unwrap();
        assert!(received.contains("Authorization: Bearer test-secret"));
        assert!(received.contains("\\\"quoted\\\""));
        let body = text_stream("real transport");
        write!(
            socket,
            "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: {}\r\n\r\n{}",
            body.len(),
            body
        )
        .unwrap();
    });
    let mut gateway = Gateway::new(Arc::new(Credentials));
    gateway.register_adapter(
        "openrouter",
        Arc::new(OpenRouter::new(Arc::new(CurlTransport))),
    );
    let mut binding = binding();
    binding.provider.base_url = format!("http://{address}/api/v1");
    let mut request = request();
    request.messages[0].content = Some("a \"quoted\" line\nand café".into());
    let response = gateway
        .generate(
            &binding,
            &request,
            &context(),
            &Cancellation::default(),
            &mut |_| Ok(()),
        )
        .unwrap();
    assert_eq!(response.message.content.as_deref(), Some("real transport"));
    server.join().unwrap();
}

#[test]
#[ignore = "requires loopback sockets; run with cargo test --test llm -- --ignored outside the restricted sandbox"]
fn cancellation_interrupts_a_stalled_http_request() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let (connected, ready) = std::sync::mpsc::channel();
    let server = thread::spawn(move || {
        let (mut socket, _) = listener.accept().unwrap();
        connected.send(()).unwrap();
        socket
            .set_read_timeout(Some(Duration::from_secs(3)))
            .unwrap();
        let mut buffer = [0; 4096];
        while socket.read(&mut buffer).unwrap_or(0) > 0 {}
    });
    let cancel = Cancellation::default();
    let worker_cancel = cancel.clone();
    let worker = thread::spawn(move || {
        let mut gateway = Gateway::new(Arc::new(Credentials));
        gateway.register_adapter(
            "openrouter",
            Arc::new(OpenRouter::new(Arc::new(CurlTransport))),
        );
        let mut binding = binding();
        binding.provider.base_url = format!("http://{address}/api/v1");
        gateway
            .generate(
                &binding,
                &request(),
                &context(),
                &worker_cancel,
                &mut |_| Ok(()),
            )
            .unwrap_err()
            .code
    });
    ready.recv_timeout(Duration::from_secs(3)).unwrap();
    let start = Instant::now();
    cancel.cancel();
    assert_eq!(worker.join().unwrap(), "CANCELLED");
    assert!(start.elapsed() < Duration::from_secs(2));
    server.join().unwrap();
}
