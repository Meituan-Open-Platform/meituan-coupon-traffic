# -*- coding: utf-8 -*-
"""
美团优惠领取工具（meituan-coupon-traffic）- 权益包发放脚本
接口：POST /eds/standard/equity/pkg/issue/claw
用法：python issue.py --token <user_token> --phone-masked <phone_masked>
"""

import argparse
import io
import sys

# Windows PowerShell 编码修复：确保输出 UTF-8 避免中文乱码
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── 常量 ──────────────────────────────────────────────────────────────
BASE_URL   = "https://peppermall.meituan.com"
ISSUE_PATH = "/eds/standard/equity/pkg/issue/claw"
# 任务类型 key（一期固定为 coupon，二期扩展时新增）
TASK_TYPE  = "coupon"

# subChannelCode 存放在独立配置文件中，不硬编码在此脚本
CONFIG_FILE = Path(__file__).parent / "config.json"


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
            save_history(old_data)
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


def save_history(data: dict):
    """保存本 Skill 的私有领券历史数据（使用 skill-cache write <skill> <file> --content <content> --type data）"""
    _cli_call("write", args=[SKILL_NAME, HISTORY_FILENAME, "--content", json.dumps(data, ensure_ascii=False)])


def load_config() -> dict:
    """加载 config.json，读取 subChannelCode 等敏感配置"""
    if not CONFIG_FILE.exists():
        print(json.dumps({
            "success": False,
            "error": "CONFIG_NOT_FOUND",
            "message": f"配置文件不存在：{CONFIG_FILE}，请联系管理员初始化"
        }, ensure_ascii=False))
        sys.exit(1)
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def gen_redeem_code(user_token: str, phone_masked: str, date_str: str) -> str:
    """
    生成当天领券唯一键
    规则：MD5(user_token + "_" + phone_masked + "_" + YYYYMMDD)

    说明：phone_masked 是脱敏手机号（如 152****0460），不同用户去掉中间4位后
    可能产生碰撞，因此在 MD5 原始串中额外加入 user_token 以保证唯一性。
    """
    raw = f"{user_token}_{phone_masked}_{date_str}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def save_redeem_code(sub_channel_code: str, user_token: str, date_str: str, redeem_code: str):
    """
    将兑换码写入历史文件。
    结构：
    {
      "<subChannelCode>": {
        "<user_token>": {
          "<YYYYMMDD>": {
            "coupon": ["code1", "code2"],   ← 一期；二期可新增其他 task_type key
            ...
          }
        }
      }
    }
    每次写入前检查是否已存在，避免重复追加。
    """
    history = load_history()
    channel_data = history.setdefault(sub_channel_code, {})
    token_data = channel_data.setdefault(user_token, {})
    date_data = token_data.setdefault(date_str, {})
    codes = date_data.setdefault(TASK_TYPE, [])
    if redeem_code not in codes:
        codes.append(redeem_code)
    save_history(history)


def format_timestamp_ms(ts_ms: int) -> str:
    """毫秒时间戳转可读日期"""
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
    """格式化单张券信息"""
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
    parser = argparse.ArgumentParser(description="美团权益包发放")
    parser.add_argument("--token", required=True, help="用户 user_token")
    parser.add_argument("--phone-masked", required=True, help="脱敏手机号（用于生成 redeem_code）")
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

    # 获取当天领券唯一键：优先复用历史记录，无则新生成（不提前写入，发券成功后再写）
    today = datetime.now().strftime("%Y%m%d")
    history = load_history()
    existing_codes = (
        history.get(sub_channel_code, {})
               .get(args.token, {})
               .get(today, {})
               .get(TASK_TYPE, [])
    )
    if existing_codes:
        # 当天已有领取记录，复用最后一个 equityPkgRedeemCode（避免重复生成）
        redeem_code = existing_codes[-1]
    else:
        # 当天首次领取，生成新的 equityPkgRedeemCode（发券成功后再写入历史文件）
        redeem_code = gen_redeem_code(args.token, args.phone_masked, today)

    # 构造请求
    body = {
        "subChannelCode": sub_channel_code,
        "token": args.token,
        "equityPkgRedeemCode": redeem_code
    }

    try:
        resp = httpx.post(
            BASE_URL + ISSUE_PATH,
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
    data = resp_data.get("data")

    # 错误码映射
    ERROR_MAP = {
        4009: ("ACTIVITY_ENDED", "活动已结束，暂时无法领取"),
        4010: ("ALREADY_RECEIVED", "你今天已经通过小美领取过美团权益了，明天再来哦～"),
        4011: ("QUOTA_EXHAUSTED", "抱歉，本次活动权益已发放完毕，下次早点来哦～"),
    }

    if code == 0:
        # 发券成功（code=0），保存兑换码到历史文件（首次领取时才写，复用历史 code 不重复写）
        is_first_issue = not bool(existing_codes)
        if is_first_issue:
            save_redeem_code(sub_channel_code, args.token, today, redeem_code)

        success_list = data.get("successEquityList", [])
        formatted_coupons = [format_coupon(e, lch=lch) for e in success_list]

        print(json.dumps({
            "success": True,
            "code": 0,
            "is_first_issue": is_first_issue,
            # is_first_issue=true  → 本次首次领取成功，向用户展示"🎉 领取成功！"
            # is_first_issue=false → 今日已领取过，不可重复领取，向用户展示：
            #   "⚠️ 今天已经领取过了，不能重复领取。以下是上次领取的券信息：" + coupons
            "redeem_code": redeem_code,
            "request_id": data.get("requestId", ""),
            "issue_status": data.get("equityPkgIssueStatus"),
            "coupon_count": len(formatted_coupons),
            "coupons": formatted_coupons
        }, ensure_ascii=False))

    elif code in ERROR_MAP:
        err_key, err_msg = ERROR_MAP[code]
        print(json.dumps({
            "success": False,
            "code": code,
            "error": err_key,
            "message": err_msg
        }, ensure_ascii=False))

    else:
        print(json.dumps({
            "success": False,
            "code": code,
            "error": "SYSTEM_ERROR",
            "message": f"系统繁忙，请稍后重试（错误码：{code}，{message}）"
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
