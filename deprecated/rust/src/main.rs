fn main() {
    let result = if std::env::args().nth(1).as_deref() == Some("chat") {
        ariadne_tasks::orchestrator::cli::run().map_err(|error| error.to_string())
    } else if std::env::args().nth(1).as_deref() == Some("config") {
        ariadne_tasks::configuration::cli::run().map_err(|error| error.to_string())
    } else {
        ariadne_tasks::task::cli::run().map_err(|error| error.to_string())
    };
    if let Err(error) = result {
        eprintln!("{error}");
        std::process::exit(1);
    }
}
