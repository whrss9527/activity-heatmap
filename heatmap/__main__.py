"""python3 -m heatmap sync | render | import

    sync    merge what the Shortcut sent (env HEALTH_TIME / HEALTH_VALUE), then draw
    render  only draw
    import  fill missing days from GitHubPoster's IN_FOLDER/apple_history.json, then draw
"""

import argparse
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from . import ingest, render


def summarize(markdown):
    """Print, and add to the Actions job summary when running in a workflow."""
    print(markdown)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as summary:
            summary.write(markdown + "\n")


def levels(text):
    cuts = [int(cut) for cut in text.split(",")] if all(cut.strip().isdigit() for cut in text.split(",")) else []
    if len(cuts) != 3 or not 0 < cuts[0] < cuts[1] < cuts[2]:
        raise argparse.ArgumentTypeError("要三个递增的正整数，如 400,500,800")
    return cuts


def preview(text, limit=300):
    text = (text or "").replace("\n", "⏎")
    return text if len(text) <= limit else text[:limit] + f"…（共 {len(text)} 字）"


def main(argv=None):
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data", type=Path, default=Path("data/activity.json"), help="历史数据（默认 data/activity.json）")
    common.add_argument("--out", type=Path, default=Path("heatmap.svg"), help="输出的 SVG（默认 heatmap.svg）")
    common.add_argument("--tz", default="Asia/Shanghai", help="按哪个时区划分日子（默认 Asia/Shanghai）")
    common.add_argument("--years", type=int, default=0, help="只画最近几年，默认全部")
    common.add_argument("--levels", type=levels, help="三个分档阈值，如 400,500,800；默认按历史数据自动取")
    common.add_argument("--title", default="活动能量", help="卡片标题")

    parser = argparse.ArgumentParser(prog="python3 -m heatmap", description="Apple 健康活动能量热力图")
    commands = parser.add_subparsers(dest="command", required=True)
    sync = commands.add_parser("sync", parents=[common], help="合并快捷指令发来的样本，再生成热力图")
    sync.add_argument("--time", default=os.environ.get("HEALTH_TIME", ""), help="样本日期列表（默认读 HEALTH_TIME）")
    sync.add_argument("--value", default=os.environ.get("HEALTH_VALUE", ""), help="样本数值列表（默认读 HEALTH_VALUE）")
    commands.add_parser("render", parents=[common], help="只生成热力图")
    legacy = commands.add_parser("import", parents=[common], help="从 GitHubPoster 的 apple_history.json 补齐缺的日子")
    legacy.add_argument("legacy", type=Path)
    args = parser.parse_args(argv)

    tz = ZoneInfo(args.tz)
    today = ingest.local_today(tz)
    series = ingest.load(args.data)

    if args.command == "sync":
        try:
            samples = ingest.parse(args.time, args.value, tz)
        except ingest.PayloadError as error:
            summarize(f"❌ 快捷指令发来的数据没法解析：{error}\n\n```\ntime:  {preview(args.time)}\nvalue: {preview(args.value)}\n```")
            return 1
        summarize(ingest.report(ingest.merge(series, samples), today))
        ingest.save(args.data, series)
    elif args.command == "import":
        added = ingest.import_legacy(series, args.legacy)
        ingest.save(args.data, series)
        print(f"补齐了 {added} 天，现在共 {len(series)} 天")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        render.render(series, years=args.years, levels=args.levels, title=args.title, today=today), encoding="utf-8"
    )
    print(f"已生成 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
