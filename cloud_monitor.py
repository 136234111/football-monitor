#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
足球赔率智能监控 - 云端省流量版（GitHub Actions用）
优化：先用/api/today摘要粗筛，有变化才推，一天只用约60次
"""

import requests
import time
import json
from datetime import datetime, timezone
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==================== 配置区 ====================
API_KEY = "p_2_1HaUS-VlXx_-Mf5O9E7yT5Avyx-phLnfLn7l3wc"
API_BASE = "http://47.99.155.27:8321"

SERVERCHAN_SENDKEY = "SCT446640Txb6g7QY3wBAHhOHUKNEW7EIv"

# 监控的联赛（5大联赛 + 欧冠 + 日韩）
TARGET_LEAGUES = {
    "英超", "西甲", "意甲", "德甲", "法甲",
    "欧冠", "欧联杯",
    "日职联", "K联赛1",
}

# 信号阈值
ODDS_RISE_THRESHOLD = 0.03      # 赔率上升阈值
ODDS_DROP_THRESHOLD = 0.02      # 赔率下降阈值
PROBABILITY_THRESHOLD = 55.0     # 隐含概率阈值

# 数据文件
ALERTED_FILE = "alerted.json"
PREV_ODDS_FILE = "prev_odds.json"
# ================================================


def load_json_file(fname, default):
    try:
        with open(fname, "r") as f:
            return json.load(f)
    except:
        return default

def save_json_file(fname, data):
    with open(fname, "w") as f:
        json.dump(data, f)

def push_wechat(title, body):
    if not SERVERCHAN_SENDKEY:
        return
    try:
        requests.get(
            f"https://sctapi.ftqq.com/{SERVERCHAN_SENDKEY}.send",
            params={"title": title, "desp": body},
            timeout=15
        )
        print(f"📱 已推送: {title}")
    except Exception as e:
        print(f"⚠️ 推送失败: {e}")

def api_request(endpoint, params=None):
    headers = {"X-API-Token": API_KEY}
    url = f"{API_BASE}{endpoint}"
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15, verify=False)
        if resp.status_code == 429:
            print(f"⚠️ 限流了")
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"⚠️ API请求失败 {endpoint}: {e}")
        return None

def calc_implied_prob(home, draw, away):
    h = 1 / home
    d = 1 / draw
    a = 1 / away
    total = h + d + a
    return {"home": h/total*100, "draw": d/total*100, "away": a/total*100}

def main():
    print(f"=== 足球赔率监控 {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")
    
    alerted = set(load_json_file(ALERTED_FILE, []))
    prev_odds = load_json_file(PREV_ODDS_FILE, {})
    
    # 第1步：只调 /api/today 拿所有比赛摘要（1次调用）
    data = api_request("/api/today")
    if not data or "matches" not in data:
        print("❌ 没拿到数据")
        return
    
    matches = data.get("matches", [])
    print(f"今日总比赛: {len(matches)} 场")
    
    new_prev = {}
    strong_signals = []
    
    for m in matches:
        league = m.get("league_zh", "")
        if league not in TARGET_LEAGUES:
            continue
        if not m.get("odds_available"):
            continue
        
        fid = str(m["event_id"])
        odds = m.get("odds", {})
        
        home_o = odds.get("home_win", 0)
        draw_o = odds.get("draw", 0)
        away_o = odds.get("away_win", 0)
        
        if not all([home_o, draw_o, away_o]):
            continue
        
        new_prev[fid] = {"home": home_o, "draw": draw_o, "away": away_o}
        
        # 第2步：和上次对比，看有没有变化
        if fid not in prev_odds:
            continue  # 第一次见，不判断
        
        prev = prev_odds[fid]
        probs = calc_implied_prob(home_o, draw_o, away_o)
        
        signals = []
        score = 0
        
        # 主胜变化
        home_diff = home_o - prev["home"]
        if home_diff >= ODDS_RISE_THRESHOLD:
            signals.append(f"主胜赔率上升 {home_diff:.3f}")
            score -= 1
        elif home_diff <= -ODDS_DROP_THRESHOLD and probs["home"] >= PROBABILITY_THRESHOLD:
            signals.append(f"主胜赔率下降 {abs(home_diff):.3f} (概率{probs['home']:.1f}%)")
            score += 1
        
        # 客胜变化
        away_diff = away_o - prev["away"]
        if away_diff >= ODDS_RISE_THRESHOLD:
            signals.append(f"客胜赔率上升 {away_diff:.3f}")
            score -= 1
        elif away_diff <= -ODDS_DROP_THRESHOLD and probs["away"] >= PROBABILITY_THRESHOLD:
            signals.append(f"客胜赔率下降 {abs(away_diff):.3f} (概率{probs['away']:.1f}%)")
            score += 1
        
        # 判断信号等级
        level = ""
        if score >= 3:
            level = "🟢 强跟买"
        elif score <= -3:
            level = "🔴 强反买"
        
        if not level:
            continue
        
        # 避免重复推送
        alert_key = f"{fid}_{level}"
        if alert_key in alerted:
            continue
        
        alerted.add(alert_key)
        
        home_name = m.get("home_team_zh", "?")
        away_name = m.get("away_team_zh", "?")
        
        strong_signals.append({
            "fid": fid,
            "league": league,
            "home": home_name,
            "away": away_name,
            "level": level,
            "score": score,
            "signals": signals,
            "odds": {"home": home_o, "draw": draw_o, "away": away_o},
            "probs": probs,
        })
        
        print(f"\n{level} {home_name} vs {away_name} ({league}) 评分:{score:+d}")
        for s in signals:
            print(f"  - {s}")
    
    # 推送
    for sig in strong_signals:
        title = f"{sig['level']} {sig['home']}vs{sig['away']}"
        body = f"""
比赛: {sig['league']} | {sig['home']} vs {sig['away']}
评分: {sig['score']:+d}

赔率:
- 主胜: {sig['odds']['home']:.2f} ({sig['probs']['home']:.1f}%)
- 平局: {sig['odds']['draw']:.2f} ({sig['probs']['draw']:.1f}%)
- 客胜: {sig['odds']['away']:.2f} ({sig['probs']['away']:.1f}%)

信号:
""" + "\n".join([f"- {s}" for s in sig['signals']])
        push_wechat(title, body)
        time.sleep(0.5)
    
    # 保存
    save_json_file(ALERTED_FILE, list(alerted))
    save_json_file(PREV_ODDS_FILE, new_prev)
    
    print(f"\n=== 完成: 发现 {len(strong_signals)} 个强信号 ===")

if __name__ == "__main__":
    main()
