//! Local chat frontends using the same command/event interface.
mod server;
mod terminal;
pub use server::{serve, serve_listener};
pub use terminal::terminal;
