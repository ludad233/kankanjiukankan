import asyncio
import csv
import os
import re
from datetime import datetime, timedelta
from playwright.async_api import async_playwright

# ============ 配置 ============
URL_POWER = "https://y.qq.com/tmead/promotion/h5/powering/1793152992875?_hidehd=1&_miniplayer=1&adtag=share_task&singerId=6665073&p_share=w2pZEizuC5V-xTHRIivoTwD_5f_DMRfGNgTtS7isP_4&hosteuin=oiEqow6FoiCA7n**&ADTAG=wxfshare"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, "power_data.csv")


# ============ 抓取与存储 ============
async def scrape_power(page):
    result = {"总电力值": None, "发电总人数": None}
    max_retries = 5

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


def get_prev_hour_record(curr_dt, all_rows):
    def fmt_no_pad(dt_obj):
        return f"{dt_obj.year}/{dt_obj.month}/{dt_obj.day} {dt_obj.hour}"

    for i in range(1, 26):
        prev_hour_dt = curr_dt - timedelta(hours=i)
        prev_hour_str = fmt_no_pad(prev_hour_dt)

        for row in reversed(all_rows):
            if not row or len(row) < 9:
                continue
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

    def calc_delta(curr_val, col_idx, heart_special=False):
        if curr_val is None: return ""
        if heart_special and curr_dt.hour == 1: return int(curr_val)
        if prev_row is None: return ""
        try:
            prev_val_str = prev_row[col_idx]
            if prev_val_str == "" or prev_val_str is None: return ""
            return int(curr_val) - int(prev_val_str)
        except:
            return ""

    # 团建数据留空
    heart_delta = ""
    power_delta = ""

    # 抓取的总电和人数正常计算增幅
    total_delta = calc_delta(row_dict["总电力值"], 5, heart_special=False)
    people_delta = calc_delta(row_dict["发电总人数"], 7, heart_special=False)

    row = [
        formatted_time,
        "", heart_delta,
        "", power_delta,
        row_dict["总电力值"] or "", total_delta,
        row_dict["发电总人数"] or "", people_delta,
    ]

    with open(CSV_FILE, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(
                ["时间", "心动人数1", "增幅", "团建电力值1", "增幅", "总电力值", "增幅", "发电总人数", "增幅"])
        writer.writerow(row)
    print(f"✅ [{formatted_time}] 写入完成。\n")


async def run_once():
    now_bj = datetime.now() + timedelta(hours=8)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
            viewport={"width": 390, "height": 844}, is_mobile=True, locale="zh-CN", timezone_id="Asia/Shanghai"
        )
        page = await context.new_page()

        data = {"时间": now_bj.strftime("%Y-%m-%d %H:%M:%S")}
        pwr = await scrape_power(page)
        data["总电力值"] = pwr["总电力值"]
        data["发电总人数"] = pwr["发电总人数"]
        await browser.close()

    if data["总电力值"] is None:
        print("❌ 抓取失败：总电力值为空。")
        return

    append_csv(data)


if __name__ == "__main__":
    asyncio.run(run_once())