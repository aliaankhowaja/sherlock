use clap::{Args, Parser, Subcommand};

#[derive(Parser, Debug)]
#[command(name = "sherlock", about = "Multi-agent team debugger")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand, Debug)]
enum Commands {
    /// Start the API server and serve the embedded React UI
    Serve(ServeArgs),
}

#[derive(Args, Debug)]
struct ServeArgs {
    /// Interface to bind
    #[arg(long, default_value = "127.0.0.1")]
    host: String,

    /// Port to bind
    #[arg(long, default_value_t = 3000)]
    port: u16,

    /// Do not open a browser window on startup
    #[arg(long, alias = "no-browser", default_value_t = false)]
    no_open: bool,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Commands::Serve(args) => {
            let url = format!("http://{}:{}", args.host, args.port);
            if !args.no_open
                && let Err(e) = webbrowser::open(&url)
            {
                eprintln!("warning: could not open browser ({e})");
            }
            api::serve(api::ServeOptions {
                host: args.host,
                port: args.port,
            })
            .await?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(args: &[&str]) -> Cli {
        Cli::try_parse_from(args).expect("cli should parse")
    }

    #[test]
    fn serve_defaults_to_localhost_3000_with_browser() {
        let cli = parse(&["sherlock", "serve"]);
        let Commands::Serve(args) = cli.command;
        assert_eq!(args.host, "127.0.0.1");
        assert_eq!(args.port, 3000);
        assert!(!args.no_open);
    }

    #[test]
    fn serve_accepts_custom_port_host_and_no_open() {
        let cli = parse(&[
            "sherlock",
            "serve",
            "--host",
            "0.0.0.0",
            "--port",
            "4001",
            "--no-open",
        ]);
        let Commands::Serve(args) = cli.command;
        assert_eq!(args.host, "0.0.0.0");
        assert_eq!(args.port, 4001);
        assert!(args.no_open);
    }

    #[test]
    fn serve_rejects_invalid_port() {
        assert!(Cli::try_parse_from(["sherlock", "serve", "--port", "abc"]).is_err());
    }
}
