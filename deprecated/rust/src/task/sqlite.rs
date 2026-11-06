//! Small ownership-safe wrapper over the system SQLite library. This avoids an
//! uncached native Rust dependency in the prototype's offline build environment.
use super::{Error, Result};
use std::{
    ffi::{CStr, CString, c_char, c_int, c_void},
    marker::PhantomData,
    ptr::{self, NonNull},
    rc::Rc,
};

#[repr(C)]
struct Sqlite {
    _private: [u8; 0],
}
#[repr(C)]
struct Stmt {
    _private: [u8; 0],
}

#[link(name = "sqlite3")]
unsafe extern "C" {
    fn sqlite3_open_v2(
        name: *const c_char,
        db: *mut *mut Sqlite,
        flags: c_int,
        vfs: *const c_char,
    ) -> c_int;
    fn sqlite3_close(db: *mut Sqlite) -> c_int;
    fn sqlite3_errmsg(db: *mut Sqlite) -> *const c_char;
    fn sqlite3_busy_timeout(db: *mut Sqlite, ms: c_int) -> c_int;
    fn sqlite3_exec(
        db: *mut Sqlite,
        sql: *const c_char,
        callback: Option<
            unsafe extern "C" fn(*mut c_void, c_int, *mut *mut c_char, *mut *mut c_char) -> c_int,
        >,
        arg: *mut c_void,
        error: *mut *mut c_char,
    ) -> c_int;
    fn sqlite3_prepare_v2(
        db: *mut Sqlite,
        sql: *const c_char,
        len: c_int,
        stmt: *mut *mut Stmt,
        tail: *mut *const c_char,
    ) -> c_int;
    fn sqlite3_bind_parameter_count(stmt: *mut Stmt) -> c_int;
    fn sqlite3_bind_text(
        stmt: *mut Stmt,
        index: c_int,
        text: *const c_char,
        len: c_int,
        destroy: Option<unsafe extern "C" fn(*mut c_void)>,
    ) -> c_int;
    fn sqlite3_step(stmt: *mut Stmt) -> c_int;
    fn sqlite3_column_count(stmt: *mut Stmt) -> c_int;
    fn sqlite3_column_text(stmt: *mut Stmt, column: c_int) -> *const u8;
    fn sqlite3_column_bytes(stmt: *mut Stmt, column: c_int) -> c_int;
    fn sqlite3_finalize(stmt: *mut Stmt) -> c_int;
}

pub(crate) struct Connection {
    raw: NonNull<Sqlite>,
    // A connection is deliberately confined to its owning thread.
    _local: PhantomData<Rc<()>>,
}

struct Statement(NonNull<Stmt>);
impl Drop for Statement {
    fn drop(&mut self) {
        // SAFETY: this statement is owned exactly once, and has a live connection.
        unsafe {
            sqlite3_finalize(self.0.as_ptr());
        }
    }
}
impl Drop for Connection {
    fn drop(&mut self) {
        // SAFETY: statements cannot outlive query(); this is the sole owner.
        unsafe {
            sqlite3_close(self.raw.as_ptr());
        }
    }
}

fn cstring(text: &str) -> Result<CString> {
    CString::new(text).map_err(|_| Error::invalid("SQL parameter contains a NUL byte"))
}

impl Connection {
    pub(crate) fn open(path: &str) -> Result<Self> {
        let name = cstring(path)?;
        let mut raw = ptr::null_mut();
        // SAFETY: name is NUL-terminated; the out pointer is valid. READWRITE | CREATE.
        let code = unsafe { sqlite3_open_v2(name.as_ptr(), &mut raw, 0x02 | 0x04, ptr::null()) };
        let Some(raw) = NonNull::new(raw) else {
            return Err(Error::new(
                "DATABASE_ERROR",
                "SQLite could not allocate a connection",
            ));
        };
        let db = Self {
            raw,
            _local: PhantomData,
        };
        if code != 0 {
            return Err(db.error());
        }
        // SAFETY: the connection is live. The timeout prevents immediate lock failures.
        if unsafe { sqlite3_busy_timeout(db.raw.as_ptr(), 5000) } != 0 {
            return Err(db.error());
        }
        db.exec("PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;")?;
        Ok(db)
    }

