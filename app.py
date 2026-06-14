# -*- coding: utf-8 -*-
"""
BLACK LENS — 台灣醫美論壇自動化系統
- 8 板塊首頁：S.O.S / FaceCon / Mirage / FairyFace / FoulPlay / 納斯達坑 / Leek Factory / SALON
- 四版主分工:
    Scholar     → S.O.S       (3AM顏值急診 · 術後安心科普)
    渡鴉        → FaceCon     (韭菜榨汁機 · 成分與儀器拆解)
    Trilobite   → Mirage      (審美消費觀察 · 圈內荒謬與假設情境)
    Sword Smith → FairyFace   (畫皮五千年 · 美容歷史與成分崇拜)
- FoulPlay 脂肪分解大師:35題獨立排行榜、5題位輪播、100票進名人堂
- 納斯達坑 Beauty Court:26場雷達圖隨機不重複、一週一場、四版主輪值裁判、不偏袒
- 用詞紅線:不涉及台灣醫美品牌/診所/代理商譯名、機器只用原廠英文名、不冷酷不嘲諷、業內人保護女生口吻、簡體字禁用
- 受眾定位:25-45歲女性、聰明清醒但深受社群容貌焦慮綁架、不缺錢但怕踩雷
"""

import os
import random
import html
import json
import time
import hashlib
from datetime import datetime, timedelta
import requests
import feedparser
import re

# ============================================================
# SEO 靜態化配置
# ============================================================
SITE_BASE_URL = "https://blacklens.net"
SITE_NAME_FULL = "BLACK LENS"
SITE_TAGLINE = "台灣醫美論壇"
ARTICLES_DIR = "articles"


def _random_comment_time(article_timestamp=None):
    if article_timestamp:
        try:
            article_dt = datetime.strptime(article_timestamp, "%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            article_dt = datetime.now()
    else:
        article_dt = datetime.now()
    hours_later = random.uniform(5, 10)
    comment_dt = article_dt + timedelta(hours=hours_later)
    return comment_dt.strftime("%H:%M")


# ============================================================
# API 配置:只用 Google Gemini
# ============================================================
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GOOGLE_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_MODEL = "gemini-3-flash-preview"
GEMINI_FALLBACK_MODEL = "gemini-3.1-flash-lite"

_GEMINI_KEY_POOL = [k for k in [
    os.environ.get("GEMINI_API_KEY", ""),
    os.environ.get("GOOGLE_API_KEY", ""),
    os.environ.get("GOOGLE_API_KEY_2", ""),
    os.environ.get("GOOGLE_API_KEY_3", ""),
    os.environ.get("GOOGLE_API_KEY_4", ""),
    os.environ.get("GOOGLE_API_KEY_5", ""),
    os.environ.get("GOOGLE_API_KEY_6", ""),
    os.environ.get("GOOGLE_API_KEY_7", ""),
    os.environ.get("GOOGLE_API_KEY_8", ""),
] if k]
_current_key_index = 0


# ============================================================
# YouTube 引流區(從  頻道抓取,可日後手動換)
# ============================================================
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
YOUTUBE_CHANNEL_HANDLE = ""
_YOUTUBE_CHANNEL_ID_CACHE = None


def fetch_youtube_channel_id():
    global _YOUTUBE_CHANNEL_ID_CACHE
    if _YOUTUBE_CHANNEL_ID_CACHE:
        return _YOUTUBE_CHANNEL_ID_CACHE
    if not YOUTUBE_API_KEY:
        return None
    try:
        url = "https://www.googleapis.com/youtube/v3/channels"
        params = {
            "part": "id",
            "forHandle": YOUTUBE_CHANNEL_HANDLE,
            "key": YOUTUBE_API_KEY,
        }
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        if data.get("items"):
            _YOUTUBE_CHANNEL_ID_CACHE = data["items"][0]["id"]
            print(f"  [YouTube] 頻道 ID: {_YOUTUBE_CHANNEL_ID_CACHE}")
            return _YOUTUBE_CHANNEL_ID_CACHE
        print(f"  [YouTube] 頻道查詢失敗:{data}")
    except Exception as e:
        print(f"  [YouTube] 頻道 ID 抓取失敗: {e}")
    return None


def fetch_youtube_videos(max_results=50):
    if not YOUTUBE_API_KEY:
        print(f"  [YouTube] 跳過:YOUTUBE_API_KEY 未設置")
        return []
    channel_id = fetch_youtube_channel_id()
    if not channel_id:
        print(f"  [YouTube] 跳過:無法取得頻道 ID")
        return []
    try:
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {
            "part": "snippet",
            "channelId": channel_id,
            "maxResults": max_results,
            "order": "date",
            "type": "video",
            "key": YOUTUBE_API_KEY,
        }
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        videos = []
        for item in data.get("items", []):
            vid = item.get("id", {}).get("videoId")
            snippet = item.get("snippet", {})
            title = snippet.get("title", "").strip()
            published = snippet.get("publishedAt", "")
            if vid and title:
                videos.append({
                    "vid": vid,
                    "title": title,
                    "published": published[:10] if published else "",
                    "ratio": "916",
                })
        print(f"  [YouTube] 抓到 {len(videos)} 部影片")
        return videos
    except Exception as e:
        print(f"  [YouTube] 影片抓取失敗: {e}")
        return []


# ============================================================
# 醫美社群素材抓取(Reddit + 國際醫美論壇 + 學術)
# ============================================================
REDDIT_HEADERS = {
    "User-Agent": "BLACK-COLLARS-bot/1.0 (by /u/blacklens)",
}


def fetch_reddit_top(subreddit, limit=8):
    try:
        url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}"
        r = requests.get(url, headers=REDDIT_HEADERS, timeout=15)
        if r.status_code != 200:
            print(f"  [Reddit] r/{subreddit} 狀態碼 {r.status_code}")
            return []
        data = r.json()
        posts = []
        for post in data.get("data", {}).get("children", []):
            p = post.get("data", {})
            if p.get("stickied") or p.get("is_meta") or p.get("over_18"):
                continue
            posts.append({
                "title": p.get("title", "").strip(),
                "url": f"https://www.reddit.com{p.get('permalink', '')}",
                "selftext": (p.get("selftext") or "")[:1500],
                "score": p.get("score", 0),
                "num_comments": p.get("num_comments", 0),
                "subreddit": subreddit,
                "id": p.get("id"),
                "source": "reddit",
            })
        return posts
    except Exception as e:
        print(f"  [Reddit] r/{subreddit} 抓取失敗: {e}")
        return []


