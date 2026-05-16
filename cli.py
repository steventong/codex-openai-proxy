"""
CLI Management Tool for Codex OpenAI Proxy.
Codex OpenAI Proxy 的命令行管理工具。
"""
import time
import click
from identity import account_store


@click.group()
def cli():
    """Codex OpenAI Proxy - Multi-account management panel."""
    pass


@cli.command()
@click.option("--account-id", prompt="Account ID (e.g., user@example.com)", help="Unique account identifier.")
@click.option("--access-token", prompt="Access Token", help="OpenAI access token.")
@click.option("--refresh-token", prompt="Refresh Token", default="", help="OpenAI refresh token.")
@click.option("--id-token", prompt="ID Token (optional)", default="", help="OpenAI ID token.")
def add(account_id, access_token, refresh_token, id_token):
    """Manually add or update an account in the pool."""
    account_store.register_account(account_id, {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "id_token": id_token,
        "last_refresh": time.time(),
    })
    click.secho(f"✅ Account '{account_id}' added successfully.", fg="green")


@cli.command()
def ls():
    """List all accounts and their current status."""
    accounts = account_store.peek_pool()
    if not accounts:
        click.secho("⚠️  Account pool is empty. Use `add` to register an account.", fg="yellow")
        return

    click.secho(f"{'Account ID':<35} | {'Status':<10} | {'Errors':<6} | Last Error", fg="cyan")
    click.secho("-" * 80)
    for aid, acc in accounts.items():
        status = acc.get("status", "unknown")
        color = "green" if status == "active" else "red"
        err_count = acc.get("error_count", 0)
        err_reason = acc.get("last_error_reason", "-")
        click.secho(f"{aid:<35} | {status:<10} | {err_count:<6} | {err_reason}", fg=color)


@cli.command()
@click.argument("account_id")
def rm(account_id):
    """Remove an account from the pool."""
    account_store.unregister_account(account_id)
    click.secho(f"🗑️  Account '{account_id}' removed.", fg="green")


@cli.command()
@click.argument("account_id")
def refresh(account_id):
    """Force a token refresh for a specific account."""
    click.secho(f"Refreshing token for '{account_id}'...", fg="cyan")
    success = account_store.refresh_session(account_id)
    if success:
        click.secho("✅ Refresh successful.", fg="green")
    else:
        click.secho("❌ Refresh failed. Check the refresh_token or network connection.", fg="red")


if __name__ == "__main__":
    cli()
