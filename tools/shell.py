import subprocess
import asyncio
import re
import os
import shlex
from langchain_core.tools import tool
from pydantic import BaseModel, Field

class ReadNcmConfigSchema(BaseModel):
    filename: str = Field(description="The name of the configuration file to read (e.g., ncm-preference.json)")

class WriteNcmConfigSchema(BaseModel):
    filename: str = Field(description="The name of the configuration file to write")
    content: str = Field(description="The content to write to the configuration file")

class ExecuteNcmCommandSchema(BaseModel):
    command_string: str = Field(description="The command string to execute, e.g., 'search song --keyword \"xxx\"'")

class ScheduleNcmCronSchema(BaseModel):
    cron_expression: str = Field(description="The cron expression for scheduling")
    command_string: str = Field(description="The command string to schedule, e.g., 'ncm-cli search song --keyword \"xxx\"' or '/usr/local/bin/node /path/to/main.js 场景'")

ALLOWED_NCM_CONFIG_FILES = {
    "ncm-preference.json",
    "ncm-history.json",
    "ncm-schedule.json"
}

def get_ncm_config_path() -> str:
    """获取 ncm 配置文件存放目录"""
    return os.path.expanduser("~/.config/ncm/")

@tool
async def install_ncm_cli() -> str:
    """执行 npm install -g @music163/ncm-cli 来安装网易云音乐 CLI 工具"""
    try:
        process = await asyncio.create_subprocess_exec(
            "npm", "install", "-g", "@music163/ncm-cli",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
        return stdout.decode() if process.returncode == 0 else f"Error: {stderr.decode()}"
    except asyncio.TimeoutError:
        return "Error: Command timed out after 120 seconds."
    except Exception as e:
        return f"Error: {str(e)}"

@tool
async def install_mpv() -> str:
    """执行 scripts/install_mpv.py 来安装 mpv 播放器。注意：如果脚本需要 sudo 权限且等待密码，会导致超时（120秒）。在服务端不需要 mpv，只要能使用 API 的功能（如歌单管理/推荐）即可。"""
    try:
        process = await asyncio.create_subprocess_exec(
            "python3", "scripts/install_mpv.py",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
        return stdout.decode() if process.returncode == 0 else f"Error: {stderr.decode()}"
    except asyncio.TimeoutError:
        return "Error: Command timed out. This often happens if sudo is waiting for a password in a non-interactive shell. Skip mpv installation on the server."
    except Exception as e:
        return f"Error: {str(e)}"

@tool
async def check_mpv_version() -> str:
    """检查是否安装了 mpv 播放器"""
    try:
        process = await asyncio.create_subprocess_exec(
            "mpv", "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
        return stdout.decode() if process.returncode == 0 else f"Error: {stderr.decode()}"
    except asyncio.TimeoutError:
        return "Error: Command timed out after 10 seconds."
    except Exception as e:
        return f"Error: {str(e)}"

@tool(args_schema=ReadNcmConfigSchema)
async def read_ncm_config(filename: str) -> str:
    """读取指定的 ncm 状态文件内容。允许的文件名: ncm-preference.json, ncm-history.json, ncm-schedule.json"""
    if filename not in ALLOWED_NCM_CONFIG_FILES:
        return f"Error: Access denied. Allowed files are {', '.join(ALLOWED_NCM_CONFIG_FILES)}"

    filepath = os.path.join(get_ncm_config_path(), filename)
    if not os.path.exists(filepath):
        return f"File {filename} does not exist yet."

    try:
        def _read():
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()
        return await asyncio.to_thread(_read)
    except Exception as e:
        return f"Error reading file {filename}: {str(e)}"

@tool(args_schema=WriteNcmConfigSchema)
async def write_ncm_config(filename: str, content: str) -> str:
    """覆盖写入内容到指定的 ncm 状态文件。允许的文件名: ncm-preference.json, ncm-history.json, ncm-schedule.json"""
    if filename not in ALLOWED_NCM_CONFIG_FILES:
        return f"Error: Access denied. Allowed files are {', '.join(ALLOWED_NCM_CONFIG_FILES)}"

    config_dir = get_ncm_config_path()
    filepath = os.path.join(config_dir, filename)

    try:
        def _write():
            os.makedirs(config_dir, exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
        await asyncio.to_thread(_write)
        return f"File {filename} written successfully."
    except Exception as e:
        return f"Error writing file {filename}: {str(e)}"

async def _drain_stream(stream):
    """消耗后台进程的输出流以防管道阻塞死锁"""
    try:
        while True:
            line = await stream.readline()
            if not line:
                break
    except Exception:
        pass

@tool
async def get_ncm_login_qrcode() -> str:
    """获取网易云音乐登录的二维码链接。直接调用该工具，它会自动在后台启动 ncm-cli 扫码登录流程并轮询，并将生成的 qrcode 链接返回给你。请将该链接直接发送给用户，让用户在浏览器打开或者扫码。"""
    try:
        env = os.environ.copy()
        env["FORCE_COLOR"] = "0"

        # 异步启动进程，不阻塞事件循环
        process = await asyncio.create_subprocess_exec(
            "ncm-cli", "login",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env
        )

        login_url = ""
        try:
            # 只用 10 秒时间抓取 URL，避免一直等待
            start_time = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - start_time < 10:
                # 尝试通过异步读取一行，最多等 1 秒
                try:
                    line_bytes = await asyncio.wait_for(process.stdout.readline(), timeout=1.0)
                except asyncio.TimeoutError:
                    if process.returncode is not None:
                        break # 进程退出了
                    continue

                if not line_bytes:
                    break

                line = line_bytes.decode(errors="ignore")
                match = re.search(r'(https?://music\.163\.com[^\s\x1b]+)', line)
                if match:
                    login_url = match.group(1)
                    break
        except Exception:
            pass

        if not login_url:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            return "Failed to extract login QR code URL within 10 seconds. Network might be unreachable."

        # 如果拿到了 URL，启动后台协程继续读取其输出，防止挂起，并让后台进程继续等扫码
        asyncio.create_task(_drain_stream(process.stdout))

        return f"Successfully retrieved login URL. Background polling process is running. Please ask the user to scan or open this link immediately: {login_url}"
    except Exception as e:
        return f"Error retrieving login QR code: {str(e)}"

@tool
async def get_ncm_cron() -> str:
    """获取当前系统中的 crontab 列表，用于检查是否已经有重复任务或管理调度。"""
    try:
        process = await asyncio.create_subprocess_exec(
            "crontab", "-l",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        return stdout.decode().strip() if process.returncode == 0 else "No crontab for current user."
    except Exception as e:
        return f"Error reading crontab: {str(e)}"

@tool(args_schema=ExecuteNcmCommandSchema)
async def execute_ncm_command(command_string: str) -> str:
    """执行 ncm-cli 命令。你只需要提供具体的参数字符串，例如：'search song --keyword "xxx"'，本工具会自动在前面补齐 'ncm-cli ' 并执行。"""
    try:
        if not command_string or not command_string.strip():
            return "Error: Empty command_string provided."

        command_args = shlex.split(command_string)
        cmd = ["ncm-cli"] + command_args

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
        except asyncio.TimeoutError:
            process.kill()
            return "Error: ncm-cli command timed out."

        output = ""
        if stdout:
            output += stdout.decode(errors="ignore")
        if stderr:
            output += f"\nError Output:\n{stderr.decode(errors='ignore')}"
        if not output:
            output = f"Command executed successfully with no output."
        return output.strip()
    except Exception as e:
        return f"Error executing ncm-cli: {str(e)}"

@tool(args_schema=ScheduleNcmCronSchema)
async def schedule_ncm_cron(cron_expression: str, command_string: str) -> str:
    """将一条新的定时任务追加到当前系统的 crontab 中。command_string 为要执行的完整命令字符串，例如：'ncm-cli search song --keyword "xxx"' 或 '/usr/local/bin/node /path/to/main.js 场景'"""
    # 校验 cron_expression，防止通过换行符等注入恶意 cron
    if '\n' in cron_expression or '\r' in cron_expression:
        return "Error: Newlines are not allowed in cron expression."

    if not re.match(r'^[\d\*\/\-\, ]+$', cron_expression):
        return "Error: Invalid cron expression format. Only digits, *, /, -, ,, and literal spaces are allowed."

    if not command_string or not command_string.strip():
        return "Error: Empty command_string provided."

    command_args = shlex.split(command_string)
    if not command_args:
        return "Error: Could not parse command_string."

    # 校验 command_args 中的每一项，防止任何参数中包含换行符导致 crontab 文件格式注入漏洞
    for arg in command_args:
        if '\n' in arg or '\r' in arg:
            return "Error: Newlines are not allowed in cron arguments."

    # 限制执行程序
    base_cmd = command_args[0]
    if base_cmd not in ["ncm-cli", "/usr/local/bin/node"]:
        return "Error: Unsupported cron command base. Only 'ncm-cli' and '/usr/local/bin/node' are allowed."

    try:
        # 1. 安全拼接命令
        command = shlex.join(command_args)

        # 2. 获取当前 crontab
        process = await asyncio.create_subprocess_exec(
            "crontab", "-l",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await process.communicate()

        # 如果 crontab 不存在，crontab -l 会报错并返回非0退出码，此时 current_cron 应为空
        current_cron = stdout.decode() if process.returncode == 0 else ""
        if current_cron and not current_cron.endswith("\n"):
            current_cron += "\n"

        # 3. 拼装新任务
        new_job = f"{cron_expression} {command}\n"

        # 4. 将新的完整 crontab 写入
        write_process = await asyncio.create_subprocess_exec(
            "crontab", "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await write_process.communicate(input=(current_cron + new_job).encode())

        if write_process.returncode == 0:
            return "Cron job scheduled successfully."
        else:
            return "Error scheduling cron job."
    except Exception as e:
        return f"Error scheduling cron: {str(e)}"