    fn error(&self) -> Error {
        // SAFETY: SQLite owns a NUL-terminated error string until the next call.
        let message =
            unsafe { CStr::from_ptr(sqlite3_errmsg(self.raw.as_ptr())) }.to_string_lossy();
        Error::new("DATABASE_ERROR", message.into_owned())
    }

    pub(crate) fn exec(&self, sql: &str) -> Result<()> {
        let sql = cstring(sql)?;
        // SAFETY: only internal constant SQL uses exec; no callback or error allocation.
        let code = unsafe {
            sqlite3_exec(
                self.raw.as_ptr(),
                sql.as_ptr(),
                None,
                ptr::null_mut(),
                ptr::null_mut(),
            )
        };
        if code == 0 { Ok(()) } else { Err(self.error()) }
    }

    pub(crate) fn query(&self, sql: &str, params: &[&str]) -> Result<Vec<Vec<String>>> {
        let sql = cstring(sql)?;
        // Keep bindings alive until after Statement's destructor (SQLITE_STATIC).
        let bindings: Vec<CString> = params
            .iter()
            .map(|value| cstring(value))
            .collect::<Result<_>>()?;
        let mut raw = ptr::null_mut();
        // SAFETY: connection, SQL, and out pointer are valid; SQLite copies the SQL.
        let code = unsafe {
            sqlite3_prepare_v2(
                self.raw.as_ptr(),
                sql.as_ptr(),
                -1,
                &mut raw,
                ptr::null_mut(),
            )
        };
        if code != 0 {
            return Err(self.error());
        }
        let stmt =
            Statement(NonNull::new(raw).ok_or_else(|| Error::invalid("Empty SQL statement"))?);
        // SAFETY: stmt is live.
        if unsafe { sqlite3_bind_parameter_count(stmt.0.as_ptr()) } as usize != bindings.len() {
            return Err(Error::invalid("Incorrect SQL parameter count"));
        }
        for (index, value) in bindings.iter().enumerate() {
            // SAFETY: values remain alive and unchanged until the statement is finalized.
            let code = unsafe {
                sqlite3_bind_text(
                    stmt.0.as_ptr(),
                    (index + 1) as c_int,
                    value.as_ptr(),
                    -1,
                    None,
                )
            };
            if code != 0 {
                return Err(self.error());
            }
        }
        let mut rows = Vec::new();
        loop {
            // SAFETY: all bindings and the owning connection are live.
            match unsafe { sqlite3_step(stmt.0.as_ptr()) } {
                100 => {
                    let mut row = Vec::new();
                    // SAFETY: a row is available; column count and bytes belong to it.
                    for index in 0..unsafe { sqlite3_column_count(stmt.0.as_ptr()) } {
                        let text = unsafe { sqlite3_column_text(stmt.0.as_ptr(), index) };
                        let len = unsafe { sqlite3_column_bytes(stmt.0.as_ptr(), index) } as usize;
                        row.push(if text.is_null() {
                            String::new()
                        } else {
                            // SAFETY: SQLite guarantees len valid bytes until the next step.
                            String::from_utf8(
                                unsafe { std::slice::from_raw_parts(text, len) }.to_vec(),
                            )
                            .map_err(|_| Error::new("DATABASE_ERROR", "Invalid UTF-8 in SQLite"))?
                        });
                    }
                    rows.push(row);
                }
                101 => return Ok(rows),
                _ => return Err(self.error()),
            }
        }
    }

    pub(crate) fn run(&self, sql: &str, params: &[&str]) -> Result<()> {
        self.query(sql, params).map(|_| ())
    }
    pub(crate) fn scalar(&self, sql: &str, params: &[&str]) -> Result<String> {
        self.query(sql, params)?
            .into_iter()
            .next()
            .and_then(|r| r.into_iter().next())
            .ok_or_else(|| Error::new("NOT_FOUND", "Database query returned no result"))
    }
}
