import streamlit as st
import requests
import json
import math as _math
import re as _re
from collections import defaultdict

st.set_page_config(page_title="LoL 試合解析ツール", page_icon="🎮", layout="wide")

# ─── Riot API ────────────────────────────────────────────────────────
def make_riot_get(api_key):
    headers = {"X-Riot-Token": api_key}
    def riot_get(url):
        try:
            res = requests.get(url, headers=headers, timeout=15)
            if res.status_code != 200:
                return {}
            return res.json()
        except Exception:
            return {}
    return riot_get

BASE_ASIA = "https://asia.api.riotgames.com"
BASE_JP   = "https://jp1.api.riotgames.com"

# ─── Data Dragon ─────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def build_champion_id_map():
    try:
        versions = requests.get("https://ddragon.leagueoflegends.com/api/versions.json", timeout=10).json()
        latest = versions[0]
        champs = requests.get(
            f"https://ddragon.leagueoflegends.com/cdn/{latest}/data/en_US/champion.json", timeout=10
        ).json().get("data", {})
        return {int(v["key"]): v["name"] for v in champs.values()}
    except Exception:
        return {}

@st.cache_data(ttl=3600)
def build_item_map():
    try:
        versions = requests.get("https://ddragon.leagueoflegends.com/api/versions.json", timeout=10).json()
        latest = versions[0]
        raw = requests.get(
            f"https://ddragon.leagueoflegends.com/cdn/{latest}/data/en_US/item.json", timeout=10
        ).json().get("data", {})
        item_map = {}
        for item_id, item in raw.items():
            tags  = item.get("tags", [])
            gold  = item.get("gold", {})
            depth = item.get("depth", 1)
            into  = item.get("into", [])
            frm   = item.get("from", [])
            if "Consumable" in tags or gold.get("purchasable") == False:
                tier = "consumable"
            elif not into:
                tier = "starter" if (not frm and gold.get("total", 0) <= 500) else "completed"
            elif depth >= 3:
                tier = "completed"
            else:
                tier = "component"
            item_map[int(item_id)] = {"name": item.get("name", f"item_{item_id}"), "tier": tier, "tags": tags}
        return item_map
    except Exception:
        return {}

