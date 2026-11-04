import asyncio
import csv
import os
import re
import shutil
from datetime import datetime, timedelta
from playwright.async_api import async_playwright

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

# ============ 配置 ============
URL_TEAM1 = "https://y.qq.com/tmead/promotion/h5/team-activity/detail?_hidehd=1&_miniplayer=1&adtag=img_share&singerId=6665073&activityId=17936311664035&searchid=568305526626555693,&p_share=waFlj7ebDqqbQF2OOC4PsiQYhkYZ9aIFBalaGNW5ISE&ADTAG=wxfshare&hosteuin=oiEq7e6k7Knqon**"
URL_POWER = "https://y.qq.com/tmead/promotion/h5/powering/1793152992875?_hidehd=1&_miniplayer=1&adtag=share_task&singerId=6665073&p_share=w2pZEizuC5V-xTHRIivoTwD_5f_DMRfGNgTtS7isP_4&hosteuin=oiEqow6FoiCA7n**&ADTAG=wxfshare"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, "power_data.csv")
CHART_FILE = os.path.join(BASE_DIR, "comparison_chart.png")
HISTORY_DIR = os.path.join(BASE_DIR, "history")
os.makedirs(HISTORY_DIR, exist_ok=True)


# ============ 抓取与存储 ============
def parse_num(text):
    if not text: return None
    m = re.search(r"[\d,]+", str(text))
    return int(m.group(0).replace(",", "")) if m else None


async def scrape_team(page, url):
    result = {"今日心动人数": None, "团建电力值": None}
    max_retries = 5  # 【升级】提升到 5 次重试

    for attempt in range(max_retries):
        try:
            print(f"🎯 第 {attempt + 1}/{max_retries} 次尝试抓取团建数据...")
            await page.goto(url, wait_until="domcontentloaded", timeout=90000)

            try:
                await page.wait_for_selector("text=本团今日心动", timeout=20000)
            except:
                pass

            await page.wait_for_timeout(3000)

            try:
                heart_ele = page.locator("text=本团今日心动").first
                parent_text = await heart_ele.evaluate("el => el.parentElement.innerText")
                result["今日心动人数"] = parse_num(parent_text)
            except:
                pass

            try:
                body_text = await page.locator("body").inner_text()
                matches = re.findall(r"(\d{1,3}(?:,\d{3})+)\s*/\s*(\d{1,3}(?:,\d{3})+)", body_text)
                if matches:
                    best = max(matches, key=lambda x: int(x[0].replace(",", "")))
                    result["团建电力值"] = int(best[0].replace(",", ""))
            except:
                pass

            if result["今日心动人数"] is not None and result["团建电力值"] is not None:
                print(f"✅ 团建数据抓取成功！心动: {result['今日心动人数']}, 电力: {result['团建电力值']}")
                return result
            else:
                print(f"⚠️ 第 {attempt + 1} 次抓取数据异常，准备重试...")
                await page.reload()
                await page.wait_for_timeout(10000) # 【升级】重试前多等 10 秒

        except Exception as e:
            print(f"⚠️ 第 {attempt + 1} 次抓取抛出异常: {e}")
            await page.wait_for_timeout(10000)

    return result


async def scrape_power(page):
    result = {"总电力值": None, "发电总人数": None}
    max_retries = 5  # 【升级】提升到 5 次重试

    for attempt in range(max_retries):
        try:
            print(f"🎯 第 {attempt + 1}/{max_retries} 次尝试抓取电力及人数...")
            await page.goto(URL_POWER, wait_until="domcontentloaded", timeout=90000)

            try:
                await page.wait_for_selector("body", timeout=15000)
            except:
                pass

            await page.wait_for_timeout(4000)

            try:
                body_text = await page.locator("body").inner_text()

                nums = re.findall(r"\d{1,3}(?:,\d{3})+", body_text)
                if nums:
                    result["总电力值"] = max(int(n.replace(",", "")) for n in nums)

                people_matches = re.search(r"发电总人数\s*([\d,]+)", body_text)
                if people_matches:
                    result["发电总人数"] = int(people_matches.group(1).replace(",", ""))
                else:
                    participate_matches = re.search(r"参与.*?([\d,]+)", body_text)
                    if participate_matches:
                        result["发电总人数"] = int(participate_matches.group(1).replace(",", ""))
            except Exception as parse_e:
                pass

            if result["总电力值"] is not None:
                print(f"✅ 成功！总电力: {result['总电力值']}, 发电总人数: {result['发电总人数']}")
                return result
            else:
                print(f"⚠️ 第 {attempt + 1} 次抓取异常，准备重试...")
                await page.reload()
                await page.wait_for_timeout(10000)

        except Exception as e:
            print(f"⚠️ 第 {attempt + 1} 次抓取总电力异常: {e}")
            await page.wait_for_timeout(10000)

    return result


