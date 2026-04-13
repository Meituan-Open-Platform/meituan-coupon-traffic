# -*- coding: utf-8 -*-
"""
美团优惠领取工具（meituan-coupon-traffic）- 用户领券记录查询脚本
接口：POST /eds/standard/equity/pkg/claw/result/query
用法：
  python query.py --token <user_token> --dates 20260323         # 查单天
  python query.py --token <user_token> --dates 20260320,20260323 # 查区间（含首尾）
"""

import argparse
import io
import sys

# Windows PowerShell 编码修复：确保输出 UTF-8 避免中文乱码
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ── 常量 ──────────────────────────────────────────────────────────────
BASE_URL    = "https://peppermall.meituan.com"
QUERY_PATH  = "/eds/standard/equity/pkg/claw/result/query"
# 任务类型 key（一期固定为 coupon）
TASK_TYPE   = "coupon"

CONFIG_FILE  = Path(__file__).parent / "config.json"


def _get_cli_path() -> Path:
    """获取 skill_cache_cli.py 路径（本地优先）"""
    env_path = os.environ.get("SKILL_CACHE_CLI_PATH")
    if env_path:
        return Path(env_path)
    return Path(__file__).parent / "skill_cache_cli.py"


def _get_python_exe() -> str:
    """获取 Python 执行路径"""
    env_python = os.environ.get("SKILL_CACHE_PYTHON")
    if env_python:
        return env_python
    return sys.executable


def _get_workspace() -> str:
    """
    获取工作空间路径

    优先级：
    1. SKILL_CACHE_WORKSPACE 环境变量
    2. CLAUDE_WORKSPACE 环境变量
    3. XIAOMEI_WORKSPACE 环境变量
    4. 默认 ~/.xiaomei-workspace（与 skill_cache_cli.py 兼容）

    注意：如果目录不存在会自动创建
    """
    workspace = os.environ.get("SKILL_CACHE_WORKSPACE") \
        or os.environ.get("CLAUDE_WORKSPACE") \
        or os.environ.get("XIAOMEI_WORKSPACE") \
        or str(Path.home() / ".xiaomei-workspace")

    # 确保目录存在（兼容首次运行的纯净环境）
    Path(workspace).mkdir(parents=True, exist_ok=True)
    return workspace


def _cli_call(command: str, subcommand: str = None, args: list = None, raw_output: bool = False) -> dict:
    """调用 mt-ug-ods-skill-cache CLI"""
    args = args or []
    cmd = [_get_python_exe(), str(_get_cli_path()), command]
    if subcommand:
        cmd.append(subcommand)
    cmd.extend(args)

    env = os.environ.copy()
    env.setdefault("SKILL_CACHE_WORKSPACE", _get_workspace())

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        stdout = result.stdout.strip() if result.stdout else ""

        if raw_output:
            return {"success": True, "content": stdout}

        if stdout:
            try:
                return json.loads(stdout)
            except json.JSONDecodeError:
                return {"success": True, "content": stdout}
        return {"success": False, "error": "Empty output"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# Skill 私有数据管理（使用 mt-ug-ods-skill-cache CLI）
SKILL_NAME = "meituan-coupon-traffic"
HISTORY_FILENAME = "mt_ods_coupon_history.json"

# 旧版历史文件路径（用于兼容迁移）
OLD_HISTORY_FILE = Path.home() / ".xiaomei-workspace" / "mt_ods_coupon_history.json"


def _migrate_old_history() -> dict:
    """检查并迁移旧版历史文件到新位置"""
    if OLD_HISTORY_FILE.exists():
        try:
            with open(OLD_HISTORY_FILE, encoding="utf-8") as f:
                old_data = json.load(f)
            # 将旧数据写入新位置（保持旧文件内容和名字不变）
            _cli_call("write", args=[SKILL_NAME, HISTORY_FILENAME, "--content", json.dumps(old_data, ensure_ascii=False)])
            return old_data
        except Exception:
            pass  # 迁移失败返回空
    return {}


def load_history() -> dict:
    """加载本 Skill 的私有领券历史数据（自动处理旧版迁移）"""
    # 先尝试从新位置读取（使用 skill-cache read <skill> <file> --type data）
    result = _cli_call("read", args=[SKILL_NAME, HISTORY_FILENAME])
    if result and isinstance(result, dict):
        # skill_cache_cli read 返回裸 JSON（文件内容本身），不含 success 字段
        if result.get("success") is not None:
            # 包装格式（有 success 字段）
            content = result.get("content")
            if content:
                try:
                    return json.loads(content) if isinstance(content, str) else content
                except json.JSONDecodeError:
                    pass
        elif "error" not in result:
            # 裸 JSON 格式（直接就是 history 数据）
            return result

    # 新位置没有数据，尝试迁移旧文件
    migrated = _migrate_old_history()
    if migrated:
        return migrated

    return {}


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        print(json.dumps({
            "success": False,
            "error": "CONFIG_NOT_FOUND",
            "message": f"配置文件不存在：{CONFIG_FILE}"
        }, ensure_ascii=False))
        sys.exit(1)
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def get_date_range(date_str: str) -> list[str]:
    """
    解析日期参数，返回日期列表（YYYYMMDD 格式）
    - 单日期："20260323" → ["20260323"]
    - 区间："20260320,20260323" → ["20260320", "20260321", "20260322", "20260323"]
    """
    parts = [p.strip() for p in date_str.split(",")]
    if len(parts) == 1:
        return [parts[0]]
    elif len(parts) == 2:
        start = datetime.strptime(parts[0], "%Y%m%d")
        end = datetime.strptime(parts[1], "%Y%m%d")
        if start > end:
            start, end = end, start
        result = []
        cur = start
        while cur <= end:
            result.append(cur.strftime("%Y%m%d"))
            cur += timedelta(days=1)
        return result
    else:
        print(json.dumps({
            "success": False,
            "error": "INVALID_DATE_FORMAT",
            "message": f"日期格式错误：{date_str}，请输入单个日期（20260323）或区间（20260320,20260323）"
        }, ensure_ascii=False))
        sys.exit(1)


def get_redeem_codes_by_dates(sub_channel_code: str, user_token: str, dates: list[str]) -> list[str]:
    """
    从历史文件中获取指定渠道、用户、日期范围内的 coupon 兑换码列表。
    路径：history[subChannelCode][user_token][date][TASK_TYPE]
    """
    history = load_history()
    token_data = history.get(sub_channel_code, {}).get(user_token, {})
    codes = []
    for date in dates:
        date_codes = token_data.get(date, {}).get(TASK_TYPE, [])
        codes.extend(date_codes)
    # 去重，保持顺序
    seen = set()
    unique_codes = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            unique_codes.append(c)
    return unique_codes


def format_timestamp_ms(ts_ms: int) -> str:
    if not ts_ms:
        return "-"
    try:
        return datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")
    except Exception:
        return str(ts_ms)


def append_lch_param(url: str, lch: str) -> str:
    """
    在跳转链接后拼接 lch 参数

    - lch 为空/None → 原样返回
    - url 已有参数（含 ?）→ 追加 &lch=xxx
    - url 无参数 → 追加 ?lch=xxx
    """
    if not lch or not url:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}lch={lch}"


