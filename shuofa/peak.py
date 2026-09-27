BIN_MS = 5000
MIN_TIMED = 4
MIN_SHARE = 0.30


def locate(progress_list: list[int]) -> dict | None:
    """最密的 5 秒。满三成才算卡在这一段。空进度不参与。"""
    timed = sorted(p for p in progress_list if isinstance(p, int) and p >= 0)
    if len(timed) < MIN_TIMED:
        return None
    best_count = 1
    best_start = timed[0]
    right = 0
    for left, start in enumerate(timed):
        if right < left:
            right = left
        while right < len(timed) and timed[right] - start < BIN_MS:
            right += 1
        count = right - left
        if count > best_count:
            best_count = count
            best_start = start
    share = best_count / len(timed)
    return {
        "start_ms": best_start,
        "end_ms": best_start + BIN_MS,
        "share": round(share, 3),
        "timed": len(timed),
        "held": share >= MIN_SHARE,
    }