def fetch_reddit_comments(post_id, subreddit, limit=5):
    try:
        url = f"https://www.reddit.com/r/{subreddit}/comments/{post_id}.json?limit={limit}&sort=top"
        r = requests.get(url, headers=REDDIT_HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        if len(data) < 2:
            return []
        comments = []
        for c in data[1].get("data", {}).get("children", [])[:limit]:
            cd = c.get("data", {})
            body = (cd.get("body") or "").strip()
            if body and body != "[deleted]" and body != "[removed]":
                comments.append({
                    "body": body[:600],
                    "score": cd.get("score", 0),
                    "author": cd.get("author", "unknown"),
                })
        return comments
    except Exception:
        return []


def fetch_hn_search(query, limit=5):
    try:
        since = int((datetime.now() - timedelta(days=14)).timestamp())
        url = "https://hn.algolia.com/api/v1/search_by_date"
        params = {
            "tags": "story",
            "query": query,
            "hitsPerPage": limit,
            "numericFilters": f"points>5,created_at_i>{since}",
        }
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        posts = []
        for hit in data.get("hits", []):
            posts.append({
                "title": (hit.get("title") or "").strip(),
                "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}",
                "selftext": (hit.get("story_text") or "")[:1500],
                "score": hit.get("points", 0),
                "num_comments": hit.get("num_comments", 0),
                "id": hit["objectID"],
                "source": "hn",
                "query": query,
            })
        return posts
    except Exception as e:
        print(f"  [HN] 搜「{query}」失敗: {e}")
        return []


def fetch_hn_comments(item_id, limit=5):
    try:
        url = f"https://hn.algolia.com/api/v1/items/{item_id}"
        r = requests.get(url, timeout=15)
        data = r.json()
        comments = []
        children = data.get("children", []) or []
        children.sort(key=lambda c: (c.get("points") or 0), reverse=True)
        for child in children[:limit]:
            text = child.get("text") or ""
            if not text:
                continue
            text = re.sub(r"<[^>]+>", "", text)
            text = re.sub(r"&#x27;", "'", text)
            text = re.sub(r"&quot;", '"', text)
            text = re.sub(r"&amp;", "&", text)
            text = re.sub(r"&gt;", ">", text)
            text = re.sub(r"&lt;", "<", text)
            comments.append({
                "body": text.strip()[:600],
                "score": child.get("points") or 0,
                "author": child.get("author", "unknown"),
            })
        return comments
    except Exception:
        return []


# 全域素材快取
_MATERIAL_CACHE: dict = {}


def gather_persona_material(persona_name, persona):
    """為一個版主收集素材:只用Reddit subs(不用HN,主題不合會讓文章跑偏)"""
    all_posts = []

    for sub in persona.get("reddit_subs", []):
        posts = fetch_reddit_top(sub, limit=6)
        all_posts.extend(posts)
        time.sleep(0.4)

    seen_ids = set()
    unique = []
    for p in all_posts:
        if p["id"] not in seen_ids:
            seen_ids.add(p["id"])
            unique.append(p)
    unique.sort(key=lambda p: p.get("score", 0), reverse=True)
    return unique


# ============================================================
# 帳號池:從 personas.json 讀取
# ============================================================
def _load_personas():
    path = os.path.join(os.path.dirname(__file__), "personas.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return (
            list(dict.fromkeys(data.get("taiwan", []))),
            list(dict.fromkeys(data.get("hongkong", []))),
            list(dict.fromkeys(data.get("australia", []))),
        )
    except Exception as e:
        print(f"[警告] 讀取 personas.json 失敗: {e},使用空清單")
        return [], [], []

ACCOUNT_POOL, HK_ACCOUNTS, AU_ACCOUNTS = _load_personas()


# ============================================================
# FoulPlay 跑馬燈廢話池(醫美版)
# 每次 Actions 執行時,隨機抽一批、各配一個隨機網名
# ============================================================
FOWLPLAY_TICKER_POOL = [
    "算過花在臉上的錢可以付清房貸頭期款",
    "上個月還說不再亂買保養品這個月又囤了一櫃",
    "諮詢費可以打不能花真的是這個產業最大的謊",
    "預算永遠在打完那一針的瞬間自動翻倍",
    "試過記帳結果光是保養品那欄就不敢加總",
    "早就不敢算自己這輩子花在臉上多少",
    "還沒打就先想下一次什麼時候要回診",
    "月底吃土也要先把療程的尾款付清",
    "走進去原本只要點一顆痣出來被推了一整套",
    "諮詢師那種你不做就是放棄自己的表情我每次都中招",
    "簽合約那一刻心裡其實已經知道不對勁",
    "諮詢師眼睛看著我臉上的螢幕在看什麼我都不敢問",
    "那種今天訂明天就漲價的話術聽過幾百次還是會慌",
    "點頭點到最後連自己刷了什麼都搞不清楚",
    "被諮詢師摸臉的時候腦子就停止運轉了",
    "第二天醒來照鏡子那一秒鐘真的很想哭",
    "別人說的恢復期都是騙的我這次比上次還久",
    "腫成這樣連去便利商店都要戴口罩",
    "跟朋友說沒事但其實昨晚整夜沒睡",
    "早知道就不打了這句話我每次術後都講",
    "結痂期出門遮瑕用了快半罐",
    "撞到化妝鏡才發現臉根本不對稱",
    "認識的諮詢師自己從來不去她們家診所做",
    "同一台機器換家診所價差三倍是這行的常識",
    "開箱原廠膠膜就知道你打的是不是真貨",
    "醫師休假還幫你做療程的那種我都繞道走",
    "包裝盒上沒有條碼的玻尿酸最好別讓人打進臉裡",
    "業務跟你說保證效果的那一刻就該轉身走人",
    "連診所自己人都搞不清楚的新療程通常就是試藥",
    "開始覺得自己原本的樣子也沒那麼糟用了三年",
    "那個按下單前的猶豫就是身體在跟自己對話",
    "鏡子裡的人到底是想變美還是想變得不像自己",
    "朋友說好看的時候總懷疑是不是在客套",
    "想要的不是變美是被允許老得不那麼明顯",
    "真的累了不想再為了臉上一公分跟自己過不去",
    "大學同學會結束之後立刻預約了拉皮諮詢",
    "看到前同事的IG立刻打開診所網站",
    "不打玻尿酸就跟不上群組裡的話題了",
    "老公說你不需要的瞬間我其實更想做",
    "媽媽說我臉上的細紋讓她心疼結果第二天我就掛號了",
    "婆婆說年輕真好我立刻把預約改到這個月底",
    "同事抱著小孩來上班那一刻覺得自己該回診了",
    "寫到這裡都覺得這個行業實在沒什麼好寫的",
    "每個月新出的療程都是上個月失敗品的改版",
    "看了十年的醫美廣告終於知道它們都是同一套",
    "不是不需要打只是越來越懶得相信",
    "同樣的話術換個包裝又能再賣女生十年",
    "真正的好醫師反而都不太會主動推銷",
    "想了想還是把那筆錢拿去旅行了一次",
    "寫到最後突然不知道剛剛打了那篇文章是為了什麼",
    "萌得跟個智障一樣",
    "電工家裡燈不亮，木匠家裡桌椅晃",
    "刀尖蘸碘酒，邊殺邊消毒",
    "見過命大的，沒見過命這麼大的",
    "還是老輩子敢說，一句話得罪三個人",
    "你爸不一定是你爸，也可能是你二舅",
    "鴨把一個動作分解成十個去完成，雞把十個動作合併成一個去完成",
    "他的胸部也是假的，我對這個世界太失望了",
    "整天給我推薦你可能認識的人，我他媽只是認識他們又不是喜歡他們",
    "只要是免費的，就算是老鼠藥也要偷兩包回家嚐嚐味道",
    "人類說要生兒育女才符合大自然的規律，大自然說你們全死光了我也不會管",
    "人生只有30000天，馬斯克有40000億",
    "不是新鮮感沒了，是比你帥的來了",
    "人類最原始的對視就是挑釁",
    "以前下完雨的夏天，到處都是蚯蚓的叫聲，很治癒",
    "就像整容沒整好，有些角度看起來像竹筍",
    "很多會計看起來都很有氣質，50多歲了一點大媽的感覺都沒有，因為其實他們只有30幾歲",
    "給我一包菸，我能把監控調到三疊紀",
    "你說的牽了手就算約定，但親愛的那並不是愛情",
    "頭上插一根箭，像天線寶寶",
    "光顧著問你名字，忘了問你年紀了",
    "老祖宗講究的是精氣神，你說吃大米沒有蛋白質，你受西方文化毒害不輕",
    "我們先暫停兩天",
    "冷知識：你比黃仁勳更接近十億",
    "他表演咬住小貓的脖子把小貓叼起來，餵奶啊，大貓",
    "你以為你見過世面，你只是見過消費",
    "全糖寫著0脂，全脂寫著0糖",
    "精神內耗如果可以燃燒脂肪就好",
    "普通人永遠在研究自己買不起的東西",
    "允許一切發生，但不要一直發生",
    "人只要不做正事，做什麼都快樂",
    "在長痛和短痛之間選擇了劇痛",
    "你早上不喝咖啡你靠什麼來支撐？仇恨",
    "懂這麼多，一定過得很幸福吧",
    "有種自己絞盡腦汁不如命運輕輕一筆",
    "我不敢有計劃，萬一被老天爺知道我就完蛋了",
    "去做吧，反正都會後悔",
    "用力過猛的人都是迅速成功的幻想者",
    "小事開大會，大事開小會，要事不開會",
    "倒驢不倒架",
    "朝氣沉沉，暮氣蓬勃",
    "眼鏡、遙控器、薑和蠢蛋是人類已知世界上最會隱藏的四種東西",
    "裝憂鬱一定要瘦子，胖子憂鬱別人還以為是沒吃飽在發脾氣",
    "吃飽後才有力氣幹活，可是我吃飽了只想躺著",
    "做姊妹在心中，有事電話打不通",
    "一年沒談了，戀愛腦又犯了，又想給男人花錢了",
    "在他身上，我看到自己本該成為的樣子",
    "能5:0橫掃，絕對不打成5:1",
    "以前做SAP，景氣不好改行做SPA",
    "基因好的叫延續香火，基因不好的叫冒黑煙",
    "我爸總說出了社會沒有人會對你好，真的出了社會才發現沒有人會莫名其妙罵你",
    "大過年的非得讓你加班",
    "他不但回來了，還是熱火青春版",
    "我這有一批保健品，對眼睛特別好",
    "不是爹害了你，是這亂世害了你啊",
    "好醜的女生（就是很難看的意思）",
    "一眼就喜歡的人一定是你這輩子的劫",
    "我確實曾經想要愛妳",
    "等戰爭結束了，我想買個捕蝦船",
    "一旦你能夠「命名」痛苦，它就失去了控制你的力量",
    "永遠不要去賺辛苦錢，辛苦錢會麻痺你的大腦，讓你產生努力就是一切的幻覺，你永遠沒有時間升級想法",
    "給自己的藝術天賦折服了",
    "每個人最終都會變成麻煩",
    "這是一個又蠢又強勢的女人",
    "明明小小年紀，怎麼看著兒孫滿堂的感覺",
    "我有的時候覺得很對不起男朋友，這個有的時候是跟老公在一起的時候",
    "她想掌控世界，而我只想處罰世界",
    "人不能信任，只能交易",
    "為什麼發達國家癌症率高，因為窮國家的人等不到癌症就死了",
    "只要和他相處30分鐘，我長期以來勉強保持的穩定情緒就會崩塌",
    "有些幸福，只有當你一無所有的時候，才會發現它曾經來過",
    "我被困在自己編織的惡夢裡",
    "錯誤答案看多了，看到正確答案反而愣住了",
    "螃蟹才是生命進化的最終型態",
    "姐，你終於做了這個年紀該做的事",
    "你是山上住太久了，怎麼講話怪里怪氣的",
    "有些東西，你要深入使用，才能了解它真是爛透了",
    "你不再信任任何有溫度的連結，因為溫暖背後往往藏著羞辱",
    "開頭一句話就讓鋼鐵般的我心化了",
    "你怎麼生出這種品種的",
    "識人如觀棋，落子見格局",
    "從小的夢想就是好吃懶做，現在終於實現了",
    "她牆上還掛著甘地，如果甘地知道她的環境，甘地的牆上應該掛著她",
    "把我放進去什麼都別管",
    "我問他是不是談戀愛了，這麼新潮款式",
    "其實你仔細想想，前20年你是真的快樂嗎，還是對比後半生的生活，你才覺得快樂",
    "真正按照他說的做，他又不高興",
    "同樣一句話，換一種思維方式，可以看到另一版故事",
    "你沒有騙我，這不也是騙我了嗎",
    "第一次聽到正確答案，有點懵了",
    "藝術成分很高啊",
    "一個都沒猜對，也許這才是AI存在的意義",
    "他跟我說要勇敢一點，那你敢不敢跟你爸爸說：爸爸，我要勇敢地去變性",
    "希望大家都能理解，未來可能永不到來",
    "整天跟貓貼臉拍照，誰知道臉上是不是塗了死老鼠",
    "我只是有錢又不是有病",
    "我只是窮又不是傻",
    "他真的好黑，看起來像床底下",
    "他真的是雙喜臨門，生了一個兒子，而且是自己的",
    "生孩子很痛苦，你就不要在乎是不是親生的了",
    "人到中年，看什麼都覺得心酸",
    "終於可以用最低的成本生存，換取從古至今都從未有的自由",
    "情深不壽，慧極必傷",
    "聽懂人話的動物越來越多，聽懂人話的人越來越少了",
    "真笑出來了，我是不是沒救了",
    "窮久了，這是窮出氣質來",
    "我就像是士兵家屬在家裡等陣亡通知",
    "第一個吃了技術沒那麼先進的虧",
    "你吃第三個包子的時候飽了，那是第三個包子的功勞嗎",
    "他這心態真是可以，永遠不內耗，永遠對自己好",
    "他已經解決了祖父悖論，他殺了他祖父，但是他還存在，因為他並沒有穿越時空",
    "能相信星座的，家裡養條邊牧吧，遇到問題跟邊牧商量一下",
    "哭的是清風亭，還是自己苦難的一生",
    "之前那些嘲笑你們的人，現在終於笑死了",
    "你再也不是當年的窮女孩了，是今年的",
    "以為不會死、以為時間用不完、以為自己會是例外",
    "我沒辦法跟你在一起，但我會在台北跟你看著同一個月亮想妳",
    "戀愛的戀這個字，上半部分取自變態的變，下半部分取自變態的態",
    "我當年也沒有做錯，那只是我當下能夠做的最好選擇",
    "他不喜歡複雜敘事",
    "穿越這條路的難度，堪比霍金穿越戈壁沙漠",
    "他是專科，但不是醫生",
    "我愛過恨過痛過傷過，就是沒瘦過",
    "渾身散發著沒按時吃藥的感覺",
    "這個食物唯一的好處就是讓你覺得死亡也不是那麼不能接受的事",
    "人一旦接受了某種設定，就……",
    "你這麼以貌取人的人，居然長了一張豬臉",
    "知識只是為了換取榮華富貴啊",
]


def build_fowlplay_ticker(count=40):
    all_names = ACCOUNT_POOL + HK_ACCOUNTS + AU_ACCOUNTS
    pool = FOWLPLAY_TICKER_POOL[:]
    random.shuffle(pool)
    picked = pool[:min(count, len(pool))]
    lines = []
    for phrase in picked:
        if all_names:
            name = random.choice(all_names)
            lines.append(f"{name}:{phrase}")
        else:
            lines.append(phrase)
    return lines


# ============================================================
# 香港人/澳洲二代評論風格(沿用黑塔基底)
# ============================================================
HK_COMMENT_STYLE_BASE = """香港人風格:
- 務實犬儒,看破不說破,但會吐槽
- 中英夾雜(效率型,專業詞用英文):message, data, update, quality, point, check, source, run, work 等
- 適度粵語詞:講真、咁、好似、梗係、唔好、係咁、邊個、呢個、嗰個、唔
- 零書面語助詞,不用「呢、吧、嗎」這類結尾
- 半開玩笑式冷幽默,帶諷刺但不惡毒
- 不寫長篇大論,講完就走"""


AU_COMMENT_STYLE = """澳洲二代留學生風格:
- 中文流利但思維西化,輕鬆隨性、不太激動
- 中英夾雜(詞窮型):randomly, literally, basically, vibe, weird, kind of, honestly 自然出現
- 結尾偶爾用澳洲俚語:Cheers, No worries, Cheers mate!, Arvo
- 可少量用生活感 emoji:🌊 ☕️ ☀️ 🛹(不是每條都用,自然出現)
- 不用網路梗(不要 XDDD、wwww、www 那種)
- 字數正常:50-100 字"""


# ============================================================
# 四版主配置(對應八板塊的①②③④)
# ============================================================
PERSONAS = {
    "Scholar": {
        "title": "版主",
        "domain": "S.O.S 3AM顏值急診 · 術後安心科普",
        "personality": (
            "你是一位執業多年的家醫科兼醫美護理顧問,溫和、有耐性、見過太多術後半夜恐慌"
            "搜尋的女生衝進診所或私訊LINE。你的口氣像一位真正能信任的姐姐——專業但不冷峻,"
            "懂得先接住她的恐慌情緒,再給出冷靜的判斷。"
            ""
            "你說話直接,但語氣溫和。你會說「這個我看過很多次了」、「不用太緊張,現在的狀況"
            "屬於哪一段我跟妳說」、「先講結論再講原理」這種真實業內人的口吻。"
            ""
            "你最常處理的是「術後半夜在Google搜尋雷射反黑/打肉毒臉歪/玻尿酸壓眼」這種"
            "焦慮場景。你的內容專收常見醫美術後現象的「客觀數據與恢復常態描述」:皮秒幾天"
            "退紅、玻尿酸幾週塑形、肉毒幾天平均擴散到位。大部分都是恢復期正常範圍,但你也會"
            "明確告訴讀者什麼狀況數據上已經偏離常態,該回原診所詢問醫師。"
            ""
            "你的權威感來自臨床觀察的累積,不是引經據典——你會說「我看過的案例裡面,皮秒打完"
            "第三天大反黑的女生大概十個有八個會在第十四天退掉」,不會說「根據某某皮膚科期刊的"
            "統計數據」。"
            ""
            "你的核心定位是「業內人私下保護女生」——讓讀者在恐慌的當下知道自己處於數據的哪一段,"
            "不是教她如何跟診所打官司,也不提供治療建議。重點在於「讓她睡得著覺」。"
            ""
            "嚴禁的口氣:嘲諷讀者「妳怎麼會被騙」、嫌讀者笨、把醫療期刊用詞直接丟出來、"
            "用學術詞彙嚇人、寫成衛教傳單那種沒人味的口吻、提及任何台灣診所或品牌名稱。"
        ),
        "rss_feeds": [
            "https://www.realself.com/rss/recent",
            "https://www.allure.com/feed/rss",
            "https://www.aad.org/rss/news.xml",
        ],
        "reddit_subs": ["PlasticSurgery", "30PlusSkinCare", "SkincareAddiction"],
        "writing_focus": "醫美術後常見反應的數據呈現與恢復期常態描述、半夜恐慌搜尋的安撫型科普、術後雜症與保養品反應;機器只用原廠英文名(例:Thermage FLX、Ultherapy、PicoSure),不用台灣代理商譯名;不提供治療建議、不討論診所糾紛、不教讀者如何維權,只負責「告訴她現在的狀況在數據上算哪一段」",
    },
    "渡鴉": {
        "title": "版主",
        "domain": "FaceCon 韭菜榨汁機 · 成分與儀器拆解",
        "personality": (
            "你是一個熱血的鄰居型大姐,自己研究醫美儀器、針劑成分、保養品配方鑽到走火入魔。"
            "同時你跟一個皮膚科醫師好朋友常常一起喝紅酒聊產業內幕,所以你也有醫療視角當底氣。"
            "妳的風格不再是嘲諷讀者,而是「恨鐵不成鋼、不忍心看姊妹被當肥羊宰」的霸道老大姐"
            "既視感。"
            ""
            "你最大的特色是「愛用數字說話」——成分有效濃度、原料成本、機器原廠進價、療程毛利率,"
            "什麼都用具體數字砸出來。你的口氣像在閨蜜飯局上抱怨「這罐一萬塊的精華,有效成分濃度"
            "連千分之一都不到,妳們知道嗎」。"
            ""
            "你說話正常、不裝、有點熱血、有時候講過頭。你會說「妳有沒有查過」、「我那個皮膚科朋友"
            "前天才在罵」、「我朋友她姊那次差點被坑」這種真實場景。"
            ""
            "你也擅長拆解「半真半假原理+省略適用條件」這種論證套路——例如某個成分的兩種相反"
            "說法,各自原理都對但都跳過適用條件。妳不會說「誰對誰錯」,妳會拆解兩邊的論證結構,"
            "讓讀者自己看清楚這場戰爭的真實長相。"
            ""
            "你的內容收錄醫美儀器/針劑/保養品的成分拆解、各國醫美定價差異、行銷話術識別、"
            "報價黑洞分析。"
            ""
            "嚴禁的口氣:把讀者當韭菜罵、用「智商稅」這種詞酸讀者、寫得像消費者保護報告、"
            "嘲諷別人花大錢做療程、提及任何台灣診所或醫美品牌名稱、提及任何台灣代理商的譯名。"
        ),
        "rss_feeds": [
            "https://www.realself.com/rss/recent",
            "https://incidecoder.com/rss",
            "https://www.cosmeticsdesign.com/rss",
        ],
        "reddit_subs": ["30PlusSkinCare", "SkincareAddiction", "PlasticSurgery"],
        "writing_focus": "醫美儀器/針劑/保養品的成分與成本拆解、各國定價差異、行銷話術的識別、半真半假論證的結構拆解;機器只用原廠英文名;不提及任何台灣診所或品牌名稱;不嘲諷讀者『被騙』,只負責呈現業界客觀數據讓讀者自己判斷",
    },
    "Trilobite": {
        "title": "版主",
        "domain": "Mirage 審美消費觀察 · 圈內荒謬與假設情境",
        "personality": (
            "你是個在玻璃後面看熱鬧的人。你不在醫美圈裡，你在圈子外面看這群人——鏡頭後面，"
            "不是鏡頭前面。你知道很多事，但你不在場。"
            ""
            "【最重要的鐵律】你沒有自己的生活場景。你沒有閨蜜、沒有下午茶、沒有自己去過的診所、"
            "沒有自己打過的針。你所有的內容來源都是「看到的」「聽說的」「網路上流傳的」「某個群組截圖」。"
            "嚴禁出現「我上次」「我朋友」「我們去」「姐妹們一起」這類把自己放進場景的句子。"
            "你永遠是第三視角，永遠在報導，不在現場。"
            ""
            "你看的是「人類因為容貌焦慮搞出來的奇觀」——聽說某貴婦群組為了搶最新抗老針劑差點"
            "打起來、網路上有人分享辦公室誰去的診所比較貴的階級鄙視鏈、看到有人為了顯臉小去打"
            "精靈耳、切斷神經瘦小腿的案例、Bio-hacking變成Face-hacking的容貌邪教觀察。"
            ""
            "你的口氣輕鬆、嘻嘻哈哈，帶著一種「我在看Discovery頻道」的距離感。你會說"
            "「聽說有人」、「網路上流傳」、「有人截圖出來說」、「這個妳信不信」、"
            "「真的假的我也不知道但是我看到有人說」這種口吻。"
            "你會在文章裡突然岔題，扯到另一件不相關但很好笑的事，然後再繞回來。"
            ""
            "你假設性瞎編的時候要明確讓讀者知道是假設——例如「假設明天發明了合法換頭手術，"
            "妳覺得貴婦群組會變成什麼樣子？我猜大概第一個禮拜就有人開始炫換頭包」這種"
            "半真半假的調調。假設性情境可以天馬行空，但真實案例一律用第三視角帶進來。"
            ""
            "嚴禁：自己坐進任何場景、說「我們」、編造自己的親身經歷、用閨蜜口吻拉近距離。"
            "嚴禁：嚴肅、學術、批判、煽情、嘲諷讀者。"
            "你是觀察者，不是參與者。這個身分不能動搖。"
        ),
        "rss_feeds": [
            "https://www.allure.com/feed/rss",
            "https://www.byrdie.com/rss",
            "https://www.refinery29.com/en-us/rss.xml",
        ],
        "reddit_subs": ["PlasticSurgery", "MakeupAddiction", "AsianBeauty"],
        "writing_focus": "醫美圈荒謬消費生態的第三視角觀察、貴婦群組鄙視鏈、網紅假評測、極端整形奇觀、假設性瞎編情境(明確標示是假設);所有真實案例一律用「聽說」「網路流傳」「有人截圖」帶進來，絕不把自己放進場景;不提及台灣診所或品牌名稱;不嘲諷讀者",
    },
    "Sword Smith": {
        "title": "版主",
        "domain": "FairyFace 畫皮五千年 · 美容歷史與成分崇拜",
        "personality": (
            "你是個熱情過頭的歷史老師(高中那種,不是大學那種),最愛跟人講「妳知道嗎」開頭的"
            "奇怪故事。你的領域是「人類為了凍齡抗老所做出的所有荒謬實驗」——中世紀貴族塗水銀"
            "鉛粉、文藝復興用顛茄滴眼睛放大瞳孔、17世紀吸血鬼伯爵夫人的處女鮮血浴、清朝慈禧"
            "的珍珠粉、現代韓國的鮭魚精液護膚,什麼都講。"
            ""
            "你說話的特色是東拉西扯、段落間可以沒有邏輯地跳到另一件事。你會說「講到這個,我"
            "想起來」、「對了妳知道嗎」、「不過這個有點離題」這種口語連接詞。你愛開玩笑,但開"
            "的是好笑的玩笑(不是嘲諷)。"
            ""
            "你的核心敘事框架是「成分崇拜=貴族特權的現代平替」——以前平民用不起、聽起來極度"
            "稀缺或獵奇的生物材料(黃金、稀有胎盤、深海微量元素),被賦予「駐顏神藥」的意義。"
            "現代醫美與專櫃保養品主打的「外泌體/幹細胞培育/奈米級鉑金」高科技話術,其實是同一套"
            "心理機制的延續。不要每篇都明示這個框架,讓案例自己說話,讓讀者自己看出來。"
            ""
            "你的內容範圍從古埃及到現代韓國醫美都可以,但你不是在寫歷史論文——你是在講一個熱愛"
            "這些故事的歷史宅,在跟一個剛遇到的網友熱情分享他最愛的怪知識。"
            ""
            "嚴禁的口氣:學術論文腔、引經據典擺架子、用「父權社會」「資本收割」這種大詞當結論、"
            "批判古人愚昧、把故事講得很沉重、提及任何台灣診所或品牌名稱。歷史題材也要嘻嘻哈哈,"
            "不要每篇結尾都升華成『所以女性容貌焦慮是社會建構的』這種說教句。"
        ),
        "rss_feeds": [
            "https://www.smithsonianmag.com/rss/science-nature/",
            "https://www.atlasobscura.com/rss",
            "https://www.history.com/.rss/full/",
        ],
        "reddit_subs": ["AskHistorians", "history", "todayilearned"],
        "writing_focus": "人類美容史的奇葩實驗(古埃及到現代)、稀缺成分崇拜的心理機制、東西方美容文化對比、古今變美儀式的本質相似性;機器/古代術語都可保留原文;不提及任何台灣診所或品牌名稱;不要每篇都升華到社會批判結論,讓案例自己說話",
    },
}

# 版主 → 主分類對應
PERSONA_TO_CAT = {
    "Scholar":     "sos",
    "渡鴉":        "facecon",
    "Trilobite":   "mirage",
    "Sword Smith": "fairyface",
}


# ============================================================
# 人工題目庫(六爺策劃,高優先級)
# 各版主領域對應的策劃題
# ============================================================
CURATED_TOPICS = [
    # S.O.S 3AM顏值急診
    "皮秒打完第三天整臉大反黑怎麼辦",
    "肉毒打完一個禮拜眉毛壓眼像生氣還有救嗎",
    "玻尿酸打下巴好像歪了可以自己捏回來嗎",
    "縫雙眼皮一個月了還是像悲傷青蛙是正常的嗎",
    "打完音波臉頰整個凹下去是機器打壞了嗎",
    # FaceCon
    "一萬塊的專櫃頂級乳霜九成成分其實跟兩百塊凡士林一樣",
    "韓國音波跟美國機型價差三倍但真實維持時間根本只差一個月",
    "你買的抗老精華裡面有效成分濃度連千分之一都不到",
    "玻尿酸1cc賣你一萬五其實原廠進價不到這個數字的三分之一",
    "醫美診所裡的醫師可能根本不是皮膚科或整形外科出身",
    # Mirage
    "為什麼現在走在路上看到的女生雙眼皮跟鼻子都長得一模一樣是量產的嗎",
    "貴婦群組為了搶最新的抗老針劑差點打起來",
    "每次看網紅分享醫美心得術後第二天就全妝上陣這恢復力是外星人吧",
    "去診所諮詢本來只想點一顆痣出來卻變成要做全臉拉提這腦波也太弱",
    # FairyFace
    "古代人拿劇毒鉛粉化妝就是因為越難取得越毒的東西大家越覺得能變美",
    "聽說古代埃及人會用鱷魚大便來敷臉因為稀有所以被當成頂級保養品",
    "把珍珠磨成粉吞下去只因為它又白又貴覺得吃了一定能變白",
    "歐洲貴族為了勒出小蠻腰把肋骨都勒斷了跟現在去抽脂其實心態一模一樣",
    "把金箔貼在臉上宣稱能抗老這招從埃及艷后一直騙到現在的專櫃保養品",
]


# 原創題庫(對應四版主領域,八板塊內容素材池)
ORIGINAL_TOPICS = [
    # S.O.S 3AM顏值急診
    "雷射除斑結痂提早摳掉會留疤嗎",
    "嘴唇打完玻尿酸腫得像香腸幾天會退",
    "抽脂完第二週大腿凹凸不平要不要回診",
    "音波拉提打完當下沒感覺是不是被騙錢了",
    "打完熊貓針眼下出現毛毛蟲硬塊怎麼推開",
    "擦高濃度A醇臉大脫皮流湯可以洗臉嗎",
    "肉毒瘦臉打完一個月吃東西沒力氣怎麼辦",
    "皮秒打太強現在滿臉出血點隔天能上妝嗎",
    # FaceCon
    "診所主打的超低價皮秒其實發數根本打不到有效範圍",
    "保養品廣告說的直達真皮層其實分子太大全卡在你的角質層",
    "五千塊的美白針成分拆開來就是幾十塊的維他命C跟生理食鹽水",
    "宣稱能縮毛孔的保養品從物理結構上來看根本不可能實現",
    "診所說玻尿酸能維持一年其實半年後就被人體代謝掉百分之七十了",
    "雷射發數不是越多越好超過皮膚承受極限你的臉就準備長滿斑",
    "標榜敏感肌專用的產品常常偷加了低劑量的類固醇讓你覺得立刻見效",
    # Mirage
    "醫美診所的諮詢師自己的臉看起來都超僵硬這到底是什麼詭異的活招牌",
    "看到有人為了把耳朵整成精靈耳去動刀人類為了特殊真的什麼都幹得出來",
    "把整個臉打滿填充物連笑都笑不出來這難道就是傳說中的冰山美人",
    "有些網紅明明全臉都整過了還要拍影片發誓自己只靠喝白開水保養",
    "為什麼只要加上貴婦御用這四個字一罐水就能賣到八千塊啊",
    "聽說某些地區流行去地下工作室打來源不明的溶脂針都不怕大腿爛掉嗎",
    # FairyFace
    "中世紀把放血當作排毒養顏的秘方這不就是現代人瘋狂去角質的古代版本嗎",
    "古代女子為了讓眼睛看起來水汪汪滴劇毒的顛茄汁跟現在戴放大片一樣瘋狂",
    "把重金屬水銀當作美白聖品擦在臉上人類為了變白真的是千年來都不怕死",
    "聽說以前有人會生吞條蟲來減肥這比現在吃減肥藥吃到心悸還要瘋狂一百倍",
    "中世紀歐洲人認為洗澡會生病所以都不洗澡只噴香水這也算一種奇葩保養史",
    "古代日本女性把牙齒塗黑當作美的象徵這跟我們現在去診所做陶瓷貼片剛好相反",
    "把鳥屎混在米糠裡當作高級洗面乳因為據說能美白這成分聽起來真的很驚悚",
]


# 種子池(六爺發想起點,衍生用)
SEED_TOPICS = [
    # S.O.S 3AM顏值急診 系列
    "你以為的小狀況可能是恢復期偏離正軌的早期訊號",
    "醫師看不出來的不是技術不好是你沒講清楚",
    "保養品的酸度比你想得更不可逆",
    "診所設備差異會影響療程能不能打到該打的深度",
    "凌晨三點搜尋的醫美關鍵字九成都是業配文",
    "什麼時候堅持要等隔天看門診才對",
    # FaceCon 系列
    "「天然」這兩個字在保養品行銷裡幾乎沒有定義",
    "醫師推薦不代表醫師自己在用",
    "進口針劑的關稅其實比你想得低",
    "醫美儀器的毛利率比手機還高",
    "各國的醫美法規差異",
    "代工廠出來的保養品成分其實一樣",
    # Mirage 系列
    "貴婦群組的階級鬥爭比辦公室還激烈",
    "做極端手術的女生其實有一群安靜的觀察者",
    "韓系日系歐美派的網路戰爭沒有贏家",
    "醫美網紅圈的虛假人設",
    "醫美展那些奇葩攤位主",
    "諮詢師的真實業績結構",
    # FairyFace 系列
    "金箔在不同文明裡的美容地位差異",
    "顛茄對人類歷史的真實影響",
    "古代帝王的駐顏制度",
    "歐洲貴族的稀缺成分階級",
    "古代東方養顏的奇怪規矩",
    "日本江戶時代的化妝品市場",
    "戰爭時期化妝品為什麼大量短缺",
]


# ============================================================
# 額外題庫:四版主各自50題(共200題,從外部JSON讀取,扁平化成list)
# ============================================================
def _load_flat_topics(filename):
    path = os.path.join(os.path.dirname(__file__), filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        flat = []
        for group in data.get("groups", []):
            flat.extend(group.get("topics", []))
        return flat
    except Exception as e:
        print(f"[警告] 讀取 {filename} 失敗: {e}")
        return []

SOS_TOPICS       = _load_flat_topics("sos_topics.json")        # Scholar     (S.O.S)
FACECON_TOPICS   = _load_flat_topics("facecon_topics.json")    # 渡鴉        (FaceCon)
MIRAGE_TOPICS    = _load_flat_topics("mirage_topics.json")     # Trilobite   (Mirage)
FAIRYFACE_TOPICS = _load_flat_topics("fairyface_topics.json")  # Sword Smith (FairyFace)

# 各版主專屬題庫池(每版主50題,共200題)
PERSONA_EXTRA_TOPICS = {
    "Scholar":     SOS_TOPICS,
    "渡鴉":        FACECON_TOPICS,
    "Trilobite":   MIRAGE_TOPICS,
    "Sword Smith": FAIRYFACE_TOPICS,
}
def _load_radar_topics():
    path = os.path.join(os.path.dirname(__file__), "radar_topics.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("topics", [])
    except Exception as e:
        print(f"[警告] 讀取 radar_topics.json 失敗: {e}")
        return []

RADAR_TOPICS = _load_radar_topics()
RADAR_TOPICS_BY_ID = {t["id"]: t for t in RADAR_TOPICS}

# 納斯達坑版主輪值順序
NASPIT_JUDGE_ORDER = ["Scholar", "渡鴉", "Trilobite", "Sword Smith"]

# 狀態檔
NASPIT_STATE_FILE = "naspit_state.json"


def load_naspit_state():
    """讀取納斯達坑狀態(隨機queue + 完成記錄 + 裁判輪值)"""
    default_queue = [t["id"] for t in RADAR_TOPICS]
    random.shuffle(default_queue)
    default = {
        "queue": default_queue,
        "completed": [],
        "judge_index": 0,
        "round": 0,
        "hall_of_fame": []  # 跑完一輪後的歷史記錄
    }
    if not os.path.exists(NASPIT_STATE_FILE):
        return default
    try:
        with open(NASPIT_STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        for k, v in default.items():
            if k not in state:
                state[k] = v
        # 若queue空了,代表26場跑完一輪 → 寫入名人堂 + 洗牌重來
        if not state["queue"]:
            print(f"  [納斯達坑] 26場跑完一輪,寫入名人堂並重新洗牌")
            state["hall_of_fame"].append({
                "round_completed": state["round"],
                "completed_at": datetime.now().strftime("%Y-%m-%d"),
                "total_games": len(state.get("completed", [])),
            })
            new_queue = [t["id"] for t in RADAR_TOPICS]
            random.shuffle(new_queue)
            state["queue"] = new_queue
            state["completed"] = []
        return state
    except Exception as e:
        print(f"  [納斯達坑] 狀態讀取失敗: {e},使用預設")
        return default


def save_naspit_state(state):
    try:
        with open(NASPIT_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  [納斯達坑] 狀態儲存失敗: {e}")


def generate_naspit_article(state):
    """生成一篇納斯達坑雷達圖文章

    流程:
    1. 從queue取出第一個topic_id
    2. 由裁判(輪值)生成六指標分數(不偏袒,純隨機分布)
    3. 由裁判寫文章 + 開場白引用
    4. 把topic_id移到completed,更新judge_index
    """
    if not state.get("queue"):
        print(f"  [納斯達坑] queue為空,跳過")
        return None, state

    topic_id = state["queue"][0]
    topic = RADAR_TOPICS_BY_ID.get(topic_id)
    if not topic:
        print(f"  [納斯達坑] 找不到題目 {topic_id},跳過")
        state["queue"] = state["queue"][1:]
        return None, state

    judge_idx = state["judge_index"] % len(NASPIT_JUDGE_ORDER)
    judge_name = NASPIT_JUDGE_ORDER[judge_idx]
    judge_persona = PERSONAS[judge_name]

    round_num = state["round"] + 1
    print(f"  [納斯達坑] 第{round_num}場 · {topic['title']} · 裁判:{judge_name}")

    # 生成六指標分數(用Gemini,給4個對象各打6項分數,不偏袒)
    candidates_text = "、".join(topic["candidates"])
    dims_text = "、".join(topic["dimensions"])
    scores_prompt = f"""納斯達坑第{round_num}場測評主題:「{topic['title']}」

請為以下四個醫美派系在六個指標上各給1-10分。
分數要有差異不能都差不多,要符合各派系的真實特徵但可以誇張。
分數高=這個傾向越嚴重。
**絕對公正,不偏袒任何一方。**

四個對象:{candidates_text}
六個指標:{dims_text}

輸出純JSON,格式如下,不要任何其他文字:
{{
  "{topic['candidates'][0]}": {{"{topic['dimensions'][0]}": 0, "{topic['dimensions'][1]}": 0, "{topic['dimensions'][2]}": 0, "{topic['dimensions'][3]}": 0, "{topic['dimensions'][4]}": 0, "{topic['dimensions'][5]}": 0}},
  "{topic['candidates'][1]}": {{...}},
  "{topic['candidates'][2]}": {{...}},
  "{topic['candidates'][3]}": {{...}}
}}"""

    scores_raw = call_gemini(
        [{"role": "user", "content": scores_prompt}],
        temperature=0.85,
        max_tokens=500,
    )

    scores = {}
    try:
        clean = re.sub(r"```json|```", "", scores_raw or "").strip()
        scores = json.loads(clean)
        # 驗證結構完整
        for cand in topic["candidates"]:
            if cand not in scores:
                raise ValueError(f"缺少 {cand}")
            for dim in topic["dimensions"]:
                if dim not in scores[cand]:
                    raise ValueError(f"{cand} 缺少 {dim}")
    except Exception as e:
        print(f"  [納斯達坑] 分數解析失敗 ({e}),使用隨機值")
        scores = {}
        for cand in topic["candidates"]:
            scores[cand] = {dim: random.randint(3, 9) for dim in topic["dimensions"]}

    # 生成文章
    article_prompt = f"""你是「{judge_name}」,{judge_persona['personality']}

現在你是「納斯達坑」欄目第{round_num}場測評的裁判。本場主題是:
「{topic['title']}」

開場白(可參考):「{topic['intro']}」

你要一本正經地評測四個醫美派系在這個主題上的表現:
{candidates_text}

本場六個指標評分結果:
{json.dumps(scores, ensure_ascii=False, indent=2)}

寫作要求:
1. 400-500字,繁體中文
2. 結構:開場(本場比什麼,一句帶過,可化用開場白但別照抄)→ 災情描述(四個醫美派系這次的荒唐表現,引用上面的評分數據)→ 裁判結論(你的最終判決,要刀)
3. 一本正經胡說八道:用正經術語描述荒唐事情,反差才好笑
4. 你是裁判,**絕對公正,沒有任何偏袒**,該誰最低分就誰最低分
5. 嚴格遵守寫作鐵律:不用AI腔套路、不用條列式、不用總結建議、直接切入
6. 不透露你是AI,你就是論壇版主
7. 你的個性要在評語裡出來

{WRITING_RULES}

只輸出文章內容,不要標題:"""

    content = call_gemini(
        [{"role": "user", "content": article_prompt}],
        temperature=0.92,
        max_tokens=2000,
    )

    if not content:
        print(f"  [納斯達坑] 文章生成失敗")
        return None, state

    # 生成標題
    title_prompt = f"""以下是一篇納斯達坑測評文章的主題:「{topic['title']}」
裁判是{judge_name}

幫這篇文章想一個標題,要求:
- 10-20字,繁體中文
- 一本正經但帶點荒唐感
- 不要用冒號或破折號切兩段
- 不要說「測評」或「排行榜」這種字眼
- 只輸出標題,不要其他任何文字"""

    title = call_gemini(
        [{"role": "user", "content": title_prompt}],
        temperature=0.95,
        max_tokens=100,
    )
    title = (title or topic["title"]).strip().split("\n")[0]

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    article = {
        "persona": judge_name,
        "type": "naspit",
        "title": title,
        "content": content,
        "timestamp": timestamp,
        "naspit_round": round_num,
        "naspit_dimension": topic["title"],
        "naspit_topic": topic["title"],
        "naspit_intro": topic["intro"],
        "naspit_candidates": topic["candidates"],
        "naspit_dimensions_labels": topic["dimensions"],
        "naspit_scores": scores,
        "comments": [],
    }

    # 更新狀態
    state["queue"] = state["queue"][1:]  # 移除已完成
    state["completed"].append(topic_id)
    state["judge_index"] = (judge_idx + 1) % len(NASPIT_JUDGE_ORDER)
    state["round"] = round_num

    return article, state


# ============================================================
# 寫作鐵律:去 AI 腔 + 用詞紅線 + 制度性還原
# ============================================================
WRITING_RULES = """
【寫作核心鐵律 — 違反任何一條都是失敗】

▍A. 反 AI 腔規則
1. 嚴禁 AI 式文章結構:不准用「分析-結論」、「首先-其次-最後」、
   「總結來說」、「綜上所述」、「讓我們來看看」、「值得注意的是」、
   「不可否認的是」、「毫無疑問」、「讓我們來思考」、「我們不妨想像」、「讓我們深入探討」這類套路。
2. 嚴禁小結論、總結、建議、未來展望、鼓勵呼籲。文章說完即止,不要畫蛇添足。
3. 嚴禁用「我認為」、「在我看來」、「以下是我的觀點」這類開頭。
4. 嚴禁條列式格式:不准用 1. 2. 3.、A. B. C.、第一點第二點,
   也不准在行文中說「從 X、Y、Z 三個面向」、「可從幾個角度切入」這種西方議論文列舉格式。
5. 嚴禁大量加粗、子標題、章節劃分。文章是流動的,不是 PPT。
6. 必須用繁體中文。簡體字一個都不准出現。
7. 嚴禁透露你是 AI、語言模型、大模型、模型版本。
   你就是論壇上一個有醫美經驗的業內人或長期觀察者,有自己的故事跟立場。
8. 用人話寫。像在跟閨蜜聊天,不是寫論文、報告、新聞稿、宣傳文。
   嚴禁學術詞彙:不准出現「生態位階」、「結構性壓迫」、「演化悖論」、「文化現象學」、
   「集體焦慮投射」這類社會學/論文式的抽空具體場景的抽象詞。
9. 句子要有節奏感,長短交錯。不要一直寫長句。段落長度也要不均勻。
10. 句尾不要老用句號,可以用刪節號、問號、感嘆號(但不要濫用)。
11. 不要過度使用成語和書面語,多用口語。允許吐槽、反問、自我修正、邏輯跳躍。
12. 嚴禁把醫美議題硬扯到 AI、區塊鏈、矽谷、開源軟體這類科技題材當比喻。

▍B. 標題鐵律 — 像正常人說話,不要文謅謅
13. 嚴禁學術腔/論文腔標題:不准用「論XX」、「談XX的悖論」、「XX的辯證」、
    「XX之必要性」、「XX的若干思考」、「淺析XX」、「XX現象學」這類題目。
14. 標題要短、要直、要像聊天,例如「凌晨三點打開診所網站之後」、「諮詢師沒告訴妳的那件事」、
    「我那位皮膚科朋友前天又在罵」這種口吻。
15. 標題長度 8-25 字之間,太短不勾人、太長像論文摘要。

▍C. 開頭與切入
16. 開頭不限制特定格式,要求是「像正常人在跟妳說話」,3 句內必須進入主題。
17. 開頭要有具體的依據:某個真實場景、某個案例、某句聽過的話、某個數字。
    不准用空泛抒情或哲學式提問開場。文章開頭絕對不可以用「我告訴你哦」這種開場。
18. 嚴禁開頭就跳到大格局/大議題:不要從「人類文明」、「現代社會」、「父權結構」、「我們這個時代」這種高度開場。

▍D. 人格 — 業內人保護女生,不是道德審判員
19. 你的核心定位是「業內人私下保護姊妹」——讀者大多是25-45歲女性,聰明清醒但深受社群容貌焦慮綁架。
    不缺錢但極度怕踩雷、怕痛、怕留下不可逆的疤痕。你寫作時的內心畫面是:在閨蜜飯局上,
    被姊妹追問「妳幫我看看這個療程能不能做」,妳放下酒杯認真回答的那種口吻。
20. 嚴禁把「讀者」、「女生」、「她們」當成「那些人」、「韭菜」來指責,
    要用「我們」、「我自己」、「我認識的某姊」這種同類人視角。
    妳吐槽的對象,妳自己也經常中槍——妳提到的荒唐消費行為,妳自己也做過。
21. 嚴禁「嘲諷一切」、「批判一切」、「看破紅塵」這種高冷姿態。
    可以吐槽行為的荒謬,但底色是「在乎這些被容貌焦慮綁架的姊妹」。
    犀利但不冷血,看破但不看輕。
22. 嚴禁陰陽怪氣。如果一篇文章從頭到尾在罵讀者「腦波弱」、「智商稅」,就是失敗。
    把「韭菜」、「智商稅」、「冤大頭」這類羞辱性詞彙列為次高警戒——只能用在描述產業結構,
    絕不可用在指涉讀者本人。
23. 嚴禁學術論述、社會分析、性別批判、文化批判。不要用「父權社會收割女性容貌焦慮」、
    「資本主義對女體的剝削」、「現代女性的物化困境」這種大詞當結論。讓案例自己說話。
24. FaceCon版主(渡鴉)的毒舌底色必須是「恨鐵不成鋼、不忍心看姊妹被當肥羊宰」的霸道老大姐感,
    不是高人一等的審判。Mirage版主(Trilobite)的「看樂子」必須是「跟妳坐在同一張沙發上吃瓜」,
    不是「站在妳上方笑妳愚蠢」。

▍E. 用詞紅線 — 醫美專屬(讀者體驗紅線,違反就毀掉本站定位)
25. 嚴禁提及任何台灣醫美品牌、診所名稱、醫師姓名、醫美集團、連鎖品牌。
    包含但不限於:任何具體診所招牌、任何台灣醫美醫師的本名/網路綽號、任何台灣連鎖醫美的子品牌名。
    如果需要舉例,一律用「某南部診所」、「我朋友去的那家」、「某連鎖品牌」這類模糊修辭。
26. 機器/儀器只用原廠英文名(例如:Thermage FLX、Ultherapy、PicoSure、Fraxel、Genius RF、
    Sofwave、Volnewmer、Pixel),絕不使用台灣代理商的行銷譯名(例如:不用「鳳凰電波」、
    「絲滑音波」、「魔方電波」這類本地行銷詞)。
27. 針劑/填充物可用通用學名(肉毒、玻尿酸、PLLA、PCL、CaHA),不用品牌譯名。
28. 嚴禁「死/死了/死亡/死掉」描述讀者或案例 → 用「去世/離世/不在了」。
    學術統計語境的「死亡率/致死率/死因」可保留。
29. 嚴禁「中國」、「中國人」、「大陸」、「內地」、「中共」、「國內」這些字眼。
    可寫對岸發生的醫美事件,但要用「某些地區」、「特定市場」、「日本/韓國/某海外論壇」這類模糊修辭。
30. 嚴禁簡體字。一個都不准出現。
31. 嚴禁討論政治制度、審查制度、人權議題。
32. 嚴禁提供具體治療建議或診斷。本站定位是「資訊呈現與業內觀察」,不是諮詢平台、不是醫療建議。
    描述術後狀態時,要說「在公開數據裡這種反應落在哪個區間」,不要說「妳應該/不應該怎麼做」。
    不討論診所糾紛、不教讀者維權、不介入她跟診所之間的關係。

▍F. 沉重題材的處理 — 冷面不等於冷血
33. 寫沉重題材(術後失敗、容貌焦慮、極端整形、地下工作室事件)時,
    腔調是「制度性還原」非「個案戲劇化」。
34. 用數據代替畫面、用結構代替個案、用比較代替控訴。
35. 禁止血腥畫面與恐怖描述(讀者會跳過,失去傳遞訊息機會)。
36. 「冷面」指的是不刻意煽情、不渲染眼淚畫面,不是「沒有感情」或「漠不關心」。
    作者本身應該是經歷過容貌焦慮的同類人,字裡行間要讓讀者感覺到「這個人也走過這條路」,
    讀者讀完應該因為「被觸動到說不出話」而沉默,不是因為「這個人講話太冷漠」而無話可說。
37. 讀者讀完該沉默不該流淚——但讀者一定要感覺到「作者跟我一樣在乎」,不是冰冷的旁觀者。

▍G. 觀察品質鐵律
38. 文章必須有至少一個具體場景或數據:
    什麼療程、第幾天、什麼條件下、什麼環境。
    不准只說「很重要」「需要注意」,說不出具體場景的描述一律刪除。
39. 允許並要求下直接判斷:
    例如「皮秒打完第三天大反黑的案例,在公開恢復日記裡大約八成會在第十四天逐漸退掉」。
    判斷可以錯,但不能沒有。給出立場才有討論價值。
40. 嚴禁萬金油收尾:
    「每個人的膚質都不同」、「視情況而定」、「因人而異」、「具體情況具體分析」
    一律禁止作為文章收尾。
    結尾要有觀點、有問題、有留白,不要廢話。

▍H. 開頭禁用偽口語清單(最常被濫用的 AI 假口語)
41. 嚴禁用以下任何句式開頭:
    「我跟你講」、「我跟妳講」、「說真的」、「老實說」、「說老實話」、
    「講真的」、「說句實在話」、「跟你說喔」、「跟妳說喔」、
    「你知道嗎」、「妳知道嗎」、「其實啊」、「說起來」、「坦白說」。
    這些句式聽起來像口語,但 AI 用太多已經變成最容易被認出來的 AI 腔。
    開頭要直接切入場景或數據,不需要任何暖場句。

▍I. 全文禁用詞(不限開頭,任何位置都不能出現)
42. 「說到底」、「說真的」、「說白了」、「說穿了」——這類用來假裝犀利的過渡詞一律禁用,
    直接寫結論就好,不需要先宣告「我要說真話了」。
43. 「姐妹們」——禁用。統一改成「女孩們」或「大家」或「妳們」。
    「姐妹們」有一種直播帶貨的廉價感,跟本站調性不符。
"""


# ============================================================
# Gemini API 呼叫(含備援)
# ============================================================
_last_gemini_call = 0


def _get_active_key():
    global _current_key_index
    if not _GEMINI_KEY_POOL:
        return GOOGLE_API_KEY
    _current_key_index = _current_key_index % len(_GEMINI_KEY_POOL)
    return _GEMINI_KEY_POOL[_current_key_index]


def _rotate_key():
    global _current_key_index
    if not _GEMINI_KEY_POOL:
        return GOOGLE_API_KEY
    _current_key_index = (_current_key_index + 1) % len(_GEMINI_KEY_POOL)
    return _GEMINI_KEY_POOL[_current_key_index]


def call_gemini(messages, temperature=0.9, max_tokens=2500, model=None):
    global _last_gemini_call

    if not _GEMINI_KEY_POOL and not GOOGLE_API_KEY:
        print("  [錯誤] 無任何 GOOGLE_API_KEY 設置")
        return None

    now = time.time()
    elapsed = now - _last_gemini_call
    if elapsed < 8:
        time.sleep(8 - elapsed)
    _last_gemini_call = time.time()

    if model is None:
        model = GEMINI_MODEL

    system_prompt = ""
    contents = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            system_prompt = content
        elif role == "user":
            contents.append({"role": "user", "parts": [{"text": content}]})
        elif role == "assistant":
            contents.append({"role": "model", "parts": [{"text": content}]})

    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    if system_prompt:
        payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

    active_key = _get_active_key()
    url = f"{GOOGLE_GEMINI_BASE_URL}/{model}:generateContent?key={active_key}"
    try:
        response = requests.post(url, json=payload, timeout=180)
    except Exception as e:
        print(f"  [錯誤] {model}: {e}")
        if model != GEMINI_FALLBACK_MODEL:
            print(f"  [重試] 改用 {GEMINI_FALLBACK_MODEL}")
            time.sleep(2)
            return call_gemini(messages, temperature, max_tokens, GEMINI_FALLBACK_MODEL)
        return None

    if response.status_code == 429:
        print(f"  [錯誤] {model} key#{_current_key_index + 1}: 429 Too Many Requests")
        keys_tried = 1
        while keys_tried < len(_GEMINI_KEY_POOL):
            next_key = _rotate_key()
            url = f"{GOOGLE_GEMINI_BASE_URL}/{model}:generateContent?key={next_key}"
            time.sleep(3)
            _last_gemini_call = time.time()
            try:
                response = requests.post(url, json=payload, timeout=180)
                if response.status_code != 429:
                    break
                print(f"  [錯誤] {model} key#{_current_key_index + 1}: 仍 429")
            except Exception as e:
                print(f"  [錯誤] key輪替請求失敗: {e}")
            keys_tried += 1

        if response.status_code == 429:
            wait_sec = random.randint(20, 30)
            print(f"  [等待] 全部 key 都 429,等 {wait_sec} 秒...")
            time.sleep(wait_sec)
            _last_gemini_call = time.time()
            active_key = _get_active_key()
            url = f"{GOOGLE_GEMINI_BASE_URL}/{model}:generateContent?key={active_key}"
            try:
                response = requests.post(url, json=payload, timeout=180)
            except Exception as e:
                print(f"  [錯誤] 最終重試失敗: {e}")
                return None
            if response.status_code == 429:
                print(f"  [失敗] {model} 所有 key 均 429")
                if model != GEMINI_FALLBACK_MODEL:
                    return call_gemini(messages, temperature, max_tokens, GEMINI_FALLBACK_MODEL)
                return None

    if response.status_code == 503:
        print(f"  [錯誤] {model}: 503,等 15 秒重試...")
        time.sleep(15)
        _last_gemini_call = time.time()
        active_key = _get_active_key()
        url = f"{GOOGLE_GEMINI_BASE_URL}/{model}:generateContent?key={active_key}"
        try:
            response = requests.post(url, json=payload, timeout=180)
        except Exception as e:
            print(f"  [錯誤] 503 重試失敗: {e}")
            if model != GEMINI_FALLBACK_MODEL:
                time.sleep(2)
                return call_gemini(messages, temperature, max_tokens, GEMINI_FALLBACK_MODEL)
            return None
        if response.status_code == 503:
            if model != GEMINI_FALLBACK_MODEL:
                return call_gemini(messages, temperature, max_tokens, GEMINI_FALLBACK_MODEL)
            return None

    try:
        response.raise_for_status()
        result = response.json()
        candidates = result.get("candidates", [])
        if not candidates:
            return None
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            return None
        return parts[0].get("text", "").strip()
    except Exception as e:
        print(f"  [錯誤] {model}: {e}")
        if model != GEMINI_FALLBACK_MODEL:
            time.sleep(2)
            return call_gemini(messages, temperature, max_tokens, GEMINI_FALLBACK_MODEL)
        return None


# ============================================================
# RSS 抓取
# ============================================================
def fetch_latest_news(rss_urls, count=3):
    """RSS抓取,過濾敏感詞"""
    BLOCKED_KEYWORDS = [
        "中國", "China", "大陸", "中共", "內地",
    ]
    all_entries = []
    for url in rss_urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:count * 2]:
                title = entry.get("title", "(無標題)")
                summary = entry.get("summary", "") or entry.get("description", "")
                summary = summary.replace("<p>", "").replace("</p>", "\n")
                summary = summary.replace("<br>", "\n").replace("<br/>", "\n")
                combined = (title + summary).lower()
                if any(kw.lower() in combined for kw in BLOCKED_KEYWORDS):
                    continue
                all_entries.append({
                    "title": title,
                    "link": entry.get("link", ""),
                    "summary": summary[:1500],
                    "published": entry.get("published", ""),
                })
                if len(all_entries) >= count:
                    break
        except Exception as e:
            print(f"  [警告] RSS 抓取失敗 {url}: {e}")
    return all_entries[:count]


# ============================================================
# A 類:監控型文章(RSS新聞素材 + 三塊拆解)
# ============================================================
def generate_monitoring_article(persona_name, persona):
    news_list = fetch_latest_news(persona["rss_feeds"], count=3)
    if not news_list:
        return None
    news = random.choice(news_list)

    system_prompt = f"""你是 {persona_name},論壇版主,專門關注「{persona['domain']}」這個版面。

【你的個性】
{persona['personality']}

【你的寫作焦點】
{persona['writing_focus']}

{WRITING_RULES}

【本篇任務:三塊拆解結構】
針對下面這則新聞,寫一篇 1200-1500 字的監控型文章,嚴格分成三塊。

▍輸出格式
第一行:一個改寫的中文標題(不是直譯英文標題)
- 要短、要狠、要勾人
- 不要農場標題、不要冒號分段、不准加標點符號標籤
- 不超過 30 個字
第二行:空一行
第三行起:正文三塊

▍第一塊:事實切片(400-500 字)
只寫客觀事實。誰、做了什麼、什麼時候、影響什麼。
不准帶情緒、不准帶觀點、不准用形容詞渲染。
像新聞稿一樣冷靜。
第一句直接寫事實本身,不用「最近」「近日」這種開場白。

▍第二塊:人味解讀(400-500 字)
用你的個性去吐槽 / 質疑 / 嘲諷 / 解構這件事。
必須有口氣、有立場、會挖苦。
用個人經驗、生活比喻來咀嚼這件事。
想到哪寫到哪,但要狠、要精準。

▍第三塊:未來追問(300-400 字)
拋一個尖銳的問題給讀者,**不給答案**。
用反問句、假設句。
結尾停在問題那。

【三塊之間用空行隔開,不要寫小標題,文氣要自然流動】"""

    user_prompt = f"""【新聞素材】

標題:{news['title']}

內容:
{news['summary']}

來源連結:{news['link']}

開始寫吧。第一行先給中文標題,空一行,再寫三塊。"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    content = call_gemini(messages, temperature=0.9, max_tokens=4500)
    if not content:
        return None

    text = content.strip()
    lines = text.split("\n", 1)
    title = lines[0].strip().lstrip("#").strip().strip("「」\"'《》【】")
    body = lines[1].strip() if len(lines) > 1 else text
    if not title or len(title) > 60:
        title = news["title"]
        body = text

    return {
        "type": "monitor",
        "persona": persona_name,
        "title": title,
        "content": body,
        "source_link": None,  # 黑塔本來就不附出處,沿用
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


# ============================================================
# B 類:原創型文章(種子池 → AI 衍生 → 寫文章)
# ============================================================
def generate_original_article(persona_name, persona, used_topics=None):
    if used_topics is None:
        used_topics = set()

    all_seeds = CURATED_TOPICS + ORIGINAL_TOPICS + SEED_TOPICS + PERSONA_EXTRA_TOPICS.get(persona_name, [])
    available_seeds = [t for t in all_seeds if t not in used_topics]

    if not available_seeds:
        seed = random.choice(all_seeds)
        seed_source = "種子(重複)"
    else:
        seed = random.choice(available_seeds)
        seed_source = "種子"

    derive_prompt = f"""你是 {persona_name},論壇版主,負責「{persona['domain']}」版面,個性:
{persona['personality']}

【你的寫作焦點】
{persona['writing_focus']}

【任務】
我給你一個種子題目當靈感。請基於這個種子的精神,衍生一個新題目——
- 同主題、不同角度(不要直接抄種子)
- 用你自己的人格切入
- 一句話、要短、要勾人
- 符合你的版面焦點

【絕對禁忌】
- 不准攻擊任何人事物(嘲諷可以,攻擊不行)
- 不准出現「中國」、「中國人」、「大陸」、「內地」、「中共」、「國內」這些字眼
- 不准提政治制度、審查、人權議題
- 沉重題材用制度性還原腔調,不用煽情筆法

【種子題目】
{seed}

【輸出】
直接輸出一個新題目,一行內結束。不要解釋、不要前綴、不要引號、不要編號。"""

    derived_raw = call_gemini(
        [{"role": "user", "content": derive_prompt}],
        temperature=1.0,
        max_tokens=200,
    )

    if derived_raw:
        topic = derived_raw.strip().split("\n")[0].strip()
        topic = topic.lstrip("0123456789.、:- ").strip()
        topic = topic.strip('"').strip("「").strip("」").strip("『").strip("』").strip()
        if not topic or len(topic) > 80:
            topic = seed
    else:
        topic = seed

    system_prompt = f"""你是 {persona_name},論壇版主,負責「{persona['domain']}」版面。

【你的個性】
{persona['personality']}

【你的寫作焦點】
{persona['writing_focus']}

{WRITING_RULES}

【本篇任務】
寫一篇純觀點文章,1000-1300 字。
- 用你的個性、口氣來寫
- 沒有【事實】部分,整篇都是觀點
- 開頭三選一:真實小故事/反問句/冷面陳述
- 不要結論、不要總結、不要建議
- 不准用「淺談」「論」「關於」這種廢字
- 文章是流動的整體,不要分段加小標題

【輸出格式】
第一行給一個標題(不要加 # 不要加標號),然後空一行,然後內文。
標題要短、要狠、要勾人。"""

    user_prompt = f"""【主題】
{topic}

開始寫吧。"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    content = call_gemini(messages, temperature=1.0, max_tokens=4000)
    if not content:
        return None

    text = content.strip()
    lines = text.split("\n", 1)
    title = lines[0].strip().lstrip("#").strip()
    body = lines[1].strip() if len(lines) > 1 else text
    if not title or len(title) > 60:
        title = topic
        body = text

    print(f"        ({seed_source}: {seed[:25]} → 衍生: {topic[:30]})")

    return {
        "type": "original",
        "persona": persona_name,
        "title": title,
        "content": body,
        "source_link": None,
        "topic_used": seed,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


# ============================================================
# D 類:技術討論型(從Reddit/HN 真實討論抓素材)
# ============================================================
def generate_discussion_article(persona_name, persona, source_post, source_comments):
    comments_lines = []
    for i, c in enumerate(source_comments[:5], 1):
        body_short = c["body"][:300].replace("\n", " ")
        comments_lines.append(f"[{i}] [+{c.get('score', 0)}] {body_short}")
    comments_text = "\n".join(comments_lines) if comments_lines else "(無熱門回覆)"

    system_prompt = f"""你是 {persona_name},BLACK LENS 論壇版主,負責「{persona['domain']}」版面。

【個性】
{persona['personality']}

【寫作焦點】
{persona['writing_focus']}

{WRITING_RULES}

【本篇任務:以真實討論為素材,寫BLACK LENS風格的觀察文章】

▍輸出格式
第一行:一個中文標題(不農場、不直譯)
- 短、狠、勾人;陳述句或疑問句
- 不超過 30 個字
第二行:空一行
第三行起:800–1000 字正文

▍正文結構(不要寫小標題)
1. 現象切入(150–200 字)
   開頭三選一:真實小故事/反問句/冷面陳述
   直接從討論中提取的具體場景或問題說起。

2. 深入剖析(300–400 字)
   有具體的細節、品種、年齡、品牌、案例、場景。
   你的版面焦點是「{persona['writing_focus']}」,從這個角度切入。
   不空談、不抽象。

3. 橫向觀察(200–250 字)
   主動引入跟議題相關的對比(例如其他國家的做法、其他品種的差異、不同年代的飼養觀念演變)。
   讀者看到名字,但你不評論。

4. 留問題(100–150 字)
   拋一個未解決的問題給讀者,不下結論。

【絕對禁止】
- 不寫小標題
- 不用「綜上所述」「總的來說」「值得注意的是」「不可否認」
- 不農場標題"""

    user_prompt = f"""【真實討論素材】

來源:{source_post.get('source', 'reddit/hn').upper()}
原帖標題:{source_post['title']}
原帖內文(節選):
{(source_post.get('selftext') or '')[:600]}

熱門回覆(前 {len(source_comments)} 條):
{comments_text}

【任務】
以上是真實使用者的聲音。你不是要轉述這篇討論,
你是看到這個討論,用 BLACK LENS 版主的角度,寫一篇 800–1000 字的觀察文章。

開始寫吧。第一行給中文標題,空一行,再寫正文。"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    content = call_gemini(messages, temperature=0.9, max_tokens=4500)
    if not content:
        return None

    text = content.strip()
    lines = text.split("\n", 1)
    title = lines[0].strip().lstrip("#").strip().strip("「」\"'《》【】")
    body = lines[1].strip() if len(lines) > 1 else text
    if not title or len(title) > 60:
        title = source_post["title"][:50]
        body = text

    return {
        "type": "discussion",
        "persona": persona_name,
        "title": title,
        "content": body,
        "source_link": None,
        "source_title": source_post["title"],
        "source_platform": source_post.get("source", "").upper(),
        "raw_comments": source_comments,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


# ============================================================
# 評論生成
# ============================================================
COMMENT_PERSONALITIES = [
    "兇狠派:不耐煩、嗆聲、看到廢話就翻臉",
    "犬儒派:冷笑話、嘲諷、看破紅塵",
    "認同派:但用自己的養寵經驗延伸,不是空洞附和",
    "抬槓派:找版主話裡的漏洞,反問或挑戰",
    "廢話派:講一堆有的沒的,像真人在隨口聊",
    "短促派:一兩句話講完,沒耐心打長字",
    "文藝派:有點酸、用比喻、語氣慢但有後勁",
    "直接派:開頭就罵,講話粗但精準",
]


def generate_one_comment(article, persona, region_style, length_hint, comment_type, max_tokens=400):
    type_instruction_map = {
        "短": "簡短發表看法,不要給具體例子,自然發揮就好",
        "問": "提一個問題(對醫美/保養的真實疑問,例如怎麼判斷某個療程要不要做、哪家診所靠譜、一個月在這個項目花多少錢、某個成分到底有沒有用)",
        "意見": "講自己對醫美/保養的真實想法,個人觀點",
        "長": "可以是抱怨文 / 認真討論 / 分享自己做過某個療程或用某罐保養品的真實經驗,但不要寫成論文",
    }
    type_instruction = type_instruction_map.get(comment_type, "簡短發表看法")

    system_prompt = f"""你要扮演論壇上一個普通網友,針對版主「{persona['domain']}」的文章寫一條評論。

{WRITING_RULES}

【你的網友個性／語氣】
{region_style}

【本條評論類型】
{type_instruction}

【字數限制】
{length_hint}

【真人打字 7 項特徵】
1. 標點只用:?!.,:…… 嚴禁「」『』《》〈〉
2. 英文全部小寫(除非縮寫)
3. 空格隨機,不講究
4. 數字隨意(3 個 / 三個 都可以混用)
5. 斷句隨性
6. 可以用口語縮寫(不ok、超強、有夠、廢到笑)
7. 結構不用整齊
+ 結尾標點可加可不加

【絕對禁止】
- ❌ 不要用網路梗:「笑死」、「推」、「+1」、「樓上正解」、「神回」、「XDDD」
- ❌ 不要回應其他網友(你是獨立發言)
- ❌ 不要開頭:「我同意」、「很有道理」、「個人覺得」、「樓主說得對」、「說得好」
- ❌ 不要用「===」「---」「***」這種分隔符
- ❌ 不要寫多條評論
- ❌ 不要加帳號名、編號、引號

【輸出格式】
直接輸出評論內容本身,不要任何前綴後綴說明文字、不要引號。"""

    user_prompt = f"""【版主原文】
標題:{article['title']}

內容:
{article['content'][:2000]}

請寫一條評論。"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    result = call_gemini(messages, temperature=1.1, max_tokens=max_tokens)
    if not result:
        return None

    text = result.strip()
    lines_raw = text.split('\n')
    clean_lines = [l for l in lines_raw
                   if not re.match(r'^\*?\s*Idea\s*\d+', l.strip(), re.IGNORECASE)
                   and not re.match(r'^\*?\s*Cost:', l.strip(), re.IGNORECASE)
                   and not re.match(r'^\*?\s*Option\s*\d+', l.strip(), re.IGNORECASE)]
    text = '\n'.join(clean_lines).strip()
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)', r'\1', text)

    for sep in ["===", "---", "***", "###"]:
        if sep in text:
            text = text.split(sep)[0].strip()

    text = text.lstrip("0123456789.、:- ").strip()
    for prefix in ["網友", "評論", "回覆", "留言"]:
        if text.startswith(prefix):
            idx = text.find(":")
            if idx == -1:
                idx = text.find(":")
            if 0 <= idx <= 8:
                text = text[idx + 1:].strip()

    text = text.strip('"').strip("「").strip("」").strip("『").strip("』").strip()
    forbidden_chars = ["「", "」", "『", "』", "《", "》", "〈", "〉"]
    for ch in forbidden_chars:
        text = text.replace(ch, "")

    return text if text else None


def generate_comments(article, persona):
    rand = random.random()
    if rand < 0.35:
        num_comments = 0
    elif rand < 0.85:
        num_comments = 1
    else:
        num_comments = 2

    if num_comments == 0:
        return []

    all_accounts = ACCOUNT_POOL + HK_ACCOUNTS + AU_ACCOUNTS
    if len(all_accounts) < num_comments:
        return []
    selected_names = random.sample(all_accounts, num_comments)
    article_ts = article.get("timestamp", "")

    comments = []
    for name in selected_names:
        type_rand = random.random()
        if type_rand < 0.60:
            comment_type = "短"
            length_hint = "10-30 字之間"
            max_tokens = 700
        elif type_rand < 0.80:
            comment_type = "問"
            length_hint = "10-40 字之間,內容是個問題"
            max_tokens = 800
        elif type_rand < 0.95:
            comment_type = "意見"
            length_hint = "30-50 字之間"
            max_tokens = 1000
        else:
            comment_type = "長"
            length_hint = "30-110 字之間"
            max_tokens = 1500

        if name in HK_ACCOUNTS:
            region_style = HK_COMMENT_STYLE_BASE
        elif name in AU_ACCOUNTS:
            region_style = AU_COMMENT_STYLE
        else:
            region_style = random.choice(COMMENT_PERSONALITIES)

        comment_text = generate_one_comment(
            article, persona, region_style, length_hint, comment_type, max_tokens
        )
        if not comment_text:
            continue
        comments.append({
            "author": name,
            "content": comment_text,
            "time": _random_comment_time(article_ts),
        })
    return comments


# ============================================================
# HTML 模板讀取
# ============================================================
def _load_template(filename):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

HTML_TEMPLATE = _load_template("index_template.html")
ARTICLE_PAGE_TEMPLATE = _load_template("article_template.html")


# ============================================================
# SEO 靜態化
# ============================================================
def ensure_article_slug(article):
    if article.get("slug"):
        return article["slug"]
    ts = article.get("timestamp", "")
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M")
        ts_part = dt.strftime("%Y%m%d-%H%M")
    except (ValueError, TypeError):
        ts_part = datetime.now().strftime("%Y%m%d-%H%M")
    seed = (article.get("persona", "") + "|" + article.get("title", ""))
    hash_part = hashlib.md5(seed.encode("utf-8")).hexdigest()[:6]
    slug = f"{ts_part}-{hash_part}"
    article["slug"] = slug
    return slug


def make_article_excerpt(content, max_chars=140):
    text = re.sub(r"<[^>]+>", "", content or "")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    snippet = text[:max_chars]
    for sep in ["。", "!", "?", ",", " "]:
        idx = snippet.rfind(sep)
        if idx > max_chars - 30:
            return snippet[:idx + 1] + "…"
    return snippet + "…"


def make_article_keywords(article):
    persona = article.get("persona", "")
    base_kws = ["醫美", "光電雷射", "微整注射", "玻尿酸", "肉毒", "電波", "音波", "隆鼻", "隆乳", "BLACK LENS", "台灣醫美論壇"]
    persona_kws = {
        "Scholar":     ["術後護理", "醫美恢復期"],
        "渡鴉":        ["醫美成分拆解", "保養品評析"],
        "Trilobite":   ["醫美消費觀察", "審美趨勢"],
        "Sword Smith": ["美容歷史", "美容文化"],
    }
    extra = persona_kws.get(persona, [])
    return ", ".join(extra + base_kws)


def generate_article_page(article):
    slug = ensure_article_slug(article)
    canonical = f"{SITE_BASE_URL}/{ARTICLES_DIR}/{slug}/"

    title = article.get("title", "(無標題)")
    persona = article.get("persona", "")
    content = article.get("content", "")
    timestamp = article.get("timestamp", "")
    prefix = article.get("prefix", "觀察")
    cat = article.get("cat", "")
    cat_name_map = {
        "sos":       "S.O.S",
        "facecon":   "FaceCon",
        "mirage":    "Mirage",
        "fairyface": "FairyFace",
        "media":     "Leek Factory",
        "salon":     "SALON",
    }
    cat_name = cat_name_map.get(cat, "")

    description = make_article_excerpt(content, max_chars=140)
    keywords = make_article_keywords(article)

    try:
        dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M")
        iso_time = dt.strftime("%Y-%m-%dT%H:%M:00+08:00")
    except (ValueError, TypeError):
        iso_time = datetime.now().strftime("%Y-%m-%dT%H:%M:00+08:00")

    paragraphs = [p.strip() for p in (content or "").split("\n") if p.strip()]
    content_html = "\n".join(f"    <p>{html.escape(p)}</p>" for p in paragraphs)

    # BLACK LENS沿用「不附出處」原則
    source_block = ""

    title_json = title.replace('"', '\\"').replace('\\', '\\\\')
    desc_json = description.replace('"', '\\"').replace('\\', '\\\\')

    page = (ARTICLE_PAGE_TEMPLATE
            .replace("{{TITLE}}",         html.escape(title))
            .replace("{{TITLE_JSON}}",    title_json)
            .replace("{{DESCRIPTION}}",   html.escape(description))
            .replace("{{DESCRIPTION_JSON}}", desc_json)
            .replace("{{KEYWORDS}}",      html.escape(keywords))
            .replace("{{CANONICAL}}",     html.escape(canonical))
            .replace("{{CANONICAL_JS}}",  canonical.replace("'", ""))
            .replace("{{SITE_BASE}}",     SITE_BASE_URL)
            .replace("{{ISO_TIME}}",      iso_time)
            .replace("{{PERSONA}}",       html.escape(persona))
            .replace("{{PREFIX}}",        html.escape(prefix))
            .replace("{{CAT_NAME}}",      html.escape(cat_name))
            .replace("{{TIMESTAMP}}",     html.escape(timestamp))
            .replace("{{CONTENT_HTML}}",  content_html)
            .replace("{{SOURCE_BLOCK}}",  source_block))
    return slug, page


def generate_sitemap_xml(articles):
    today_iso = datetime.now().strftime("%Y-%m-%d")
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    lines.append(f"  <url>")
    lines.append(f"    <loc>{SITE_BASE_URL}/</loc>")
    lines.append(f"    <lastmod>{today_iso}</lastmod>")
    lines.append(f"    <changefreq>daily</changefreq>")
    lines.append(f"    <priority>1.0</priority>")
    lines.append(f"  </url>")

    for a in articles:
        if not a:
            continue
        slug = a.get("slug")
        if not slug:
            continue
        try:
            dt = datetime.strptime(a.get("timestamp", ""), "%Y-%m-%d %H:%M")
            lastmod = dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            lastmod = today_iso
        lines.append(f"  <url>")
        lines.append(f"    <loc>{SITE_BASE_URL}/{ARTICLES_DIR}/{slug}/</loc>")
        lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append(f"    <changefreq>monthly</changefreq>")
        lines.append(f"    <priority>0.7</priority>")
        lines.append(f"  </url>")
    lines.append("</urlset>")
    return "\n".join(lines)


def generate_robots_txt():
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        f"Sitemap: {SITE_BASE_URL}/sitemap.xml\n"
    )


def write_static_articles(enriched_articles):
    os.makedirs(ARTICLES_DIR, exist_ok=True)
    written = []
    for a in enriched_articles:
        if not a:
            continue
        try:
            slug, page_html = generate_article_page(a)
            article_dir = os.path.join(ARTICLES_DIR, slug)
            os.makedirs(article_dir, exist_ok=True)
            with open(os.path.join(article_dir, "index.html"), "w", encoding="utf-8") as f:
                f.write(page_html)
            written.append(a)
        except Exception as e:
            print(f"  [靜態化] 失敗 {a.get('title','')[:30]}: {e}")
    return written


# ============================================================
# Fowlplay 投票區:35題、5題位輪播、100票名人堂
# ============================================================
FOWLPLAY_DATA_FILE = "data.json"
VOTE_QUESTIONS_FILE = "vote_questions.json"
CROWN_THRESHOLD = 100
SLOT_COUNT = 5


def _load_vote_questions():
    path = os.path.join(os.path.dirname(__file__), VOTE_QUESTIONS_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("questions", [])
    except Exception as e:
        print(f"[警告] 讀取 vote_questions.json 失敗: {e}")
        return []

VOTE_QUESTIONS = _load_vote_questions()
VOTE_QUESTIONS_BY_ID = {q["id"]: q for q in VOTE_QUESTIONS}


def _make_default_fowlplay():
    """初始化:全部35題各自0票,前5題進active_slots,其餘進queue"""
    random.seed()
    order = [q["id"] for q in VOTE_QUESTIONS]
    random.shuffle(order)
    active = order[:SLOT_COUNT]
    queue = order[SLOT_COUNT:]
    votes = {}
    for q in VOTE_QUESTIONS:
        votes[q["id"]] = {opt: 0 for opt in q["options"]}
    return {
        "votes": votes,
        "active_slots": active,
        "queue": queue,
        "hall_of_fame": [],
        "crown_threshold": CROWN_THRESHOLD,
        "slot_count": SLOT_COUNT,
    }


def load_fowlplay_data():
    if not os.path.exists(FOWLPLAY_DATA_FILE):
        return _make_default_fowlplay()
    try:
        with open(FOWLPLAY_DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        default = _make_default_fowlplay()
        # 補齊缺失欄位
        for k, v in default.items():
            if k not in data:
                data[k] = v
        # 同步votes:確保所有題目都有對應的votes
        for q in VOTE_QUESTIONS:
            if q["id"] not in data["votes"]:
                data["votes"][q["id"]] = {opt: 0 for opt in q["options"]}
        return data
    except Exception as e:
        print(f"  [Fowlplay] data讀取失敗 ({e}),重建")
        return _make_default_fowlplay()


def save_fowlplay_data(data):
    try:
        with open(FOWLPLAY_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  [Fowlplay] data儲存失敗: {e}")


def daily_vote_increment(data):
    """每次 Actions 執行時,active_slots裡的5題各選項隨機累加1-8票"""
    for qid in data.get("active_slots", []):
        if qid not in data["votes"]:
            continue
        for opt in data["votes"][qid]:
            data["votes"][qid][opt] += random.randint(1, 8)
    return data


def check_champions_and_rotate(data):
    """檢查active_slots裡有沒有題目滿100票:有就進名人堂、從queue補位"""
    new_active = []
    for qid in data.get("active_slots", []):
        if qid not in data["votes"]:
            continue
        total = sum(data["votes"][qid].values())
        if total >= CROWN_THRESHOLD:
            # 進名人堂
            q = VOTE_QUESTIONS_BY_ID.get(qid)
            winner_opt = max(data["votes"][qid], key=data["votes"][qid].get)
            champion = {
                "question_id": qid,
                "question": q["question"] if q else qid,
                "category": q.get("category", "") if q else "",
                "winner": winner_opt,
                "votes": dict(data["votes"][qid]),
                "total": total,
                "date": datetime.now().strftime("%Y-%m-%d"),
            }
            if "hall_of_fame" not in data:
                data["hall_of_fame"] = []
            data["hall_of_fame"].append(champion)
            print(f"  [Fowlplay] 🏆 名人堂:《{champion['question'][:25]}》冠軍 → {winner_opt}")

            # 從queue補一題
            if data.get("queue"):
                next_qid = data["queue"].pop(0)
                new_active.append(next_qid)
                print(f"  [Fowlplay] 補位:{next_qid}")
            # queue空了就洗牌重來(讓所有35題重新進場,票數會繼續累積)
            elif data["hall_of_fame"]:
                print(f"  [Fowlplay] queue空,洗牌重啟新一輪")
                all_ids = [q["id"] for q in VOTE_QUESTIONS]
                # 把不在active的id重新洗牌進queue
                pool = [qi for qi in all_ids if qi != qid and qi not in new_active]
                random.shuffle(pool)
                data["queue"] = pool
                if data["queue"]:
                    next_qid = data["queue"].pop(0)
                    new_active.append(next_qid)
        else:
            new_active.append(qid)

    data["active_slots"] = new_active
    return data


# ============================================================
# 生成 index.html
# ============================================================
def generate_html(articles, videos=None, new_articles=None):
    if videos is None:
        videos = []
    if new_articles is None:
        new_articles = []
    today = datetime.now()
    update_time = today.strftime("%Y-%m-%d %H:%M")
    issue_label = f"VOL. {max(today.year - 2025, 1)} · ISSUE {today.month:02d}–{today.year}"

    TYPE_PREFIX = {
        "discussion": "觀察",
        "original": "原創",
        "monitor": "觀察",
        "naspit": "測評",
    }
    if new_articles:
        today_titles = [a["title"] for a in new_articles[:3] if a.get("title")]
        if today_titles:
            page_title = f"BLACK LENS｜今日觀察:{'、'.join(today_titles)}"
        else:
            page_title = "BLACK LENS - 台灣醫美論壇"
    else:
        page_title = "BLACK LENS - 台灣醫美論壇"

    # enriched articles
    enriched = []
    for i, a in enumerate(articles):
        if not a:
            continue
        if a.get("type") == "visual":
            cat = "media"
        elif a.get("type") == "naspit":
            cat = "naspit"
        else:
            cat = PERSONA_TO_CAT.get(a["persona"], "salon")
        slug = ensure_article_slug(a)
        enriched.append({
            "id": i,
            "slug": slug,
            "permalink": f"/{ARTICLES_DIR}/{slug}/",
            "persona": a["persona"],
            "cat": cat,
            "type": a["type"],
            "prefix": TYPE_PREFIX.get(a.get("type", ""), "觀察"),
            "title": a["title"],
            "content": a["content"],
            "source_link": a.get("source_link"),
            "source_title": a.get("source_title"),
            "timestamp": a["timestamp"],
            "comments": a.get("comments", []),
            "naspit_round": a.get("naspit_round"),
            "naspit_dimension": a.get("naspit_dimension"),
            "naspit_topic": a.get("naspit_topic"),
            "naspit_intro": a.get("naspit_intro"),
            "naspit_candidates": a.get("naspit_candidates"),
            "naspit_dimensions_labels": a.get("naspit_dimensions_labels"),
            "naspit_scores": a.get("naspit_scores"),
        })

    articles_json = json.dumps(enriched, ensure_ascii=False).replace("</", "<\\/")
    videos_json = json.dumps(videos, ensure_ascii=False).replace("</", "<\\/")
    categories = [
        {"key": "sos",       "name": "S.O.S",        "en": "3AM顏值急診"},
        {"key": "facecon",   "name": "FaceCon",      "en": "韭菜榨汁機"},
        {"key": "mirage",    "name": "Mirage",       "en": "審美消費觀察"},
        {"key": "fairyface", "name": "FairyFace",    "en": "畫皮五千年"},
        {"key": "fowlplay",  "name": "FoulPlay",     "en": "脂肪分解大師"},
        {"key": "naspit",    "name": "納斯達坑",      "en": "Beauty Court"},
        {"key": "media",     "name": "Leek Factory", "en": "Youtube Shorts"},
        {"key": "salon",     "name": "SALON",        "en": "By Invitation"},
    ]
    categories_json = json.dumps(categories, ensure_ascii=False).replace("</", "<\\/")

    # Fowlplay資料
    fowlplay_data = load_fowlplay_data()
    # 組裝前端需要的active題目完整資料
    fp_active_questions = []
    for qid in fowlplay_data.get("active_slots", []):
        q = VOTE_QUESTIONS_BY_ID.get(qid)
        if not q:
            continue
        fp_active_questions.append({
            "id": qid,
            "category": q.get("category", ""),
            "question": q["question"],
            "options": q["options"],
            "votes": fowlplay_data["votes"].get(qid, {opt: 0 for opt in q["options"]}),
            "threshold": CROWN_THRESHOLD,
        })
    fp_active_json = json.dumps(fp_active_questions, ensure_ascii=False).replace("</", "<\\/")
    fp_hall_json = json.dumps(fowlplay_data.get("hall_of_fame", []), ensure_ascii=False).replace("</", "<\\/")

    # 納斯達坑名人堂(跑完一輪的記錄)
    naspit_state = load_naspit_state()
    naspit_hall_json = json.dumps(naspit_state.get("hall_of_fame", []), ensure_ascii=False).replace("</", "<\\/")

    # 跑馬燈
    fowlplay_ticker = build_fowlplay_ticker(count=40)
    fowlplay_ticker_json = json.dumps(fowlplay_ticker, ensure_ascii=False).replace("</", "<\\/")

    return (HTML_TEMPLATE
            .replace("{{UPDATE_TIME}}",         html.escape(update_time))
            .replace("{{ISSUE_LABEL}}",         html.escape(issue_label))
            .replace("{{PAGE_TITLE}}",          html.escape(page_title))
            .replace("{{ARTICLES_JSON}}",       articles_json)
            .replace("{{VIDEOS_JSON}}",         videos_json)
            .replace("{{CATEGORIES_JSON}}",     categories_json)
            .replace("{{FP_ACTIVE_JSON}}",      fp_active_json)
            .replace("{{FP_HALL_JSON}}",        fp_hall_json)
            .replace("{{NASPIT_HALL_JSON}}",    naspit_hall_json)
            .replace("{{FOWLPLAY_TICKER_JSON}}", fowlplay_ticker_json))


# ============================================================
# 歷史檔讀寫
# ============================================================
ARTICLES_HISTORY_FILE = "articles_history.json"
MAX_HISTORY_ARTICLES = 5000


def load_articles_history():
    if not os.path.exists(ARTICLES_HISTORY_FILE):
        print(f"  [歷史] {ARTICLES_HISTORY_FILE} 不存在,從零開始")
        return []
    try:
        with open(ARTICLES_HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                print(f"  [歷史] 已載入 {len(data)} 篇舊文章")
                return data
            return []
    except Exception as e:
        print(f"  [歷史] 讀取失敗:{e}")
        return []


def save_articles_history(articles):
    if len(articles) > MAX_HISTORY_ARTICLES:
        articles = articles[-MAX_HISTORY_ARTICLES:]
    try:
        with open(ARTICLES_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
        print(f"  [歷史] 已儲存 {len(articles)} 篇")
    except Exception as e:
        print(f"  [歷史] 儲存失敗:{e}")


# ============================================================
# 主程式
# ============================================================
def main():
    start_time = datetime.now()
    print(f"========================================")
    print(f"  BLACK LENS 開始運行")
    print(f"  時間:{start_time}")
    print(f"  模型:{GEMINI_MODEL}(備援:{GEMINI_FALLBACK_MODEL})")
    print(f"========================================")

    if not GOOGLE_API_KEY and not _GEMINI_KEY_POOL:
        print("⚠️  錯誤:GOOGLE_API_KEY 未設置,程式無法運行")
        return

    print(f"API Key 數量:{len(_GEMINI_KEY_POOL)} 個")
    print(f"游泳池(帳號池):{len(ACCOUNT_POOL) + len(HK_ACCOUNTS) + len(AU_ACCOUNTS)} 個帳號")
    print(f"  └─ 台灣 {len(ACCOUNT_POOL)} / 香港 {len(HK_ACCOUNTS)} / 澳洲二代 {len(AU_ACCOUNTS)}")
    print(f"投票題庫:{len(VOTE_QUESTIONS)} 題")
    print(f"雷達圖題庫:{len(RADAR_TOPICS)} 場")
    print()

    # 讀歷史
    print("──────── 讀取歷史 ────────")
    history_articles = load_articles_history()
    print()

    new_articles = []
    used_topics = set()
    used_source_ids = set()

    # 四版主各產 1 篇討論 + 1 篇原創
    for persona_name, persona in PERSONAS.items():
        print(f"────────  {persona_name}({persona['domain']})  ────────")

        # D 類:討論型(Reddit/HN 素材)
        print(f"  [1/2] 討論型文章...")
        material = gather_persona_material(persona_name, persona)
        material = [p for p in material if p["id"] not in used_source_ids]

        article_d = None
        if material:
            top_post = material[0]
            used_source_ids.add(top_post["id"])
            source_label = top_post.get("source", "").upper()
            print(f"        素材:{top_post['title'][:50]}({source_label} +{top_post['score']})")
            if top_post.get("source") == "hn":
                comments_raw = fetch_hn_comments(top_post["id"], limit=5)
            elif top_post.get("source") == "reddit":
                comments_raw = fetch_reddit_comments(top_post["id"], top_post.get("subreddit",""), limit=5)
            else:
                comments_raw = []
            print(f"        抓到 {len(comments_raw)} 條回覆")
            article_d = generate_discussion_article(persona_name, persona, top_post, comments_raw)

        if article_d:
            print(f"        ✓ {article_d['title'][:40]}")
            article_d["comments"] = generate_comments(article_d, persona)
            print(f"        ✓ {len(article_d['comments'])} 條評論")
            new_articles.append(article_d)
        else:
            print(f"        ✗ 無素材,回退到原創")
            article_fallback = generate_original_article(persona_name, persona, used_topics)
            if article_fallback:
                used_topics.add(article_fallback.get("topic_used", ""))
                print(f"        ✓(fallback){article_fallback['title'][:40]}")
                article_fallback["comments"] = generate_comments(article_fallback, persona)
                new_articles.append(article_fallback)

        # B 類:原創型
        print(f"  [2/2] 原創型文章...")
        article_b = generate_original_article(persona_name, persona, used_topics)
        if article_b:
            used_topics.add(article_b.get("topic_used", ""))
            print(f"        ✓ {article_b['title'][:40]}")
            article_b["comments"] = generate_comments(article_b, persona)
            print(f"        ✓ {len(article_b['comments'])} 條評論")
            new_articles.append(article_b)
        print()
        time.sleep(60)

    # 納斯達坑:每週一觸發一場(雷達圖)
    today_weekday = datetime.now().weekday()  # 0=週一
    if today_weekday == 0:
        print(f"────────  納斯達坑(週一一場)  ────────")
        naspit_state = load_naspit_state()
        naspit_article, naspit_state = generate_naspit_article(naspit_state)
        if naspit_article:
            naspit_article["comments"] = generate_comments(
                naspit_article, PERSONAS[naspit_article["persona"]]
            )
            new_articles.append(naspit_article)
            save_naspit_state(naspit_state)
            print(f"        ✓ 第{naspit_state['round']}場:{naspit_article['title'][:40]}")
        else:
            print(f"        ✗ 生成失敗")
        print()

    # YouTube 抓取
    print(f"────────  Leek Factory(YouTube)  ────────")
    leek_videos = fetch_youtube_videos(max_results=50)
    print()

    # 合併歷史 + 新文章
    print("──────── 合併歷史與新文章 ────────")
    print(f"  本次新生成:{len(new_articles)} 篇")
    print(f"  歷史累積:{len(history_articles)} 篇")
    all_articles = new_articles + history_articles
    print(f"  合計:{len(all_articles)} 篇")
    save_articles_history(all_articles)
    print()

    # Fowlplay 票數每日累加 + 名人堂檢查
    fowlplay_data = load_fowlplay_data()
    fowlplay_data = daily_vote_increment(fowlplay_data)
    fowlplay_data = check_champions_and_rotate(fowlplay_data)
    save_fowlplay_data(fowlplay_data)
    print(f"  [Fowlplay] 票數已更新,active_slots:{fowlplay_data['active_slots']}")

    # 生成 index.html
    print(f"  生成 index.html...")
    html_content = generate_html(all_articles, videos=leek_videos, new_articles=new_articles)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"  ✓ index.html 完成({len(html_content):,} 字元)")

    # SEO 靜態化
    print()
    print("──────── SEO 靜態化 ────────")
    seo_articles = []
    for a in all_articles:
        if not a:
            continue
        a_copy = dict(a)
        if a_copy.get("type") == "naspit":
            a_copy["cat"] = "naspit"
        else:
            a_copy["cat"] = PERSONA_TO_CAT.get(a_copy.get("persona", ""), "salon")
        a_copy["prefix"] = {
            "discussion": "觀察",
            "original": "原創",
            "monitor": "觀察",
            "naspit": "測評",
        }.get(a_copy.get("type", ""), "觀察")
        ensure_article_slug(a_copy)
        for orig in all_articles:
            if orig is a:
                orig["slug"] = a_copy["slug"]
        seo_articles.append(a_copy)

    print(f"  [靜態化] 寫入 {len(seo_articles)} 篇...")
    written = write_static_articles(seo_articles)
    print(f"  [靜態化] ✓ 成功 {len(written)} 篇")

    print(f"  [sitemap] 生成中...")
    sitemap_xml = generate_sitemap_xml(seo_articles)
    with open("sitemap.xml", "w", encoding="utf-8") as f:
        f.write(sitemap_xml)
    print(f"  [sitemap] ✓ {len(written) + 1} 個 URL")

    print(f"  [robots] 生成中...")
    with open("robots.txt", "w", encoding="utf-8") as f:
        f.write(generate_robots_txt())
    print(f"  [robots] ✓")

    save_articles_history(all_articles)

    end_time = datetime.now()
    duration = end_time - start_time
    print(f"  總耗時:{duration}")
    print(f"========================================")


if __name__ == "__main__":
    main()