def load_all_rows():
    if not os.path.exists(CSV_FILE): return [], []
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            with open(CSV_FILE, "r", encoding=enc, newline="") as f:
                content = list(csv.reader(f))
            return content[0], content[1:]
        except:
            continue
    return [], []


def parse_dt_loose(s):
    if not s: return None
    s = re.sub(r'(\d+[/-]\d+[/-]\d+)\s+(\d{1}):', r'\1 0\2:', s)
    s = s.strip().replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except:
            pass
    return None


def get_prev_hour_record(curr_dt, all_rows):
    def fmt_no_pad(dt_obj):
        return f"{dt_obj.year}/{dt_obj.month}/{dt_obj.day} {dt_obj.hour}"

    for i in range(1, 13):
        prev_hour_dt = curr_dt - timedelta(hours=i)
        prev_hour_str = fmt_no_pad(prev_hour_dt)

        if prev_hour_dt.day != curr_dt.day:
            break

        for row in reversed(all_rows):
            if not row or len(row) < 9: continue
            if row[0].startswith(prev_hour_str):
                return row
    return None


def append_csv(row_dict):
    file_exists = os.path.exists(CSV_FILE)
    header, all_rows = load_all_rows()
    curr_dt = datetime.strptime(row_dict["时间"], "%Y-%m-%d %H:%M:%S")

    if curr_dt.minute >= 50:
        curr_dt = curr_dt + timedelta(minutes=(60 - curr_dt.minute))

    formatted_time = f"{curr_dt.year}/{curr_dt.month}/{curr_dt.day} {curr_dt.hour:02d}:{curr_dt.minute:02d}"
    prev_row = get_prev_hour_record(curr_dt, all_rows)

    def calc_delta(curr_val, col_idx):
        if curr_val is None or prev_row is None: return ""
        try:
            prev_val_str = prev_row[col_idx]
            if prev_val_str == "" or prev_val_str is None: return ""
            return int(curr_val) - int(prev_val_str)
        except:
            return ""

    row = [
        formatted_time,
        row_dict["今日心动人数1"] or "", calc_delta(row_dict["今日心动人数1"], 1),
        row_dict["团建电力值1"] or "", calc_delta(row_dict["团建电力值1"], 3),
        row_dict["总电力值"] or "", calc_delta(row_dict["总电力值"], 5),
        row_dict["发电总人数"] or "", calc_delta(row_dict["发电总人数"], 7),
    ]

    with open(CSV_FILE, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(
                ["时间", "心动人数1", "增幅", "团建电力值1", "增幅", "总电力值", "增幅", "发电总人数", "增幅"])
        writer.writerow(row)
    print(f"✅ [{formatted_time}] 写入完成。\n")


# ============ 图表生成 ============
def to_float(v):
    try:
        return float(v) if v not in (None, "") else None
    except:
        return None


def fmt_w(v):
    if v is None: return ""
    sign = "-" if v < 0 else ""
    w = abs(v) / 10000.0
    return f"{sign}{int(round(w))}w" if abs(w - round(w)) < 1e-9 else f"{sign}{w:.1f}w"


def generate_chart(target_date, save_path, is_final=False):
    header, rows = load_all_rows()
    if not rows: return

    data_map = {}
    for r in rows:
        if len(r) < 9: continue
        dt = parse_dt_loose(r[0])
        if dt is None: continue

        target_date_str = dt.strftime('%Y-%m-%d')

        rec = {"dt": dt, "hour": dt.hour, "minute": dt.minute,
               "heart": to_float(r[1]), "heart_delta": to_float(r[2]),
               "team1": to_float(r[3]), "delta": to_float(r[4]),
               "totalPower": to_float(r[5]) if len(r) > 5 else None,
               "people": to_float(r[7]) if len(r) > 7 else None}

        if dt.hour == 0:
            data_map[f"{target_date_str}_0"] = rec
            continue

        key = f"{target_date_str}_{dt.hour}"
        data_map.setdefault(key, rec)

    today_str = target_date.strftime("%Y-%m-%d")
    yest_date = target_date - timedelta(days=1)
    yest_str = yest_date.strftime("%Y-%m-%d")
    next_str = (target_date + timedelta(days=1)).strftime("%Y-%m-%d")

    hours = list(range(0, 25))

    plt.rcParams["font.sans-serif"] = ["WenQuanYi Zen Hei", "Microsoft YaHei", "SimHei", "Arial Unicode MS",
                                       "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, axes = plt.subplots(4, 1, figsize=(14, 18), sharex=True)
    fig.suptitle(f"今天({target_date}) 数据总览", fontsize=20, fontweight="bold", color="#D35400", y=0.96)

    def plot_metric(ax, key, title, color):
        yest_vals, today_vals = [], []
        for h in hours:
            if h == 0:
                y_data, t_data = data_map.get(f"{yest_str}_0"), data_map.get(f"{today_str}_0")
            elif h == 24:
                y_data, t_data = data_map.get(f"{today_str}_0"), data_map.get(f"{next_str}_0")
            else:
                y_data, t_data = data_map.get(f"{yest_str}_{h}"), data_map.get(f"{today_str}_{h}")

            yest_vals.append(y_data[key] if y_data and y_data[key] is not None else float("nan"))
            today_vals.append(t_data[key] if t_data and t_data[key] is not None else float("nan"))

        ax.plot(hours, yest_vals, marker="o", linestyle="-", color="#FFB3C6", linewidth=2, markersize=5, label="昨天")
        ax.plot(hours, today_vals, marker="o", linestyle="-", color=color, linewidth=2.5, markersize=5, label="今天")

        ax.set_title(title, fontsize=14, fontweight="bold", color="#333")
        ax.set_ylabel(title, fontsize=10)
        ax.grid(axis='y', linestyle="--", alpha=0.3)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)

        for h, val in zip(hours, today_vals):
            if val is not None and not (isinstance(val, float) and val != val) and val != 0:
                ax.annotate(f'{int(val):,}', (h, val), textcoords="offset points", xytext=(0, -15), ha='center',
                            fontsize=7, color="#D35400", fontweight="bold")

    plot_metric(axes[0], 'heart', '心动人数趋势', '#FF8C42')
    plot_metric(axes[1], 'team1', '团建电力趋势', '#FF8C42')
    plot_metric(axes[2], 'totalPower', '总电力值趋势', '#333333')
    plot_metric(axes[3], 'people', '发电总人数趋势', '#D81B60')

    def time_formatter(x, pos):
        if x == 0: return "00:00"
        if x == 24: return "24:00"
        return f"{int(x):02d}:00"

    formatter = ticker.FuncFormatter(time_formatter)
    axes[-1].xaxis.set_major_formatter(formatter)
    axes[-1].xaxis.set_major_locator(ticker.MultipleLocator(2))
    axes[-1].set_xlabel("时段", fontsize=12)
    fig.autofmt_xdate(rotation=30, ha="right")

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"图表已生成：{save_path}")


