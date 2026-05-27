"""
fetch_emails.py — 从 IMAP 拉取指定日期范围的邮件

用法:
  python fetch_emails.py [--days N] [--output FILE]
  python fetch_emails.py --weekly --output FILE

参数:
  --days N      拉取最近 N 天（默认 1，即今天）
  --weekly      拉取本周（周一到今天）
  --output FILE 输出 JSON 文件路径（默认 stdout）

环境变量（必填）:
  DAILY_REPORT_IMAP_HOST  IMAP 服务器地址
  DAILY_REPORT_EMAIL      邮箱地址
  DAILY_REPORT_PASS       邮箱密码或授权码

环境变量（可选）:
  DAILY_REPORT_IMAP_PORT  IMAP 端口（默认 993）
  DAILY_REPORT_DIR        报告存放目录（默认 ./Daily Report）
"""

import argparse
import datetime
import email
import email.header
import imaplib
import json
import os
import ssl
import sys

# ── 配置（全部从环境变量读取，不含任何硬编码默认值）───────────
IMAP_HOST = os.environ.get("DAILY_REPORT_IMAP_HOST", "")
IMAP_PORT = int(os.environ.get("DAILY_REPORT_IMAP_PORT", "993"))
EMAIL_USER = os.environ.get("DAILY_REPORT_EMAIL", "")
EMAIL_PASS = os.environ.get("DAILY_REPORT_PASS", "")
OUTPUT_DIR = os.environ.get("DAILY_REPORT_DIR", "./Daily Report")

# ── 启动检查：缺少必填环境变量则快速失败 ───────────────────────────
def _check_env():
    missing = [k for k in ("DAILY_REPORT_IMAP_HOST", "DAILY_REPORT_EMAIL", "DAILY_REPORT_PASS") if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"缺少必需的环境变量: {', '.join(missing)}\n请设置后再运行。")


def decode_header_str(s):
    """解码 email 头部的字符串（如 Subject、From）"""
    if s is None:
        return ""
    parts = email.header.decode_header(s)
    result = []
    for raw, enc in parts:
        if isinstance(raw, bytes):
            result.append(raw.decode(enc or "utf-8", errors="replace"))
        else:
            result.append(raw)
    return "".join(result)


def get_body(msg):
    """提取邮件纯文本正文，忽略附件和 HTML"""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if disp.startswith("attachment"):
                continue
            if ct == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode(charset, errors="replace")
                    break
    else:
        ct = msg.get_content_type()
        if ct == "text/plain":
            charset = msg.get_content_charset() or "utf-8"
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode(charset, errors="replace")
    # 截断过长正文，保留前 3000 字符
    return body[:3000].strip()


def fetch_emails(user, password, since_date, before_date):
    """连接 IMAP，拉取指定日期范围的邮件，返回列表"""
    ctx = ssl.create_default_context()
    mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=ctx)
    mail.login(user, password)
    mail.select("INBOX")

    # 搜索：SINCE <date> BEFORE <date>
    since_str = since_date.strftime("%d-%b-%Y")
    before_str = before_date.strftime("%d-%b-%Y")
    status, msg_ids = mail.search(None, f'SINCE "{since_str}" BEFORE "{before_str}"')

    if status != "OK":
        mail.logout()
        raise RuntimeError(f"IMAP search failed: {status}")

    ids = msg_ids[0].split()
    print(f"Found {len(ids)} emails between {since_date} and {before_date}", file=sys.stderr)

    emails = []
    for uid in ids:
        status, data = mail.fetch(uid, "(RFC822)")
        if status != "OK":
            continue
        raw = data[0][1]
        msg = email.message_from_bytes(raw)
        emails.append({
            "from": decode_header_str(msg.get("From", "")),
            "subject": decode_header_str(msg.get("Subject", "")),
            "date": msg.get("Date", ""),
            "body": get_body(msg),
        })

    mail.logout()
    return emails


def main():
    _check_env()
    parser = argparse.ArgumentParser(description="拉取 IMAP 邮件")
    parser.add_argument("--days", type=int, default=1, help="拉取最近 N 天（默认 1）")
    parser.add_argument("--weekly", action="store_true", help="拉取本周（周一至今）")
    parser.add_argument("--output", "-o", help="输出 JSON 文件路径")
    args = parser.parse_args()

    today = datetime.date.today()

    if args.weekly:
        # 本周一
        since = today - datetime.timedelta(days=today.weekday())
        since_dt = datetime.datetime.combine(since, datetime.time.min)
        before_dt = datetime.datetime.combine(today, datetime.time.max)
        period_label = f"{today.year} 第{today.isocalendar()[1]}周"
    else:
        since = today - datetime.timedelta(days=args.days - 1)
        since_dt = datetime.datetime.combine(since, datetime.time.min)
        before_dt = datetime.datetime.combine(today, datetime.time.max)
        period_label = since.strftime("%Y-%m-%d") if args.days == 1 else f"{since} 至 {today}"

    emails = fetch_emails(EMAIL_USER, EMAIL_PASS, since, today + datetime.timedelta(days=1))

    result = {
        "period": period_label,
        "email_count": len(emails),
        "emails": emails,
    }

    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        out_path = os.path.join(OUTPUT_DIR, args.output)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Saved to {out_path}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
