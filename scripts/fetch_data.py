#!/usr/bin/env python3
import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SMP_PATH = os.path.join(BASE_DIR, "smp.json")
REC_PATH = os.path.join(BASE_DIR, "rec.json")

# 이제 data.go.kr을 직접 호출하지 않고, 서울 리전 Vercel 프록시를 거칩니다.
PROXY_URL = os.environ.get("PROXY_URL")      # 예: https://solar-data-proxy.vercel.app/api/data
PROXY_TOKEN = os.environ.get("PROXY_TOKEN")  # Vercel에 등록한 것과 동일한 값


def http_get(url, retries=3, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return res.read().decode("utf-8", errors="replace")
        except Exception as e:
            last_err = e
            print(f"  (http_get 시도 {attempt}/{retries} 실패: {e})")
            if attempt < retries:
                time.sleep(3)
    raise last_err


def parse_response(text):
    """JSON이든 XML이든 둘 다 처리해서 (header_dict, items_list) 로 통일해서 반환"""
    text = text.strip()

    # 1) JSON 시도
    if text.startswith("{"):
        data = json.loads(text)
        header = data.get("header") or (data.get("response") or {}).get("header") or {}
        body = data.get("body") or (data.get("response") or {}).get("body") or {}
        items = ((body.get("items") or {}).get("item"))
        if isinstance(items, dict):
            items = [items]
        return header, (items or [])

    # 2) XML 시도
    root = ET.fromstring(text)
    header_el = root.find("header")
    result_code = header_el.findtext("resultCode") if header_el is not None else None
    result_msg = header_el.findtext("resultMsg") if header_el is not None else None
    header = {"resultCode": result_code, "resultMsg": result_msg}

    items = []
    for item_el in root.findall(".//items/item"):
        d = {child.tag: (child.text or "").strip() for child in item_el}
        items.append(d)

    return header, items


def fetch_smp():
    params = urllib.parse.urlencode({
        "type": "smp",
        "token": PROXY_TOKEN,
    })
    url = f"{PROXY_URL}?{params}"
    text = http_get(url)
    header, items = parse_response(text)

    if not header or header.get("resultCode") != "00":
        raise RuntimeError(f"SMP API 오류: {header.get('resultMsg') if header else text[:200]}")
    if not items:
        raise RuntimeError("SMP API: item 데이터 없음")

    land_items = [it for it in items if "육지" in (it.get("areaName") or "")]
    pool = land_items or items

    # 현재(KST) 시각 기준으로, 아직 지나지 않은 미래 시간대(예측값)는 제외한다.
    # API의 hour 필드는 1~24이며, hour=N은 "N-1시~N시" 구간을 의미하므로
    # 실제로 확정된(이미 지난) 시간은 hour <= 현재 시(0~23) 인 경우까지다.
    now_kst = datetime.now(timezone(timedelta(hours=9)))
    today_str = now_kst.strftime("%Y%m%d")
    cutoff_hour = now_kst.hour  # 0~23. 예: 12시대(12:00~13:00 진행중)면 hour=12까지가 확정분

    # 오늘 날짜 + 확정된(지나간) 시간대만 모아서 평균/최고/최저/최신시각을 계산
    today_values = []  # [(hour, smp), ...]
    for it in pool:
        try:
            hour = int(it.get("hour"))
            smp = float(it.get("smp"))
        except (TypeError, ValueError):
            continue
        date_str = (it.get("date") or "").strip()

        if date_str != today_str:
            continue
        if hour > cutoff_hour:
            continue  # 아직 안 지난 시간대(예측값)는 제외

        today_values.append((hour, smp))

    if not today_values:
        raise RuntimeError("SMP API: 오늘 확정된 시간대 데이터가 아직 없음")

    latest_hour = max(h for h, _ in today_values)
    avg_price = sum(v for _, v in today_values) / len(today_values)

    return {
        "mode": "auto",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "areaLabel": "육지",
        "price": round(avg_price, 2),
        "unit": "원/kWh",
        "tradeDay": today_str,
        "tradHour": latest_hour,
    }


def fetch_rec():
    def to_num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    # bzDd(거래일)는 필수 파라미터. REC 현물시장은 매일 안 열리므로(주 2회 정도),
    # 오늘부터 최대 14일 전까지 하루씩 거슬러 올라가며 데이터가 있는 날을 찾는다.
    today = datetime.now(timezone(timedelta(hours=9))).date()  # KST 기준 오늘
    last_error = None

    for delta in range(0, 15):
        target_date = today - timedelta(days=delta)
        bz_dd = target_date.strftime("%Y%m%d")

        params = urllib.parse.urlencode({
            "type": "rec",
            "token": PROXY_TOKEN,
            "date": bz_dd,
        })
        url = f"{PROXY_URL}?{params}"

        try:
            text = http_get(url, retries=1)
            header, items = parse_response(text)
        except Exception as e:
            last_error = e
            continue

        if not header or header.get("resultCode") != "00":
            last_error = RuntimeError(header.get("resultMsg") if header else "unknown error")
            continue

        if not items:
            # 그 날짜엔 장이 안 열렸음 -> 하루 더 이전으로
            continue

        item = items[0]
        print(f"  (REC: {bz_dd} 데이터 사용)")
        return {
            "mode": "auto",
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "bzDd": item.get("bzDd") or bz_dd,
            "landAvgPrc": to_num(item.get("landAvgPrc")),
            "clsPrc": to_num(item.get("clsPrc")),
            "landHgPrc": to_num(item.get("landHgPrc")),
            "landLwPrc": to_num(item.get("landLwPrc")),
            "unit": "원",
        }

    raise RuntimeError(f"REC API: 최근 14일 내 거래일 데이터를 찾지 못함 (마지막 오류: {last_error})")


def update_file(path, fetcher, label):
    try:
        data = fetcher()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"{label} 갱신 완료: {json.dumps(data, ensure_ascii=False)}")
    except Exception as e:
        print(f"{label} 갱신 실패: {e}", file=sys.stderr)


def main():
    if not PROXY_URL or not PROXY_TOKEN:
        print("PROXY_URL / PROXY_TOKEN이 아직 설정되지 않았습니다. 자동 갱신을 건너뜁니다 (수동 모드 유지).")
        return
    update_file(SMP_PATH, fetch_smp, "SMP")
    update_file(REC_PATH, fetch_rec, "REC")


if __name__ == "__main__":
    main()
