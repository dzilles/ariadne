use super::*;
use crate::{Error, Result};
use std::{collections::BTreeMap, sync::Arc};

pub trait CredentialResolver: Send + Sync {
    fn resolve(&self, reference: &str) -> Result<String>;
}
pub struct EnvironmentCredentials;
impl CredentialResolver for EnvironmentCredentials {
    fn resolve(&self, reference: &str) -> Result<String> {
        let name = reference
            .strip_prefix("env:")
            .ok_or_else(|| Error::invalid("Unsupported credential reference"))?;
        let value = std::env::var(name).map_err(|_| {
            Error::new(
                "AUTHENTICATION_ERROR",
                format!("Set environment variable {name}"),
            )
        })?;
        if value.is_empty() || value.chars().any(char::is_control) {
            return Err(Error::new(
                "AUTHENTICATION_ERROR",
                "Credential is empty or contains control characters",
            ));
        }
        Ok(value)
    }
}

/// Implementations emit incremental events. Gateway owns the terminal event.
pub trait Adapter: Send + Sync {
    fn generate(
        &self,
        binding: &Binding,
        request: &Request,
        credentials: &dyn CredentialResolver,
        cancellation: &Cancellation,
        emit: &mut dyn FnMut(EventKind) -> Result<()>,
    ) -> Result<Response>;
}

pub struct Gateway {
    adapters: BTreeMap<String, Arc<dyn Adapter>>,
    credentials: Arc<dyn CredentialResolver>,
}
impl Default for Gateway {
    fn default() -> Self {
        let mut gateway = Self::new(Arc::new(EnvironmentCredentials));
        gateway.register_adapter(
            "openrouter",
            Arc::new(OpenRouter::new(Arc::new(CurlTransport))),
        );
        gateway
    }
}
impl Gateway {
    pub fn new(credentials: Arc<dyn CredentialResolver>) -> Self {
        Self {
            adapters: BTreeMap::new(),
            credentials,
        }
    }
    pub fn register_adapter(&mut self, kind: &str, adapter: Arc<dyn Adapter>) {
        self.adapters.insert(kind.into(), adapter);
    }

    /// Blocking streaming API; run on a worker thread when driving a UI.
    pub fn generate(
        &self,
        binding: &Binding,
        request: &Request,
        context: &CallContext,
        cancellation: &Cancellation,
        emit: &mut dyn FnMut(Event) -> Result<()>,
    ) -> Result<Response> {
        let mut forward = |kind| {
            emit(Event {
                context: context.clone(),
                kind,
            })
        };
        forward(EventKind::Started)?;
        let result = (|| {
            cancellation.check()?;
            binding.provider.validate()?;
            if binding.model.trim().is_empty() {
                return Err(Error::invalid("Model ID cannot be empty"));
            }
            if context.call_id.is_empty()
                || context.caller_id.is_empty()
                || context.snapshot_id != binding.snapshot_id
            {
                return Err(Error::invalid(
                    "Call context must identify the caller, invocation, and matching configuration snapshot",
                ));
            }
            if request.messages.is_empty() {
                return Err(Error::invalid("Model request needs messages"));
            }
            let adapter = self
                .adapters
                .get(&binding.provider.adapter)
                .ok_or_else(|| {
                    Error::new(
                        "UNSUPPORTED_ADAPTER",
                        "No adapter registered for this connection",
                    )
                })?;
            // Prevent adapter implementations from accidentally emitting their own terminal events.
            let mut incremental = |event| match event {
                EventKind::TextDelta { .. }
                | EventKind::ToolCallReady { .. }
                | EventKind::Usage { .. } => forward(event),
                _ => Err(Error::new(
                    "ADAPTER_ERROR",
                    "Adapter emitted an invalid lifecycle event",
                )),
            };
            let response = adapter.generate(
                binding,
                request,
                self.credentials.as_ref(),
                cancellation,
                &mut incremental,
            )?;
            cancellation.check()?;
            Ok(response)
        })();
        match &result {
            Ok(response) => forward(EventKind::Finished {
                response: response.clone(),
            })?,
            Err(error) => forward(EventKind::Failed {
                error: error.clone(),
            })?,
        }
        result
    }
}