def format_coupon(equity: dict, lch: str = "") -> dict:
    price_limit_type = equity.get("priceLimitType", 1)
    price_limit_amount_str = equity.get("priceLimitAmountYuanStr", "")
    discount_amount_str = equity.get("discountAmountYuanStr", "")

    if price_limit_type == 1:
        use_condition = "无门槛"
    elif price_limit_type in (2, 3):
        use_condition = f"满{price_limit_amount_str}元可用"
    else:
        use_condition = f"满{price_limit_amount_str}元可用" if price_limit_amount_str else "-"

    jump_url = append_lch_param(equity.get("jumpUrl", ""), lch)

    return {
        "name": equity.get("userEquityName", "-"),
        "discount_amount": discount_amount_str,
        "use_condition": use_condition,
        "valid_start": format_timestamp_ms(equity.get("beginTime")),
        "valid_end": format_timestamp_ms(equity.get("endTime")),
        "issue_time": format_timestamp_ms(equity.get("issueTime")),
        "jump_url": jump_url,
        "user_equity_id": equity.get("userEquityId", "")
    }


def main():
    parser = argparse.ArgumentParser(description="美团权益领取记录查询")
    parser.add_argument("--token", required=True, help="用户 user_token")
    parser.add_argument("--dates", required=True,
                        help="查询日期，单天如 20260323，区间如 20260320,20260323")
    args = parser.parse_args()

    import httpx

    config = load_config()
    sub_channel_code = config.get("subChannelCode")
    lch = config.get("lch", "")
    if not sub_channel_code:
        print(json.dumps({
            "success": False,
            "error": "CONFIG_INVALID",
            "message": "配置文件缺少 subChannelCode 字段"
        }, ensure_ascii=False))
        sys.exit(1)

    # 解析日期范围
    dates = get_date_range(args.dates)

    # 从历史文件获取兑换码
    redeem_codes = get_redeem_codes_by_dates(sub_channel_code, args.token, dates)

    if not redeem_codes:
        print(json.dumps({
            "success": True,
            "code": 0,
            "query_dates": dates,
            "redeem_code_count": 0,
            "records": [],
            "message": f"在 {dates[0]}{'~' + dates[-1] if len(dates) > 1 else ''} 期间未找到领取记录（本地无兑换码存档）"
        }, ensure_ascii=False))
        return

    # 构造请求
    body = {
        "subChannelCode": sub_channel_code,
        "token": args.token,
        "equityPkgRedeemCodeList": redeem_codes
    }

    try:
        resp = httpx.post(
            BASE_URL + QUERY_PATH,
            json=body,
            headers={"Content-Type": "application/json"},
            timeout=15,
            verify=True
        )
        resp_data = resp.json()
    except httpx.TimeoutException:
        print(json.dumps({
            "success": False,
            "error": "TIMEOUT",
            "message": "请求超时，请稍后重试"
        }, ensure_ascii=False))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": "NETWORK_ERROR",
            "message": f"网络异常：{str(e)}"
        }, ensure_ascii=False))
        sys.exit(1)

    code = resp_data.get("code")
    message = resp_data.get("message", "")
    data = resp_data.get("data", [])

    if code == 0:
        # 格式化每条记录
        records = []
        for item in (data or []):
            redeem_code = item.get("equityRedeemCode", "")
            success_list = item.get("successEquityList", [])
            records.append({
                "redeem_code": redeem_code,
                "coupon_count": len(success_list),
                "coupons": [format_coupon(e, lch=lch) for e in success_list]
            })

        print(json.dumps({
            "success": True,
            "code": 0,
            "query_dates": dates,
            "redeem_code_count": len(redeem_codes),
            "record_count": len(records),
            "records": records
        }, ensure_ascii=False))
    else:
        print(json.dumps({
            "success": False,
            "code": code,
            "error": "API_ERROR",
            "message": f"查询失败（错误码：{code}，{message}）"
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