# ─── ゾーン判定 ──────────────────────────────────────────────────────
def _dist_to_segment(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return _math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return _math.hypot(px - (ax + t * dx), py - (ay + t * dy))

def _min_dist_to_path(x, y, path):
    if len(path) == 1:
        return _math.hypot(x - path[0][0], y - path[0][1])
    return min(_dist_to_segment(x, y, path[i][0], path[i][1], path[i+1][0], path[i+1][1])
               for i in range(len(path) - 1))

_ZONE_PATHS = {
    "top_lane":    ([(400,14400),(400,10500),(900,9500),(1500,9000)],           1600),
    "bot_lane":    ([(14400,500),(13800,1500),(12500,2500),(11500,3800),(10500,4800),(9500,5600)], 1400),
    "mid_lane":    ([(2200,12700),(5000,9800),(7400,7400),(9800,5000),(12200,2600)], 1400),
    "blue_jungle": ([(2500,7500),(4500,7000),(4800,5000),(3200,3800)],          3200),
    "red_jungle":  ([(13000,6500),(12200,7200),(10200,7800),(9800,9800),(11200,11200)], 3500),
    "blue_base":   ([(1000,1000)],                                              2800),
    "red_base":    ([(13800,13800)],                                            2800),
    "river":       ([(4800,12200),(6500,10500),(7400,9500),(8800,8200),(10200,6700),(12200,4800)], 750),
}
_ZONE_PRIORITY = {"blue_base":0,"red_base":0,"top_lane":1,"bot_lane":1,"mid_lane":1,"river":1.5,"blue_jungle":2,"red_jungle":2}
_MID_START = (2200, 12700)
_MID_NX = (12200-2200)/_math.hypot(12200-2200,2600-12700)
_MID_NY = (2600-12700)/_math.hypot(12200-2200,2600-12700)
_TOP_BLUE_OUTER_Y=10441; _TOP_RED_OUTER_Y=13875
_BOT_BLUE_OUTER_D=11533; _BOT_RED_OUTER_D=18371
_MID_BLUE_OUTER_P=4972;  _MID_RED_OUTER_P=9173

def position_to_zone(x, y):
    if x is None or y is None: return "unknown"
    candidates = []
    for zone, (path, width) in _ZONE_PATHS.items():
        d = _min_dist_to_path(x, y, path)
        if d <= width: candidates.append((_ZONE_PRIORITY[zone], d, zone))
    if candidates:
        candidates.sort(); base_zone = candidates[0][2]
    else:
        base_zone = min(_ZONE_PATHS, key=lambda z: _min_dist_to_path(x, y, _ZONE_PATHS[z][0]))
    if base_zone == "top_lane":
        if y < _TOP_BLUE_OUTER_Y: return "top_blueside"
        elif y > _TOP_RED_OUTER_Y: return "top_redside"
        return "top_center"
    elif base_zone == "bot_lane":
        d = x + y
        if d < _BOT_BLUE_OUTER_D: return "bot_blueside"
        elif d > _BOT_RED_OUTER_D: return "bot_redside"
        return "bot_center"
    elif base_zone == "mid_lane":
        p = (x-_MID_START[0])*_MID_NX + (y-_MID_START[1])*_MID_NY
        if p < _MID_BLUE_OUTER_P: return "mid_blueside"
        elif p > _MID_RED_OUTER_P: return "mid_redside"
        return "mid_center"
    elif base_zone == "blue_jungle":
        return "blue_jungle_top" if y > x else "blue_jungle_bot"
    elif base_zone == "red_jungle":
        return "red_jungle_top" if y > x else "red_jungle_bot"
    elif base_zone == "river":
        return "river_baron" if y > x else "river_dragon"
    return base_zone

# ─── ヘルパー ─────────────────────────────────────────────────────────
def get_role(p):
    pos = p.get("teamPosition") or p.get("individualPosition") or ""
    return {"TOP":"top","JUNGLE":"jungle","MIDDLE":"mid","BOTTOM":"bot","UTILITY":"support"}.get(pos.upper(), pos.lower() or "unknown")

def get_items(p, item_id_to_info):
    items = []
    for i in range(7):
        item_id = p.get(f"item{i}", 0)
        if item_id != 0:
            info = item_id_to_info.get(item_id, {})
            items.append({"id": item_id, "name": info.get("name", f"item_{item_id}"), "tier": info.get("tier", "unknown")})
    return items

TIER_ORDER = ["IRON","BRONZE","SILVER","GOLD","PLATINUM","EMERALD","DIAMOND","MASTER","GRANDMASTER","CHALLENGER"]
RANK_ORDER = ["IV","III","II","I"]

def tier_score(tier, rank="I"):
    t = TIER_ORDER.index(tier) if tier in TIER_ORDER else -1
    r = RANK_ORDER.index(rank) if rank in RANK_ORDER else 0
    return t * 4 + r

def higher_rank(a, b):
    if a is None: return b
    if b is None: return a
    return a if tier_score(a.get("tier",""), a.get("rank","I")) >= tier_score(b.get("tier",""), b.get("rank","I")) else b

def get_rank(puuid, summoner_id, riot_get):
    def parse_entries(entries):
        if not isinstance(entries, list) or not entries: return None
        result = {}
        for entry in entries:
            q = entry.get("queueType", "")
            w, l = entry.get("wins", 0), entry.get("losses", 0)
            current = {"tier": entry.get("tier","UNRANKED"), "rank": entry.get("rank",""),
                       "lp": entry.get("leaguePoints",0), "wins": w, "losses": l,
                       "winRate": f"{round(w/max(w+l,1)*100,1)}%"}
            prev_tier = entry.get("highestTierAchieved","")
            prev = {"tier": prev_tier, "rank": "I"} if prev_tier else None
            parsed = {"current": current, "prevSeasonPeak": prev, "peakRank": higher_rank(current, prev)}
            if q == "RANKED_SOLO_5x5": result["solo"] = parsed
            elif q == "RANKED_FLEX_SR": result["flex"] = parsed
        return result if result else None
    if puuid:
        parsed = parse_entries(riot_get(f"{BASE_JP}/lol/league/v4/entries/by-puuid/{puuid}"))
        if parsed: return parsed
    if summoner_id:
        parsed = parse_entries(riot_get(f"{BASE_JP}/lol/league/v4/entries/by-summoner/{summoner_id}"))
        if parsed: return parsed
    return {"solo": None, "flex": None}

def get_top_masteries(puuid, riot_get, top_n=10):
    data = riot_get(f"{BASE_JP}/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}/top?count={top_n}")
    if not isinstance(data, list): return []
    champ_id_to_name = build_champion_id_map()
    return [{"champion": champ_id_to_name.get(m.get("championId"), f"id:{m.get('championId')}"),
             "level": m.get("championLevel",0), "points": m.get("championPoints",0)} for m in data]

def get_champion_mastery(puuid, champion_name, riot_get):
    champ_id_to_name = build_champion_id_map()
    champ_name_to_id = {v: k for k, v in champ_id_to_name.items()}
    champ_id = champ_name_to_id.get(champion_name)
    if not champ_id: return None
    data = riot_get(f"{BASE_JP}/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}/by-champion/{champ_id}")
    if not isinstance(data, dict) or "championLevel" not in data:
        return {"champion": champion_name, "level": 0, "points": 0}
    return {"champion": champion_name, "level": data.get("championLevel",0), "points": data.get("championPoints",0)}

LOLALYTICS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
LANE_MAP = {"top":"top","jungle":"jungle","mid":"middle","bot":"bottom","support":"support"}

def get_matchup(champ1, champ2, lane, days=30):
    def fmt(name): return name.lower().replace(" ","").replace("'","").replace(".","")
    lane_str = LANE_MAP.get(lane, lane)
    url = f"https://lolalytics.com/lol/{fmt(champ1)}/vs/{fmt(champ2)}/build/?patch={days}&lane={lane_str}&vslane={lane_str}"
    try:
        res = requests.get(url, headers=LOLALYTICS_HEADERS, timeout=15)
        if res.status_code != 200: return None
        html = res.text
        wr_all    = _re.findall(r'<!--t=\w+-->([\d.]+)<!---->%(?=.*?Win Rate)', html, _re.DOTALL)
        games_all = _re.findall(r'([\d,]+)\s*</div>\s*<div[^>]*>\s*Games', html)
        if len(wr_all) >= 2 and games_all:
            return {"winRate": float(wr_all[1]), "games": int(games_all[0].replace(",",""))}
        return None
    except Exception:
        return None

# ─── メイン解析処理 ───────────────────────────────────────────────────
def run_analysis(api_key, match_id, config, progress_cb):
    riot_get = make_riot_get(api_key)
    champ_id_to_name = build_champion_id_map()
    item_id_to_info  = build_item_map()
    champ_name_to_id = {v: k for k, v in champ_id_to_name.items()}

    progress_cb(0.05, "試合データ取得中...")
    match_data    = riot_get(f"{BASE_ASIA}/lol/match/v5/matches/{match_id}")
    timeline_data = riot_get(f"{BASE_ASIA}/lol/match/v5/matches/{match_id}/timeline")
    if not match_data.get("info"):
        raise ValueError("試合データを取得できませんでした。APIキーとMATCH IDを確認してください。")
    if not timeline_data.get("info"):
        raise ValueError("タイムラインデータを取得できませんでした。")

    info         = match_data.get("info", {})
    participants = info.get("participants", [])
    duration_min = round(info.get("gameDuration", 0) / 60, 1)

    id_to_champ  = {p["participantId"]: p.get("championName", f"p{p['participantId']}") for p in participants}
    blue_ids     = [p["participantId"] for p in participants if p["teamId"] == 100]
    red_ids      = [p["participantId"] for p in participants if p["teamId"] == 200]
    blue_champs  = {p.get("championName") for p in participants if p["teamId"] == 100}
    red_champs   = {p.get("championName") for p in participants if p["teamId"] == 200}
    pid_to_champ = {p["participantId"]: p.get("championName", f"p{p['participantId']}") for p in participants}
    pid_to_side  = {p["participantId"]: ("blue" if p["teamId"] == 100 else "red") for p in participants}

    ban_map = {"blue": [], "red": []}
    for team in info.get("teams", []):
        side = "blue" if team["teamId"] == 100 else "red"
        for b in team.get("bans", []):
            ban_map[side].append(champ_id_to_name.get(b.get("championId"), f"id:{b.get('championId')}"))
    all_bans = set(ban_map["blue"]) | set(ban_map["red"])

    # プレイヤーフィルター
    pf_cfg = config["player_filter"]
    role_to_lane = {"top":"TOP","jungle":"JG","mid":"MID","bot":"BOT","support":"SUP"}
    target_pids = set()
    for p in participants:
        side = "blue" if p["teamId"] == 100 else "red"
        role = get_role(p)
        lane_key = role_to_lane.get(role, "")
        if lane_key and pf_cfg[side].get(lane_key, False):
            target_pids.add(p["participantId"])

    def pid_is_target(pid): return pid in target_pids
    def champ_is_target(name):
        for p in participants:
            if p.get("championName") == name: return p["participantId"] in target_pids
        return False

    # スキル順
    progress_cb(0.10, "スキル・タイムライン解析中...")
    skill_orders    = defaultdict(list)
    ult_level_times = {}
    slot_map = {1:"Q",2:"W",3:"E",4:"R"}
    for frame in timeline_data.get("info",{}).get("frames",[]):
        for event in frame.get("events",[]):
            if event.get("type") == "SKILL_LEVEL_UP":
                pid   = event.get("participantId")
                skill = slot_map.get(event.get("skillSlot"))
                if pid and skill:
                    skill_orders[pid].append(skill)
                    if skill == "R":
                        t_min = round(event.get("timestamp",0)/60000,1)
                        if pid not in ult_level_times: ult_level_times[pid] = []
                        ult_level_times[pid].append({"level": len(ult_level_times.get(pid,[]))+1, "time": t_min})

    # チームゴールド・プレイヤーゴールド
    team_gold_timeline = {}
    player_timeline    = defaultdict(dict)
    for frame in timeline_data.get("info",{}).get("frames",[]):
        t   = frame.get("timestamp",0) // 60000
        key = f"at{t}min"
        pf  = frame.get("participantFrames",{})
        blue_gold = sum(pf.get(str(i),{}).get("totalGold",0) for i in blue_ids)
        red_gold  = sum(pf.get(str(i),{}).get("totalGold",0) for i in red_ids)
        team_gold_timeline[key] = {"blue": blue_gold, "red": red_gold}
        if config["ev_player_gold"]:
            for pid_str, pdata in pf.items():
                pid = int(pid_str)
                if not pid_is_target(pid): continue
                champ = pid_to_champ.get(pid)
                if champ:
                    player_timeline[champ][key] = {"gold": pdata.get("totalGold",0)}

    # イベント解析
    progress_cb(0.20, "イベント解析中...")
    feats_count      = {"blue":{"kills":0,"epics":0},"red":{"kills":0,"epics":0}}
    feats_done       = {"blue":set(),"red":set()}
    feats_claimed    = set()
    feats_events     = []
    first_tower_done = False
    EPIC_MONSTERS    = {"dragon","baron_nashor","riftherald","horde","atakhan"}

    def check_feats(side, time_min):
        fc, fd = feats_count[side], feats_done[side]
        newly = []
        if fc["kills"] >= 3 and "kills" not in fd and "kills" not in feats_claimed:
            feats_claimed.add("kills"); fd.add("kills"); newly.append("champion_kills_3")
        if fc["epics"] >= 3 and "epics" not in fd and "epics" not in feats_claimed:
            feats_claimed.add("epics"); fd.add("epics"); newly.append("epic_monsters_3")
        for feat in newly:
            if config["ev_feats"]:
                feats_events.append({"time":time_min,"type":"feat_of_strength","team":side,
                                     "feat":feat,"totalAchieved":len(fd),"completed":len(fd)>=2})

    events = []
    completed_item_events = []
    COMPLETED_ITEM_TIERS  = {"legendary","mythic","boots"}

    for frame in timeline_data.get("info",{}).get("frames",[]):
        for event in frame.get("events",[]):
            etype    = event.get("type")
            time_min = round(event.get("timestamp",0)/60000,1)
            pos      = event.get("position",{})
            zone     = position_to_zone(pos.get("x"), pos.get("y"))

            if etype == "CHAMPION_KILL":
                killer_id = event.get("killerId",0)
                side = pid_to_side.get(killer_id)
                if config["ev_kill"]:
                    killer = id_to_champ.get(killer_id,"unknown")
                    victim_champ = id_to_champ.get(event.get("victimId",0),"unknown")
                    tower_dmg = any(d.get("type")=="TOWER" for d in event.get("victimDamageReceived",[]))
                    ult_used = []
                    if config["ev_ult_used"]:
                        ult_used = list({id_to_champ.get(d.get("participantId"), d.get("spellName",""))
                                        for d in event.get("victimDamageReceived",[])
                                        if d.get("spellSlot")==3 and d.get("participantId",0)!=0})
                    assists_list = [id_to_champ.get(a, f"p{a}") for a in event.get("assistingParticipantIds",[])]
                    if tower_dmg:
                        victim_side = pid_to_side.get(event.get("victimId",0))
                        assists_list.append("BlueTeamTower" if victim_side=="red" else "RedTeamTower")
                    ev = {"time":time_min,"type":"kill","killer":killer,"victim":victim_champ,
                          "assists":assists_list,"zone":zone,"ultUsed":ult_used}
                    involved = {killer, victim_champ} | {a for a in assists_list if "Tower" not in a}
                    if any(champ_is_target(c) for c in involved):
                        events.append(ev)
                if side: feats_count[side]["kills"] += 1; check_feats(side, time_min)

            elif etype in ("ELITE_MONSTER_KILL","BUILDING_KILL"):
                name    = (event.get("monsterType") or event.get("buildingType","")).lower()
                team_id = event.get("teamId",0)
                side    = "blue" if team_id==100 else "red"
                killer  = id_to_champ.get(event.get("killerId",0),"unknown")
                if config["ev_objective"]:
                    events.append({"time":time_min,"type":"objective","name":name,"team":side,"killer":killer,"zone":zone})
                if etype=="ELITE_MONSTER_KILL" and any(em in name for em in EPIC_MONSTERS):
                    feats_count[side]["epics"] += 1; check_feats(side, time_min)
                if etype=="BUILDING_KILL" and "tower" in name and not first_tower_done:
                    first_tower_done = True
                    if "first_tower" not in feats_claimed:
                        feats_claimed.add("first_tower"); feats_done[side].add("first_tower")
                        if config["ev_feats"]:
                            feats_events.append({"time":time_min,"type":"feat_of_strength","team":side,
                                                 "feat":"first_tower","totalAchieved":len(feats_done[side]),"completed":len(feats_done[side])>=2})

            elif etype == "TURRET_PLATE_DESTROYED":
                if config["ev_plate"]:
                    attacker_id   = event.get("killerId",0)
                    defender_tid  = event.get("teamId",0)
                    attacker_side = "blue" if defender_tid==200 else "red"
                    lane_raw   = event.get("laneType","").lower()
                    lane_label = {"top_lane":"top","bot_lane":"bot","mid_lane":"mid"}.get(lane_raw, lane_raw)
                    if pid_is_target(attacker_id):
                        events.append({"time":time_min,"type":"plate_destroyed","lane":lane_label,
                                       "attackerSide":attacker_side,"attacker":id_to_champ.get(attacker_id,"unknown"),"zone":zone})

            elif etype == "ITEM_PURCHASED":
                if config["ev_item"]:
                    pid = event.get("participantId",0)
                    if pid and pid_is_target(pid):
                        item_id   = event.get("itemId",0)
                        item_info = item_id_to_info.get(item_id,{})
                        if item_info.get("tier") in COMPLETED_ITEM_TIERS:
                            completed_item_events.append({"time":time_min,"type":"item_completed",
                                "player":id_to_champ.get(pid,"unknown"),"side":pid_to_side.get(pid,"unknown"),
                                "itemId":item_id,"itemName":item_info.get("name",f"item_{item_id}"),
                                "itemTier":item_info.get("tier","unknown")})

            elif etype == "LEVEL_UP":
                if config["ev_level_up"]:
                    pid = event.get("participantId",0)
                    if pid_is_target(pid):
                        events.append({"time":time_min,"type":"level_up",
                                       "player":id_to_champ.get(pid,"unknown"),"level":event.get("level",0)})

            elif etype == "SKILL_LEVEL_UP" and event.get("skillSlot") == 4:
                if config["ev_ult_leveled"]:
                    pid = event.get("participantId",0)
                    if pid_is_target(pid):
                        champ  = id_to_champ.get(pid,"unknown")
                        ult_lv = len([e2 for e2 in events if e2.get("type")=="ult_leveled" and e2.get("player")==champ])+1
                        events.append({"time":time_min,"type":"ult_leveled","player":champ,
                                       "side":pid_to_side.get(pid,"unknown"),"ultLevel":ult_lv})

    # ドラゴンソウル
    if config["ev_dragon_soul"]:
        dragon_kills = {"blue":0,"red":0}
        for ev in list(events):
            if ev.get("type")=="objective" and "dragon" in ev.get("name","").lower():
                team = ev.get("team")
                if team in dragon_kills:
                    dragon_kills[team] += 1
                    if dragon_kills[team] == 4:
                        events.append({"time":ev["time"],"type":"dragon_soul","team":team,"name":ev.get("name","dragon")})

    if config["ev_feats"]:
        events.extend(feats_events)
    events.extend(completed_item_events)
    events.sort(key=lambda e: e["time"])

    # チームスタッツ
    progress_cb(0.30, "プレイヤー情報取得中（10人分・少し時間がかかります）...")
    team_totals = defaultdict(lambda: {"damage":0,"gold":0})
    for p in participants:
        side = "blue" if p["teamId"]==100 else "red"
        team_totals[side]["damage"] += p.get("totalDamageDealtToChampions",0)
        team_totals[side]["gold"]   += p.get("goldEarned",0)

    teams = {"blue":{"players":[],"bans":ban_map["blue"],"objectives":{}},
             "red": {"players":[],"bans":ban_map["red"], "objectives":{}}}

    total_players = len(participants)
    for pi, p in enumerate(participants):
        progress_cb(0.30 + (pi / total_players) * 0.45,
                    f"プレイヤー情報取得中... ({pi+1}/{total_players}) {p.get('championName','')}")
        side       = "blue" if p["teamId"]==100 else "red"
        pid        = p["participantId"]
        opp_champs = red_champs if side=="blue" else blue_champs
        puuid      = p.get("puuid","")
        summoner_id = p.get("summonerId","")
        k,d,a      = p.get("kills",0),p.get("deaths",0),p.get("assists",0)
        dmg        = p.get("totalDamageDealtToChampions",0)
        gold       = p.get("goldEarned",0)
        team_kills = sum(q.get("kills",0) for q in participants if q["teamId"]==p["teamId"])
        played_champ = p.get("championName","")
        is_target = pid_is_target(pid)

        rank     = get_rank(puuid, summoner_id, riot_get) if is_target and config["rank"] else {"solo":None,"flex":None}
        masteries = get_top_masteries(puuid, riot_get, top_n=10) if is_target and config["mastery_top3"] else []

        if is_target and config["mastery_played"]:
            played_in_top3 = any(m["champion"]==played_champ for m in masteries[:3])
            played_mastery = (next(m for m in masteries[:3] if m["champion"]==played_champ)
                              if played_in_top3 else get_champion_mastery(puuid, played_champ, riot_get))
        else:
            played_mastery = None

        top3_status = []
        if is_target and config["mastery_top3"] and masteries:
            for i, m in enumerate(masteries[:3]):
                champ = m["champion"]
                if champ in all_bans:
                    status = f"banned_by_{'ally' if champ in ban_map[side] else 'enemy'}"
                elif champ in opp_champs:
                    status = "picked_by_enemy"
                else:
                    status = "available"
                top3_status.append({"champion":champ,"masteryRank":i+1,"points":m["points"],
                                    "level":m["level"],"status":status,"isPlaying":champ==played_champ})

        player_data = {
            "champion": played_champ, "role": get_role(p),
            "kda": {"k":k,"d":d,"a":a,"ratio":round((k+a)/max(d,1),2)},
            "gold": gold, "killParticipation": f"{round((k+a)/max(team_kills,1)*100,1)}%",
            "firstBloodKill": p.get("firstBloodKill",False),
        }
        if config["rank"] and is_target:           player_data["rank"]               = rank
        if config["mastery_top3"] and is_target:   player_data["top3MasteryStatus"]  = top3_status
        if config["mastery_played"] and is_target: player_data["playedChampionMastery"] = played_mastery
        if config["vision"] and is_target:
            player_data["vision"] = {"score":p.get("visionScore",0),"wardsPlaced":p.get("wardsPlaced",0),
                                     "wardsKilled":p.get("wardsKilled",0),"controlWards":p.get("visionWardsBoughtInGame",0)}
        if config["items"] and is_target:       player_data["items"]      = get_items(p, item_id_to_info)
        if config["skill_order"] and is_target: player_data["skillOrder"] = skill_orders.get(pid,[])
        if config["shares"] and is_target:
            player_data["damageShare"] = f"{round(dmg/max(team_totals[side]['damage'],1)*100,1)}%"
            player_data["goldShare"]   = f"{round(gold/max(team_totals[side]['gold'],1)*100,1)}%"
            player_data["damage"]      = dmg
        if config["special_kills"] and is_target:
            player_data["soloKills"]   = p.get("challenges",{}).get("soloKills",0)
            player_data["pentaKills"]  = p.get("pentaKills",0)
            player_data["quadraKills"] = p.get("quadraKills",0)
        teams[side]["players"].append(player_data)

    for team in info.get("teams",[]):
        side = "blue" if team["teamId"]==100 else "red"
        obj  = team.get("objectives",{})
        teams[side]["objectives"] = {
            "win":        team.get("win",False),
            "firstBlood": obj.get("champion",{}).get("first",False),
            "dragons":    obj.get("dragon",{}).get("kills",0),
            "baron":      obj.get("baron",{}).get("kills",0),
            "towers":     obj.get("tower",{}).get("kills",0),
            "inhibitors": obj.get("inhibitor",{}).get("kills",0),
            "riftHerald": obj.get("riftHerald",{}).get("kills",0),
        }

    # マッチアップ
    lane_matchups = []
    if config["lane_matchups"]:
        progress_cb(0.80, "マッチアップ相性取得中...")
        for bp, rp in zip(teams["blue"]["players"], teams["red"]["players"]):
            lane = bp["role"]
            bc, rc = bp["champion"], rp["champion"]
            bvr = get_matchup(bc, rc, lane)
            rvb = get_matchup(rc, bc, lane)
            lane_matchups.append({
                "lane":lane,"blue":bc,"red":rc,
                "blueWinRate": bvr["winRate"] if bvr else None,
                "redWinRate":  rvb["winRate"] if rvb else None,
                "games": (bvr or rvb or {}).get("games"),
                "advantage": "blue" if (bvr and bvr["winRate"]>50) else ("red" if (bvr and bvr["winRate"]<50) else "even"),
            })

    # 統合タイムライン
    progress_cb(0.92, "タイムライン統合中...")
    tg = team_gold_timeline
    pt = dict(player_timeline)
    events_by_min = defaultdict(list)
    for e in events: events_by_min[int(e["time"])].append(e)
    for e in completed_item_events: events_by_min[int(e["time"])].append(e)

    feats_summary = {
        "blue": {"kills":feats_count["blue"]["kills"],"epics":feats_count["blue"]["epics"],
                 "firstTower":"first_tower" in feats_done["blue"],
                 "achieved":sorted(list(feats_done["blue"])),"completed":len(feats_done["blue"])>=2},
        "red":  {"kills":feats_count["red"]["kills"], "epics":feats_count["red"]["epics"],
                 "firstTower":"first_tower" in feats_done["red"],
                 "achieved":sorted(list(feats_done["red"])), "completed":len(feats_done["red"])>=2},
        "claimed": {k: True for k in feats_claimed},
        "note": "各カテゴリは先取チームのみ付与。後追いは偉業に加算されない",
    }

    all_minutes = sorted(int(k.replace("at","").replace("min","")) for k in tg.keys())
    unified_timeline = []
    for t in all_minutes:
        key  = f"at{t}min"
        gold = tg.get(key,{})
        player_snap = {}
        for champ, tl_data in pt.items():
            snap = tl_data.get(key)
            if snap: player_snap[champ] = snap
        frame_events = sorted([e for e in events+completed_item_events if t <= e["time"] < t+1], key=lambda e: e["time"])
        unified_timeline.append({
            "minute": t,
            "goldDiff_blue_lead": gold.get("blue",0)-gold.get("red",0),
            "teamGold": {"blue":gold.get("blue",0),"red":gold.get("red",0)},
            "playerGoldCs": player_snap,
            "events": frame_events,
        })

    # フェーズ自動分割
    _early_end = 14
    if duration_min <= 20:
        phases = {"early":{"start":0,"end":_early_end},"late":{"start":_early_end+1,"end":round(duration_min)}}
    else:
        _mid_end = round((_early_end+1+round(duration_min))/2)
        phases = {"early":{"start":0,"end":_early_end},"mid":{"start":_early_end+1,"end":_mid_end},"late":{"start":_mid_end+1,"end":round(duration_min)}}

    feedback = {
        "meta": {
            "matchId":  match_data.get("metadata",{}).get("matchId",""),
            "patch":    info.get("gameVersion","").rsplit(".",1)[0],
            "duration": f"{duration_min}min",
            "gameMode": info.get("gameMode",""),
            "queueId":  info.get("queueId",0),
            "phases":   phases,
            "analysisNotes": {
                "assists_tower": (
                    "killイベントのassistsに'BlueTeamTower'または'RedTeamTower'が含まれる場合、"
                    "victimがそのタワーからダメージを受けた状態でキルされたことを示す。"
                    "これはタワー下での死亡を意味するものではなく、"
                    "タワーがキルに貢献した1人のチャンピオンとして扱うこと。"
                ),
                "phases": (
                    "meta.phasesに序盤・中盤・終盤の時間範囲が定義されている。"
                    "各フェーズの分析はそのstart〜end分のイベントのみを根拠とすること。"
                ),
                "gold_diff": (
                    "timeline.teamGoldのblueとredの差がゴールドリードを示す。"
                    "blue - red が正の値ならblueリード、負の値ならredリード。"
                ),
                "custom": config.get("custom_note",""),
            },
        },
        "teams":         teams,
        "timeline":      unified_timeline,
        "featsOfStrength": feats_summary,
        "laneMatchups":  lane_matchups,
    }

    progress_cb(1.0, "完了！")
    return feedback, match_id

# ─── Streamlit UI ────────────────────────────────────────────────────
st.title("🎮 LoL 試合解析ツール")
st.caption("Riot APIから試合データを取得し、AI分析用のJSONを生成します")

# ── 入力 ──
with st.container(border=True):
    st.subheader("① 入力情報")
    col1, col2 = st.columns(2)
    with col1:
        api_key  = st.text_input("Riot API Key", type="password", placeholder="RGAPI-xxxxxxxx-xxxx-...")
    with col2:
        match_id_input = st.text_input("Match ID", placeholder="JP1_xxxxxxxxx または JP1-xxxxxxxxx")

# ── 設定 ──
with st.expander("② 出力設定（デフォルトはすべてオン）", expanded=False):
    st.markdown("**ゲーム開始前分析**")
    ca1, ca2, ca3, ca4 = st.columns(4)
    rank         = ca1.checkbox("ランク情報",             value=True)
    mastery_top3 = ca2.checkbox("マスタリーTop3",         value=True)
    mastery_played = ca3.checkbox("使用チャンピオンマスタリー", value=True)
    lane_matchups_on = ca4.checkbox("レーンマッチアップ勝率", value=True)

    st.markdown("**試合結果サマリー**")
    cb1, cb2, cb3, cb4, cb5 = st.columns(5)
    vision       = cb1.checkbox("ビジョン情報",           value=True)
    items        = cb2.checkbox("最終アイテム",            value=True)
    skill_order  = cb3.checkbox("スキル習得順",            value=True)
    special_kills = cb4.checkbox("ソロキル/ペンタ",        value=True)
    shares       = cb5.checkbox("ダメージ/Gシェア",        value=True)

    st.markdown("**タイムライン詳細**")
    cc1, cc2, cc3, cc4, cc5 = st.columns(5)
    ev_kill      = cc1.checkbox("キルイベント",            value=True)
    ev_objective = cc2.checkbox("オブジェクティブ",        value=True)
    ev_level_up  = cc3.checkbox("レベルアップ",            value=True)
    ev_ult_leveled = cc4.checkbox("Rスキル習得",           value=True)
    ev_ult_used  = cc5.checkbox("アルティメット使用",      value=True)
    cc6, cc7, cc8, cc9, cc10 = st.columns(5)
    ev_plate     = cc6.checkbox("プレート破壊",            value=True)
    ev_item      = cc7.checkbox("完成品アイテム購入",      value=True)
    ev_feats     = cc8.checkbox("力の偉業",                value=True)
    ev_dragon_soul = cc9.checkbox("ドラゴンソウル",        value=True)
    ev_player_gold = cc10.checkbox("プレイヤーゴールド推移", value=True)

    st.markdown("**対象プレイヤー絞り込み**")
    pd1, pd2 = st.columns(2)
    with pd1:
        st.caption("🔵 Blue")
        pbc1, pbc2, pbc3, pbc4, pbc5 = st.columns(5)
        b_top = pbc1.checkbox("TOP", value=True, key="b_top")
        b_jg  = pbc2.checkbox("JG",  value=True, key="b_jg")
        b_mid = pbc3.checkbox("MID", value=True, key="b_mid")
        b_bot = pbc4.checkbox("BOT", value=True, key="b_bot")
        b_sup = pbc5.checkbox("SUP", value=True, key="b_sup")
    with pd2:
        st.caption("🔴 Red")
        prc1, prc2, prc3, prc4, prc5 = st.columns(5)
        r_top = prc1.checkbox("TOP", value=True, key="r_top")
        r_jg  = prc2.checkbox("JG",  value=True, key="r_jg")
        r_mid = prc3.checkbox("MID", value=True, key="r_mid")
        r_bot = prc4.checkbox("BOT", value=True, key="r_bot")
        r_sup = prc5.checkbox("SUP", value=True, key="r_sup")

    st.markdown("**AI分析への追加指示（任意）**")
    custom_note = st.text_input("カスタムノート", value="", placeholder="例：TOPレーンのマッチアップを重点的に分析して")

config = {
    "rank": rank, "mastery_top3": mastery_top3, "mastery_played": mastery_played,
    "lane_matchups": lane_matchups_on,
    "vision": vision, "items": items, "skill_order": skill_order,
    "special_kills": special_kills, "shares": shares,
    "ev_kill": ev_kill, "ev_objective": ev_objective, "ev_level_up": ev_level_up,
    "ev_ult_leveled": ev_ult_leveled, "ev_ult_used": ev_ult_used,
    "ev_plate": ev_plate, "ev_item": ev_item, "ev_feats": ev_feats,
    "ev_dragon_soul": ev_dragon_soul, "ev_player_gold": ev_player_gold,
    "player_filter": {
        "blue": {"TOP":b_top,"JG":b_jg,"MID":b_mid,"BOT":b_bot,"SUP":b_sup},
        "red":  {"TOP":r_top,"JG":r_jg,"MID":r_mid,"BOT":r_bot,"SUP":r_sup},
    },
    "custom_note": custom_note,
}

# ── 実行ボタン ──
if st.button("🚀 解析実行", type="primary", use_container_width=True):
    if not api_key:
        st.error("API Keyを入力してください")
    elif not match_id_input:
        st.error("Match IDを入力してください")
    else:
        match_id = match_id_input.strip().replace("-","_",1)
        progress_bar = st.progress(0)
        status_text  = st.empty()

        def progress_cb(val, msg):
            progress_bar.progress(val)
            status_text.text(msg)

        try:
            with st.spinner(""):
                feedback, mid = run_analysis(api_key, match_id, config, progress_cb)

            st.success(f"✅ 解析完了：{feedback['meta']['duration']} / フェーズ {list(feedback['meta']['phases'].keys())}")

            json_str  = json.dumps(feedback, ensure_ascii=False, indent=2)
            tokens    = len(json_str) // 4
            st.info(f"📊 イベント数：{sum(len(f['events']) for f in feedback['timeline'])}件　｜　トークン概算：{tokens:,} tokens")

            st.download_button(
                label     = "⬇️ JSONダウンロード",
                data      = json_str,
                file_name = f"{mid}_feedback.json",
                mime      = "application/json",
                use_container_width = True,
            )
        except Exception as e:
            st.error(f"❌ エラーが発生しました：{e}")
        finally:
            progress_bar.empty()
            status_text.empty()
