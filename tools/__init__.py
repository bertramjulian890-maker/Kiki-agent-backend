from .search import fake_weather_search
from .shell import (
    install_ncm_cli,
    install_mpv,
    check_mpv_version,
    get_ncm_login_qrcode,
    get_ncm_cron,
    execute_ncm_command,
    schedule_ncm_cron,
    read_ncm_config,
    write_ncm_config
)

# 向外暴露所有供 LLM 调用的工具
TOOLS = [
    fake_weather_search,
    install_ncm_cli,
    install_mpv,
    check_mpv_version,
    execute_ncm_command,
    get_ncm_login_qrcode,
    get_ncm_cron,
    schedule_ncm_cron,
    read_ncm_config,
    write_ncm_config
]
