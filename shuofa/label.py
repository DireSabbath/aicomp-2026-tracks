"""圈子判断的阈值。写死在这里，看过留出结果之后不回头改。"""

HOME_MIN = 0.25
MULTI_MIN = 0.10
OTHER_MAX = MULTI_MIN

ONLY_HERE = "只有这个圈子"
EVERYWHERE = "哪里都在说"
UNSURE = "看不准"

COLLECTION_NAMES = {
    "luoxiang": "罗翔说刑法",
    "yuanshen-preview": "原神前瞻",
    "new-sanguo": "吐槽新三国",
    "xiaoyuehan": "小约翰可汗",
    "heishenhua": "黑神话官方",
}


def collection_name(collection_id: str) -> str:
    return COLLECTION_NAMES.get(collection_id, collection_id)


def judge(rates: dict[str, float]) -> dict:
    """rates 是每个圈子里「多少比例的视频出现过这句」。"""
    if not rates:
        return {"label": UNSURE, "home": None}
    widespread = [cid for cid, rate in rates.items() if rate >= MULTI_MIN]
    if len(widespread) >= 2:
        return {"label": EVERYWHERE, "home": None}
    home = max(rates, key=lambda cid: rates[cid])
    others_quiet = all(rate <= OTHER_MAX for cid, rate in rates.items() if cid != home)
    if rates[home] >= HOME_MIN and others_quiet:
        return {"label": ONLY_HERE, "home": home}
    return {"label": UNSURE, "home": None}
