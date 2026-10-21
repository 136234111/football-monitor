#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
足球赔率智能监控 - 云端版（GitHub Actions用）
每次运行只抓一轮，发现强信号就推送到微信
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

TARGET_LEAGUES = {
    "英超", "西甲", "意甲", "德甲", "法甲",
    "欧冠", "欧联杯", "欧会杯",
    "日职联", "K联赛1",
}

KEY_BOOKMAKERS = ["bet365", "pinnacle", "william-hill"]

ODDS_RISE_THRESHOLD = 0.03
ODDS_DROP_THRESHOLD = 0.02
PROBABILITY_THRESHOLD = 55.0
MODEL_EDGE_THRESHOLD = 3.0
CLV_THRESHOLD = 0.005

# 记录已推送过的信号（避免重复推送）
ALERTED_FILE = "alerted.json"
# ================================================


def load_alerted():
    try:
        with open(ALERTED_FILE, "r") as f:
            return set(json.load(f))
    except:
        return set()

def save_alerted(alerted):
    with open(ALERTED_FILE, "w") as f:
        json.dump(list(alerted), f)

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
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"⚠️ API请求失败 {endpoint}: {e}")
        return None

def get_today_fixtures():
    data = api_request("/api/today")
    if not data or "matches" not in data:
        return []
    fixtures = []
    for m in data["matches"]:
        league = m.get("league_zh", "")
        if league not in TARGET_LEAGUES:
            continue
        if not m.get("odds_available"):
            continue
        fixtures.append({
            "fixture_id": m["event_id"],
            "home": m.get("home_team_zh", "?"),
            "away": m.get("away_team_zh", "?"),
            "league": league,
            "kickoff": f"{m.get('date','')} {m.get('time','')}",
        })
    return fixtures

def get_1x2_odds(full):
    bm = full.get("odds_by_bookmaker", {}).get("bet365", {})
    spf = bm.get("胜平负", {})
    if spf:
        return {
            "home": float(spf["主队"]),
            "draw": float(spf["平局"]),
            "away": float(spf["客队"]),
        }
    o = full.get("odds", {})
    if o.get("home_win"):
        return {
            "home": float(o["home_win"]),
            "draw": float(o["draw"]),
            "away": float(o["away_win"]),
        }
    return None

def calc_implied_prob(odds):
    h = 1 / odds["home"]
    d = 1 / odds["draw"]
    a = 1 / odds["away"]
    total = h + d + a
    return {"home": h/total*100, "draw": d/total*100, "away": a/total*100}

def analyze_match(fid):
    """分析一场比赛，返回 (评分, 信号列表, 赔率, 概率)"""
    full = api_request(f"/match_full/{fid}")
    if not full:
        return 0, [], None, None
    
    odds = get_1x2_odds(full)
    if not odds:
        return 0, [], None, None
    
    probs = calc_implied_prob(odds)
    score = 0
    signals = []
    
    time.sleep(0.3)  # 避免限流
    
    # 1. 模型 vs 市场
    pred = api_request(f"/prediction/{fid}")
    if pred and pred.get("prediction"):
        p = pred["prediction"]
        model_home = p.get("prob_home", 0) * 100
        model_away = p.get("prob_away", 0) * 100
        
        home_edge = model_home - probs["home"]
        away_edge = model_away - probs["away"]
        
        if home_edge > MODEL_EDGE_THRESHOLD:
            score += 2
            signals.append(f"模型看好主胜 ({model_home:.1f}% vs 市场{probs['home']:.1f}%, 差{home_edge:+.1f}%)")
        elif home_edge < -MODEL_EDGE_THRESHOLD:
            score -= 1
            signals.append(f"模型不看好主胜 (差{home_edge:+.1f}%)")
        
        if away_edge > MODEL_EDGE_THRESHOLD:
            score += 2
            signals.append(f"模型看好客胜 ({model_away:.1f}% vs 市场{probs['away']:.1f}%, 差{away_edge:+.1f}%)")
        elif away_edge < -MODEL_EDGE_THRESHOLD:
            score -= 1
            signals.append(f"模型不看好客胜 (差{away_edge:+.1f}%)")
    
    time.sleep(0.3)
    
    # 2. CLV走势
    clv_data = api_request(f"/match_clv/{fid}")
    if clv_data and clv_data.get("found"):
        c = clv_data.get("clv", {})
        clv_h = c.get("clv_home", 0)
        clv_a = c.get("clv_away", 0)
        
        if clv_h > CLV_THRESHOLD:
            score += 1
            signals.append(f"主胜CLV上升 {clv_h:.4f} (资金流入)")
        elif clv_h < -CLV_THRESHOLD:
            score -= 1
            signals.append(f"主胜CLV下降 {clv_h:.4f} (资金流出)")
        
        if clv_a > CLV_THRESHOLD:
            score += 1
            signals.append(f"客胜CLV上升 {clv_a:.4f} (资金流入)")
        elif clv_a < -CLV_THRESHOLD:
            score -= 1
            signals.append(f"客胜CLV下降 {clv_a:.4f} (资金流出)")
    
    return score, signals, odds, probs

def main():
    print(f"=== 足球赔率监控 {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")
    
    alerted = load_alerted()
    
    fixtures = get_today_fixtures()
    print(f"今日目标联赛比赛: {len(fixtures)} 场")
    
    strong_signals = []
    
    for m in fixtures:
        fid = m["fixture_id"]
        score, signals, odds, probs = analyze_match(fid)
        
        # 判断信号等级
        if score >= 3:
            level = "🟢 强跟买"
        elif score <= -3:
            level = "🔴 强反买"
        else:
            continue  # 弱信号不推送
        
        # 避免重复推送
        alert_key = f"{fid}_{level}"
        if alert_key in alerted:
            continue
        
        alerted.add(alert_key)
        strong_signals.append((m, score, signals, level))
        
        print(f"\n{level} {m['home']} vs {m['away']} ({m['league']}) 评分:{score:+d}")
        for s in signals:
            print(f"  - {s}")
        
        # 推送到微信
        title = f"{level} {m['home']}vs{m['away']}"
        body = f"""
比赛: {m['league']} | {m['home']} vs {m['away']}
开赛: {m['kickoff']}
评分: {score:+d}

赔率:
- 主胜: {odds['home']:.2f} ({probs['home']:.1f}%)
- 平局: {odds['draw']:.2f} ({probs['draw']:.1f}%)
- 客胜: {odds['away']:.2f} ({probs['away']:.1f}%)

信号:
""" + "\n".join([f"- {s}" for s in signals])
        
        push_wechat(title, body)
        time.sleep(0.5)
    
    save_alerted(alerted)
    
    print(f"\n=== 完成: 发现 {len(strong_signals)} 个强信号 ===")

if __name__ == "__main__":
    main()