# ============ 主流程 ============
async def run_once():
    now_bj = datetime.now() + timedelta(hours=8)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
            viewport={"width": 390, "height": 844},
            device_scale_factor=3,
            is_mobile=True,
            has_touch=True,
            locale="zh-CN",
            timezone_id="Asia/Shanghai"
        )

        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")

        page = await context.new_page()

        data = {"时间": now_bj.strftime("%Y-%m-%d %H:%M:%S")}
        curr_dt = now_bj

        t1 = await scrape_team(page, URL_TEAM1)
        data["今日心动人数1"], data["团建电力值1"] = t1["今日心动人数"], t1["团建电力值"]

        pwr = await scrape_power(page)
        data["总电力值"] = pwr["总电力值"]
        data["发电总人数"] = pwr["发电总人数"]
        await browser.close()

    if data["今日心动人数1"] is None and data["团建电力值1"] is None and data["总电力值"] is None:
        print("❌ 抓取失败：所有数据均为空，经过重试依然被拦截或超时。")
        return

    append_csv(data)

    try:
        chart_date = curr_dt
        if chart_date.minute >= 50:
            chart_date = chart_date + timedelta(minutes=(60 - chart_date.minute))

        today_date = chart_date.date()
        generate_chart(today_date, CHART_FILE)

        if curr_dt.hour == 23 and curr_dt.minute >= 50:
            archive_name = f"{today_date}.png"
            archive_path = os.path.join(HISTORY_DIR, archive_name)
            shutil.copy(CHART_FILE, archive_path)
            print(f"📁 已生成每日归档图片：{archive_path}")

    except Exception as e:
        print(f"生成图表失败: {e}")


async def main():
    print("定时任务已启动...")
    try:
        await run_once()
    except Exception as e:
        print(f"[抓取失败]: {e}")


if __name__ == "__main__":
    asyncio.run(main())