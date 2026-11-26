#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
codex-repair: 只读诊断 Codex 日志库 (logs_2.sqlite)
用法:
  python diagnose_logs.py                     # 默认: 最近 ERROR/WARN + 按天统计
  python diagnose_logs.py --kw "MCP server startup failed"
  python diagnose_logs.py --kw 429 --kw "request timed out" --days 7
  python diagnose_logs.py --since 456661      # 只查某个 id 之后的新日志
说明:
  - 全程只读打开 (mode=ro)，不会修改任何文件。
  - 日志库文件名可能随版本变化 (logs_1/2/3.sqlite)，自动探测最新一个。
  - feedback_log_body 前面的 tracing 前缀可读性差，输出时截断到最后一个 "}:" 之后。
"""
import argparse
import datetime as dt
import os
import sqlite3
import sys

HOME = os.path.expanduser("~")
CODEX_HOME = os.environ.get("CODEX_HOME", os.path.join(HOME, ".codex"))


def find_log_db():
    """找到最新的 logs_N.sqlite"""
    cands = []
    for f in os.listdir(CODEX_HOME):
        if f.startswith("logs_") and f.endswith(".sqlite"):
            p = os.path.join(CODEX_HOME, f)
            cands.append((os.path.getmtime(p), p))
    if not cands:
        print("未找到 logs_*.sqlite，请确认 CODEX_HOME 路径:", CODEX_HOME, file=sys.stderr)
        sys.exit(1)
    cands.sort(reverse=True)
    return cands[0][1]


def short(body, n=200):
    if not body:
        return ""
    # 去掉冗长的 tracing 前缀
    tail = body.split("}:").pop()
    return tail.strip().replace("\n", " ")[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kw", action="append", default=[], help="关键词，可多次传")
    ap.add_argument("--days", type=int, default=0, help="只看最近 N 天(0=全部)")
    ap.add_argument("--since", type=int, default=0, help="只看 id 大于此值的日志")
    ap.add_argument("--limit", type=int, default=25, help="每条查询最多输出行数")
    ap.add_argument("--levels", default="ERROR,WARN", help="逗号分隔的 level 列表")
    args = ap.parse_args()

    db = find_log_db()
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    cur = con.cursor()
    print("== 日志库:", db)
    print("== 表:", [r[0] for r in cur.execute("select name from sqlite_master where type='table'")])

    where = []
    params = []
    if args.since:
        where.append("id > ?")
        params.append(args.since)
    if args.days:
        where.append("ts >= ?")
        params.append(int(dt.datetime.now().timestamp()) - args.days * 86400)
    # 追加条件（不含 where 关键字，避免与 level/like 条件重复）
    w = (" and " + " and ".join(where)) if where else ""

    # 1) 按天统计 ERROR/WARN
    print("\n== 按天 ERROR/WARN 数量 (近14天) ==")
    for r in cur.execute(
        "select date(ts,'unixepoch','localtime') d, count(*) from logs "
        "where level in ('ERROR','WARN') and ts >= ? group by d order by d desc limit 14",
        (int(dt.datetime.now().timestamp()) - 14 * 86400,),
    ):
        print(" ", r[0], r[1])

    # 2) 最近 ERROR/WARN 明细
    levels = [l.strip() for l in args.levels.split(",") if l.strip()]
    ph = ",".join("?" * len(levels))
    print(f"\n== 最近 {args.limit} 条 {levels} ==")
    for r in cur.execute(
        f"select id,ts,level,target,feedback_log_body from logs where level in ({ph}) {w} "
        f"order by id desc limit {args.limit}",
        levels + params,
    ):
        print(f"  [{r[0]}] {dt.datetime.fromtimestamp(r[1]):%m-%d %H:%M:%S} {r[2]:<5} {r[3]} | {short(r[4], 240)}")

    # 3) 关键词命中（按天统计 + 最近明细）
    for kw in args.kw:
        print(f"\n== 关键词 '{kw}' 按天统计 (近14天) ==")
        for r in cur.execute(
            "select date(ts,'unixepoch','localtime') d, count(*) from logs "
            "where feedback_log_body like ? and ts >= ? group by d order by d desc limit 14",
            ("%" + kw + "%", int(dt.datetime.now().timestamp()) - 14 * 86400),
        ):
            print(" ", r[0], r[1])
        print(f"== 关键词 '{kw}' 最近 {args.limit} 条 ==")
        for r in cur.execute(
            f"select id,ts,level,target,feedback_log_body from logs "
            f"where feedback_log_body like ? {w} order by id desc limit {args.limit}",
            ("%" + kw + "%",) + tuple(params),
        ):
            print(f"  [{r[0]}] {dt.datetime.fromtimestamp(r[1]):%m-%d %H:%M:%S} {r[2]:<5} {r[3]} | {short(r[4], 240)}")

    con.close()


if __name__ == "__main__":
    main()
