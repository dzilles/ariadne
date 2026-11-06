use super::*;
use crate::{Error, Result};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
};

pub struct OpenRouter {
    transport: Arc<dyn HttpTransport>,
}
impl OpenRouter {
    pub fn new(transport: Arc<dyn HttpTransport>) -> Self {
        Self { transport }
    }
}
impl Adapter for OpenRouter {
    fn generate(
        &self,
        binding: &Binding,
        request: &Request,
        credentials: &dyn CredentialResolver,
        cancellation: &Cancellation,
        emit: &mut dyn FnMut(EventKind) -> Result<()>,
    ) -> Result<Response> {
        let mut body = json!({
            "model":binding.model, "messages":request.messages.iter().map(encode_message).collect::<Vec<_>>(),
            "stream":true, "stream_options":{"include_usage":true},
            "max_tokens":binding.settings.get("max_output_tokens").cloned().unwrap_or(json!(2048)),
            "provider":{"require_parameters":true, "allow_fallbacks":false}
        });
        for name in ["temperature", "top_p"] {
            if let Some(value) = binding.settings.get(name) {
                body[name] = value.clone();
            }
        }
        if !request.tools.is_empty() {
            body["tools"] = Value::Array(request.tools.iter().map(|tool| json!({"type":"function", "function":{
                "name":tool.name, "description":tool.description, "parameters":tool.input_schema
            }})).collect());
            body["tool_choice"] = json!("auto");
        }
        let http = HttpRequest {
            url: format!(
                "{}/chat/completions",
                binding.provider.base_url.trim_end_matches('/')
            ),
            bearer: credentials.resolve(&binding.provider.credential_ref)?,
            body: serde_json::to_vec(&body)?,
            timeout_ms: binding.timeout_ms(),
        };
        let mut parser = StreamParser::new();
        let mut got_headers = false;
        self.transport.post(&http, cancellation, &mut |packet| {
            cancellation.check()?;
            match packet {
                TransportEvent::Headers {
                    status,
                    content_type,
                } => {
                    if got_headers {
                        return Err(protocol("Unexpected repeated response headers"));
                    }
                    got_headers = true;
                    if status != 200 {
                        return Err(status_error(status));
                    }
                    if !content_type
                        .split(';')
                        .next()
                        .unwrap_or("")
                        .trim()
                        .eq_ignore_ascii_case("text/event-stream")
                    {
                        return Err(protocol("Expected an SSE response from OpenRouter"));
                    }
                }
                TransportEvent::Data(bytes) => {
                    if !got_headers {
                        return Err(protocol("Response body arrived before headers"));
                    }
                    parser.feed(&bytes, emit)?;
                }
            }
            Ok(())
        })?;
        parser.finish(emit)
    }
}

fn encode_message(message: &Message) -> Value {
    let mut value = json!({"role":message.role,"content":message.content});
    if !message.tool_calls.is_empty() {
        value["tool_calls"] = json!(message.tool_calls.iter().map(|call| json!({
            "id":call.id,"type":"function","function":{"name":call.name,"arguments":call.arguments}
        })).collect::<Vec<_>>());
    }
    if let Some(id) = &message.tool_call_id {
        value["tool_call_id"] = json!(id);
    }
    for key in ["reasoning", "reasoning_details"] {
        if let Some(data) = message.continuation.get(key) {
            value[key] = data.clone();
        }
    }
    value
}

fn protocol(message: &str) -> Error {
    Error::new("PROTOCOL_ERROR", message)
}
fn status_error(status: u16) -> Error {
    match status {
        401 | 403 => Error::new(
            "AUTHENTICATION_ERROR",
            "OpenRouter rejected the credentials",
        ),
        402 => Error::new(
            "PAYMENT_REQUIRED",
            "OpenRouter account has insufficient credits",
        ),
        429 => Error::new("RATE_LIMITED", "OpenRouter rate limit reached").retryable(),
        408 | 504 => Error::new("TIMEOUT", "OpenRouter request timed out").retryable(),
        400 | 404 | 422 => Error::new(
            "PROVIDER_REQUEST_ERROR",
            "OpenRouter rejected the model or request parameters",
        ),
        _ => Error::new(
            "PROVIDER_ERROR",
            format!("OpenRouter returned HTTP {status}"),
        )
        .retryable(),
    }
}

