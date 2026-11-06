//! Ariadne's task prototype. Orchestrator writes and observed execution events
//! have separate interfaces; embeddings are derived from transactional sources.
mod error;
mod model;
pub(crate) mod sqlite;
mod store;
mod vectors;

pub use error::{Error, Result};
pub use model::*;
pub use store::{OrchestratorApi, RecordingApi, TaskStore};
pub use vectors::*;

pub mod cli;
pub mod tools;

#[cfg(test)]
mod tests;
