use serde::{Deserialize, Serialize};
use std::fmt;

pub type Result<T> = std::result::Result<T, Error>;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Error {
    pub code: String,
    pub message: String,
    pub retryable: bool,
}
impl Error {
    pub fn new(code: &str, message: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
            retryable: false,
        }
    }
    pub fn invalid(message: impl Into<String>) -> Self {
        Self::new("VALIDATION_ERROR", message)
    }
    pub fn retryable(mut self) -> Self {
        self.retryable = true;
        self
    }
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}
impl std::error::Error for Error {}
impl From<std::io::Error> for Error {
    fn from(error: std::io::Error) -> Self {
        Self::new("IO_ERROR", error.to_string())
    }
}
impl From<serde_json::Error> for Error {
    fn from(error: serde_json::Error) -> Self {
        Self::invalid(error.to_string())
    }
}
impl From<crate::configuration::Error> for Error {
    fn from(error: crate::configuration::Error) -> Self {
        Self::new(error.code, error.message)
    }
}
impl From<crate::task::Error> for Error {
    fn from(error: crate::task::Error) -> Self {
        Self::new(error.code, error.message)
    }
}