#[derive(Default)]
struct PartialCall {
    id: String,
    name: String,
    arguments: String,
}
struct StreamParser {
    buffer: Vec<u8>,
    data: Vec<String>,
    total: usize,
    done: bool,
    response: Response,
    calls: BTreeMap<u64, PartialCall>,
}
impl StreamParser {
    fn new() -> Self {
        Self {
            buffer: vec![],
            data: vec![],
            total: 0,
            done: false,
            calls: BTreeMap::new(),
            response: Response {
                message: Message::text(Role::Assistant, ""),
                finish_reason: String::new(),
                usage: Usage::default(),
                provider_request_id: None,
                model: None,
            },
        }
    }
    fn feed(&mut self, bytes: &[u8], emit: &mut dyn FnMut(EventKind) -> Result<()>) -> Result<()> {
        self.total += bytes.len();
        if self.total > 16 * 1024 * 1024 {
            return Err(protocol("Model response exceeded 16 MiB"));
        }
        self.buffer.extend_from_slice(bytes);
        while let Some(end) = self.buffer.iter().position(|byte| *byte == b'\n') {
            let line = self.buffer.drain(..=end).collect::<Vec<_>>();
            let line = std::str::from_utf8(&line)
                .map_err(|_| protocol("Invalid UTF-8 in SSE stream"))?
                .trim_end_matches(['\r', '\n']);
            if line.is_empty() {
                self.dispatch(emit)?;
            } else if let Some(value) = line.strip_prefix("data:") {
                self.data
                    .push(value.strip_prefix(' ').unwrap_or(value).into());
            }
            // SSE comments, IDs, and event names do not contain completion data.
        }
        Ok(())
    }
    fn dispatch(&mut self, emit: &mut dyn FnMut(EventKind) -> Result<()>) -> Result<()> {
        if self.data.is_empty() {
            return Ok(());
        }
        let data = std::mem::take(&mut self.data).join("\n");
        if self.done {
            return Err(protocol("Unexpected data after stream completion"));
        }
        if data == "[DONE]" {
            self.done = true;
            return Ok(());
        }
        let value: Value =
            serde_json::from_str(&data).map_err(|_| protocol("Invalid JSON in SSE event"))?;
        if let Some(error) = value.get("error") {
            let status = error
                .get("code")
                .and_then(Value::as_u64)
                .and_then(|s| u16::try_from(s).ok());
            return Err(status.map(status_error).unwrap_or_else(|| {
                Error::new("PROVIDER_ERROR", "OpenRouter failed during generation")
            }));
        }
        if let Some(id) = value["id"].as_str() {
            self.response.provider_request_id = Some(id.into());
        }
        if let Some(model) = value["model"].as_str() {
            self.response.model = Some(model.into());
        }
        if let Some(usage) = value.get("usage").filter(|u| u.is_object()) {
            self.response.usage = Usage {
                input_tokens: usage["prompt_tokens"].as_u64(),
                output_tokens: usage["completion_tokens"].as_u64(),
                cost: usage["cost"]
                    .as_f64()
                    .filter(|n| n.is_finite() && *n >= 0.0),
            };
            emit(EventKind::Usage {
                usage: self.response.usage.clone(),
            })?;
        }
        let Some(choices) = value["choices"].as_array() else {
            return Err(protocol("SSE event has no choices"));
        };
        if choices.len() > 1 {
            return Err(protocol("Expected a single completion choice"));
        }
        let Some(choice) = choices.first() else {
            return Ok(());
        };
        if let Some(reason) = choice["finish_reason"].as_str() {
            if reason == "error" {
                return Err(Error::new(
                    "PROVIDER_ERROR",
                    "OpenRouter failed during generation",
                ));
            }
            if !self.response.finish_reason.is_empty() {
                return Err(protocol("Repeated completion finish reason"));
            }
            self.response.finish_reason = reason.into();
        }
        let delta = &choice["delta"];
        if let Some(text) = delta["content"].as_str() {
            self.response
                .message
                .content
                .as_mut()
                .unwrap()
                .push_str(text);
            emit(EventKind::TextDelta { text: text.into() })?;
        }
        if let Some(text) = delta["refusal"].as_str() {
            self.response
                .message
                .content
                .as_mut()
                .unwrap()
                .push_str(text);
            emit(EventKind::TextDelta { text: text.into() })?;
        }
        if let Some(reasoning) = delta["reasoning"].as_str() {
            let entry = self
                .response
                .message
                .continuation
                .entry("reasoning".into())
                .or_insert(json!(""));
            let mut text = entry.as_str().unwrap_or("").to_string();
            text.push_str(reasoning);
            *entry = json!(text);
        }
        if let Some(details) = delta["reasoning_details"].as_array() {
            self.response
                .message
                .continuation
                .entry("reasoning_details".into())
                .or_insert(json!([]))
                .as_array_mut()
                .unwrap()
                .extend(details.iter().cloned());
        }
        if let Some(calls) = delta["tool_calls"].as_array() {
            for call in calls {
                let index = call["index"]
                    .as_u64()
                    .filter(|n| *n < 32)
                    .ok_or_else(|| protocol("Invalid tool-call index"))?;
                if call
                    .get("type")
                    .and_then(Value::as_str)
                    .is_some_and(|s| s != "function")
                {
                    return Err(protocol("Unsupported tool-call type"));
                }
                let entry = self.calls.entry(index).or_default();
                if let Some(id) = call["id"].as_str() {
                    entry.id.push_str(id);
                }
                if let Some(name) = call["function"]["name"].as_str() {
                    entry.name.push_str(name);
                }
                if let Some(arguments) = call["function"]["arguments"].as_str() {
                    entry.arguments.push_str(arguments);
                }
            }
        }
        Ok(())
    }
    fn finish(mut self, emit: &mut dyn FnMut(EventKind) -> Result<()>) -> Result<Response> {
        if !self.done
            || self.response.finish_reason.is_empty()
            || !self.buffer.is_empty()
            || !self.data.is_empty()
        {
            return Err(protocol(
                "Model stream ended without a complete terminal event",
            ));
        }
        let mut ids = BTreeSet::new();
        for (_, call) in self.calls {
            if self.response.finish_reason != "tool_calls"
                || call.id.is_empty()
                || call.name.is_empty()
                || !ids.insert(call.id.clone())
            {
                return Err(protocol("Incomplete, duplicate, or truncated tool call"));
            }
            let arguments: Value = serde_json::from_str(&call.arguments)
                .map_err(|_| protocol("Tool arguments are not complete JSON"))?;
            if !arguments.is_object() {
                return Err(protocol("Tool arguments must be a JSON object"));
            }
            self.response.message.tool_calls.push(ToolCall {
                id: call.id,
                name: call.name,
                arguments: call.arguments,
            });
        }
        if self.response.finish_reason == "tool_calls"
            && self.response.message.tool_calls.is_empty()
        {
            return Err(protocol("Tool-call completion contains no calls"));
        }
        if self.response.message.content.as_deref() == Some("") {
            self.response.message.content = None;
        }
        for call in &self.response.message.tool_calls {
            emit(EventKind::ToolCallReady { call: call.clone() })?;
        }
        Ok(self.response)
    }
}
