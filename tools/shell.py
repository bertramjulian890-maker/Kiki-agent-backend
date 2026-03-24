import subprocess
import re
from langchain_core.tools import tool

import shlex

@tool
def install_ncm_cli() -> str:
    """执行 npm install -g @music163/ncm-cli 来安装网易云音乐 CLI 工具"""
    try:
        result = subprocess.run(
            ["npm", "install", "-g", "@music163/ncm-cli"],
            capture_output=True,
            text=True,
            timeout=120
        )
        return result.stdout if result.returncode == 0 else f"Error: {result.stderr}"
    except Exception as e:
        return f"Error: {str(e)}"

@tool
def install_mpv() -> str:
    """执行 scripts/install_mpv.py 来安装 mpv 播放器。注意：如果脚本需要 sudo 权限且等待密码，会导致超时（120秒）。在服务端不需要 mpv，只要能使用 API 的功能（如歌单管理/推荐）即可。"""
    try:
        result = subprocess.run(
            ["python3", "scripts/install_mpv.py"],
            capture_output=True,
            text=True,
            timeout=120
        )
        return result.stdout if result.returncode == 0 else f"Error: {result.stderr}"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out. This often happens if sudo is waiting for a password in a non-interactive shell. Skip mpv installation on the server."
    except Exception as e:
        return f"Error: {str(e)}"

@tool
def check_mpv_version() -> str:
    """检查是否安装了 mpv 播放器"""
    try:
        result = subprocess.run(
            ["mpv", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.stdout if result.returncode == 0 else f"Error: {result.stderr}"
    except Exception as e:
        return f"Error: {str(e)}"

@tool
def execute_ncm_command(args: list[str]) -> str:
    """执行 ncm-cli 命令，例如 args 为 ['search', 'song', '--keyword', 'xxx']，代表 ncm-cli search song --keyword xxx"""
    try:
        if not args:
            return "Error: Empty args provided."

        cmd = ["ncm-cli"] + args
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += f"\nError Output:\n{result.stderr}"
        if not output:
            output = f"Command executed successfully with no output."
        return output.strip()
    except subprocess.TimeoutExpired:
        return "Error: ncm-cli command timed out."
    except Exception as e:
        return f"Error executing ncm-cli: {str(e)}"

@tool
def schedule_ncm_cron(cron_expression: str, args: list[str]) -> str:
    """将一条新的定时任务追加到当前系统的 crontab 中。args 为要执行的命令列表，例如 ['ncm-cli', 'search', 'song', '--keyword', 'xxx'] 或 ['/usr/local/bin/node', '/path/to/main.js', '场景']"""
    # 校验 cron_expression，防止通过换行符等注入恶意 cron
    if '\n' in cron_expression or '\r' in cron_expression:
        return "Error: Newlines are not allowed in cron expression."

    if not re.match(r'^[\d\*\/\-\, ]+$', cron_expression):
        return "Error: Invalid cron expression format. Only digits, *, /, -, ,, and literal spaces are allowed."

    if not args:
        return "Error: Empty args provided."

    # 限制执行程序
    base_cmd = args[0]
    if base_cmd not in ["ncm-cli", "/usr/local/bin/node"]:
        return "Error: Unsupported cron command base. Only 'ncm-cli' and '/usr/local/bin/node' are allowed."

    try:
        # 1. 安全拼接命令
        command = shlex.join(args)

        # 2. 获取当前 crontab
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True
        )
        # 如果 crontab 不存在，crontab -l 会报错并返回非0退出码，此时 current_cron 应为空
        current_cron = result.stdout if result.returncode == 0 else ""
        if current_cron and not current_cron.endswith("\n"):
            current_cron += "\n"

        # 3. 拼装新任务
        new_job = f"{cron_expression} {command}\n"

        # 4. 将新的完整 crontab 写入
        process = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, text=True)
        process.communicate(input=current_cron + new_job)

        if process.returncode == 0:
            return "Cron job scheduled successfully."
        else:
            return "Error scheduling cron job."
    except Exception as e:
        return f"Error scheduling cron: {str(e)}"
