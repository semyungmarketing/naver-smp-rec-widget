#!/usr/bin/env python3
import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone

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


def fetch_smp():
    params = urllib.parse.urlencode({
        "type": "smp",
        "token": PROXY_TOKEN,
    })
    url = f"{PROXY_URL}?{params}"
    text = http_get(url)
    data = json.loads(text)
    header = data.get("header") or (data.get("response") or {}).get("header")
    if not header or header.get("resultCode") != "00":
        raise RuntimeError(f"SMP API 오류: {header.get('resultMsg') if header else text[:200]}")
    body = data.get("body") or (data.get("response") or {}).get("body") or {}
    items = ((body.get("items") or {}).get("item"))
    if isinstance(items, dict):
        items = [items]
    if not items:
        raise RuntimeError("SMP API: item 데이터 없음")

    land_items = [it for it in items if "육지" in (it.get("areaName") or "")]
    pool = land_items or items

    latest = None
    for it in pool:
        try:
            hour = int(it.get("hour"))
            smp = float(it.get("smp"))
        except (TypeError, ValueError):
            continue
        date_str = (it.get("date") or "").strip()
        key = (date_str, hour)
        if latest is None or key > latest["key"]:
            latest = {"key": key, "hour": hour, "smp": smp, "date": date_str}
    if latest is None:
        raise RuntimeError("SMP API: 유효한 시간대 데이터 없음")

    return {
        "mode": "auto",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "areaLabel": "육지",
        "price": latest["smp"],
        "unit": "원/kWh",
        "tradeDay": latest["date"],
        "tradHour": latest["hour"],
    }


def fetch_rec():
    params = urllib.parse.urlencode({
        "type": "rec",
        "token": PROXY_TOKEN,
    })
    url = f"{PROXY_URL}?{params}"
    text = http_get(url)
    data = json.loads(text)
    header = data.get("header") or (data.get("response") or {}).get("header")
    if not header or header.get("resultCode") != "00":
        raise RuntimeError(f"REC API 오류: {header.get('resultMsg') if header else text[:200]}")
    body = data.get("body") or (data.get("response") or {}).get("body") or {}
    items = ((body.get("items") or {}).get("item"))
    item = items[0] if isinstance(items, list) else items
    if not item:
        raise RuntimeError("REC API: item 데이터 없음")

    def to_num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return {
        "mode": "auto",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "bzDd": item.get("bzDd"),
        "landAvgPrc": to_num(item.get("landAvgPrc")),
        "clsPrc": to_num(item.get("clsPrc")),
        "landHgPrc": to_num(item.get("landHgPrc")),
        "landLwPrc": to_num(item.get("landLwPrc")),
        "unit": "원",
    }


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
