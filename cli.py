import click
import json
from account_manager import account_manager

@click.group()
def cli():
    """Codex OpenAI Proxy 多账号管理面板"""
    pass

@cli.command()
@click.option('--account-id', prompt='Account ID (e.g., user1@email.com)', help='唯一账号标识')
@click.option('--access-token', prompt='Access Token', help='OpenAI 访问令牌')
@click.option('--refresh-token', prompt='Refresh Token', help='OpenAI 刷新令牌', default='')
@click.option('--id-token', prompt='ID Token (可选)', default='', help='ID 令牌')
def add(account_id, access_token, refresh_token, id_token):
    """手动添加或更新一个账号到账号池"""
    tokens = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "id_token": id_token
    }
    account_manager.add_account(account_id, tokens)
    click.secho(f"✅ 账号 '{account_id}' 已成功添加并加入调度池！", fg='green')

@cli.command()
def ls():
    """列出当前账号池状态"""
    accounts = account_manager.get_all_accounts()
    if not accounts:
        click.secho("⚠️ 当前账号池为空，请使用 add 命令添加账号。", fg='yellow')
        return

    click.secho(f"{'Account ID':<30} | {'Status':<10} | {'Errors':<6} | {'Last Error'}", fg='cyan')
    click.secho("-" * 75)
    for aid, acc in accounts.items():
        status = acc.get("status", "unknown")
        color = 'green' if status == 'active' else 'red'
        err_count = acc.get("error_count", 0)
        err_reason = acc.get("last_error_reason", "-")
        click.secho(f"{aid:<30} | {status:<10} | {err_count:<6} | {err_reason}", fg=color)

@cli.command()
@click.argument('account_id')
def rm(account_id):
    """从账号池中删除指定账号"""
    account_manager.remove_account(account_id)
    click.secho(f"🗑️ 账号 '{account_id}' 已移除。", fg='green')

@cli.command()
@click.argument('account_id')
def refresh(account_id):
    """强制对指定账号进行 Token 刷新"""
    click.secho(f"正在尝试刷新账号 '{account_id}' 的 Token...", fg='cyan')
    success = account_manager.force_refresh_token(account_id)
    if success:
        click.secho("✅ 刷新成功！", fg='green')
    else:
        click.secho("❌ 刷新失败，请检查 refresh_token 或网络连接。", fg='red')

if __name__ == '__main__':
    cli()
