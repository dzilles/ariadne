//! Shared model access. Callers own prompts, conversation state, and tool execution.
mod gateway;
mod model;
mod openrouter;
mod transport;

pub use gateway::{Adapter, CredentialResolver, EnvironmentCredentials, Gateway};
pub use model::*;
pub use openrouter::OpenRouter;
pub use transport::{CurlTransport, HttpRequest, HttpTransport, TransportEvent};
