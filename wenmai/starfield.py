"""六维星图。每颗星是一支有弹幕的视频，方向是六维构成，大小是弹幕量。"""

from __future__ import annotations

import json
import math
from pathlib import Path

DIM_COLOR = {
    "作品评价": (156, 43, 30),
    "知识认知": (36, 87, 166),
    "情感认同": (161, 92, 7),
    "审美鉴赏": (47, 111, 98),
    "传播思辨": (92, 61, 122),
    "传承意向": (138, 75, 47),
}

# 六个方向张开，纯某一维的片子会落到对应的极点。
AXES = (
    ("作品评价", (1.0, 0.18, 0.05)),
    ("知识认知", (-0.42, 0.92, 0.08)),
    ("情感认同", (-0.55, -0.72, 0.28)),
    ("审美鉴赏", (0.42, 0.12, 0.96)),
    ("传播思辨", (0.12, -0.28, -0.95)),
    ("传承意向", (0.72, -0.58, -0.28)),
)

VIEWS = (
    ("three-quarter", 0.55, 0.42, "斜看：知识认知在上，审美和传播思辨拉开纵深"),
    ("side", 1.7, 0.28, "侧看：作品评价和传承意向分到两侧"),
    ("above", 0.4, 1.05, "俯看：六极张开，中间是没有落入六维的暗星"),
)


def place(mix: dict[str, float]) -> tuple[float, float, float]:
    x = y = z = 0.0
    for name, axis in AXES:
        weight = float(mix.get(name) or 0)
        x += weight * axis[0]
        y += weight * axis[1]
        z += weight * axis[2]
    return x, y, z


def _mix(star: dict) -> dict[str, float]:
    """开方后再归一。稀有的维度仍能把星星从知识认知极拉开。"""
    counts = star.get("by_dimension") or {}
    weights = {name: math.sqrt(int(counts.get(name) or 0)) for name, _ in AXES}
    total = sum(weights.values())
    if total <= 0:
        return {}
    return {name: weight / total for name, weight in weights.items()}


def coordinates(star: dict) -> tuple[float, float, float, bool]:
    mix = _mix(star)
    salt = sum(ord(char) for char in (star.get("bvid") or ""))
    jx = ((salt % 11) - 5) / 42
    jy = (((salt // 11) % 11) - 5) / 42
    jz = (((salt // 121) % 11) - 5) / 42
    if not mix:
        return jx / 4, jy / 4, jz / 4, True
    x, y, z = place(mix)
    return x + jx, y + jy, z + jz, False


def project(x: float, y: float, z: float, yaw: float, pitch: float) -> tuple[float, float, float]:
    cy, sy = math.cos(yaw), math.sin(yaw)
    x1 = x * cy + z * sy
    z1 = -x * sy + z * cy
    cp, sp = math.cos(pitch), math.sin(pitch)
    y2 = y * cp - z1 * sp
    z2 = y * sp + z1 * cp
    return x1, y2, z2


def _layout(stars: list[dict], yaw: float, pitch: float) -> list[dict]:
    points = []
    for star in stars:
        x, y, z, dust = coordinates(star)
        px, py, depth = project(x, y, z, yaw, pitch)
        points.append(
            {
                "x": px,
                "y": py,
                "depth": depth,
                "danmaku": int(star.get("danmaku") or 0),
                "coded": int(star.get("coded") or 0),
                "dominant": star.get("dominant") or "",
                "title": star.get("title") or "",
                "group_title": star.get("group_title") or "",
                "dust": dust,
            }
        )
    points.sort(key=lambda item: item["depth"])
    return points


def _font(size: int):
    from PIL import ImageFont

    for path in (
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def render_view(stars: list[dict], yaw: float, pitch: float, caption: str, path: Path) -> None:
    from PIL import Image, ImageChops, ImageDraw

    width, height = 1600, 1000
    base = Image.new("RGB", (width, height), (12, 10, 8))
    glow = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(glow)
    ink = ImageDraw.Draw(base)
    font = _font(32)
    small = _font(20)
    # 暗角，让星星从背景里浮出来。
    for step in range(8, 0, -1):
        shade = 8 + step
        margin = step * 18
        ink.ellipse((margin, margin // 2, width - margin, height - margin // 2), outline=(shade, shade - 2, shade - 4))
    ink.text((48, 36), "文脉 · 六维星图", font=font, fill=(246, 239, 228))
    ink.text((48, 82), caption, font=small, fill=(183, 168, 148))

    points = _layout(stars, yaw, pitch)
    peak = max((item["danmaku"] for item in points), default=1) or 1

    scale = 340

    def to_screen(x: float, y: float) -> tuple[float, float]:
        return width * 0.50 + x * scale, height * 0.52 - y * scale

    ox, oy = to_screen(0, 0)
    for name, axis in AXES:
        px, py, _depth = project(axis[0], axis[1], axis[2], yaw, pitch)
        sx, sy = to_screen(px, py)
        color = DIM_COLOR[name]
        ink.line((ox, oy, sx, sy), fill=tuple(max(28, channel // 3) for channel in color), width=1)

    for item in points:
        sx, sy = to_screen(item["x"], item["y"])
        if item["dust"]:
            radius = 1.6
            color = (150, 140, 126)
            halo = 3
        else:
            radius = 1.8 + 4.2 * math.log1p(item["danmaku"]) / math.log1p(peak)
            color = DIM_COLOR.get(item["dominant"], (236, 228, 214))
            halo = radius * 2.4
        draw.ellipse((sx - halo, sy - halo, sx + halo, sy + halo), fill=tuple(channel // 7 for channel in color))
        draw.ellipse((sx - radius, sy - radius, sx + radius, sy + radius), fill=color)
        if not item["dust"]:
            core = max(0.8, radius * 0.35)
            draw.ellipse((sx - core, sy - core, sx + core, sy + core), fill=(255, 244, 230))

    image = ImageChops.add(base, glow)
    ink = ImageDraw.Draw(image)
    star_xy = [to_screen(item["x"], item["y"]) for item in points]
    if star_xy:
        cx = sum(x for x, _y in star_xy) / len(star_xy)
        cy = sum(y for _x, y in star_xy) / len(star_xy)
        cloud = max(math.hypot(x - cx, y - cy) for x, y in star_xy)
    else:
        cx, cy, cloud = width / 2, height / 2, 0
    for name, axis in AXES:
        # 轴的方向不变。字若落进星云，就沿同一方向推到云外，避免被知识认知盖住。
        tip_x, tip_y, _depth = project(axis[0], axis[1], axis[2], yaw, pitch)
        tx, ty = to_screen(tip_x, tip_y)
        px, py, _depth = project(axis[0] * 1.42, axis[1] * 1.42, axis[2] * 1.42, yaw, pitch)
        sx, sy = to_screen(px, py)
        dx, dy = sx - cx, sy - cy
        dist = math.hypot(dx, dy) or 1.0
        outside = cloud + 56
        if dist < outside:
            sx = cx + dx / dist * outside
            sy = cy + dy / dist * outside
        text_box = ink.textbbox((0, 0), name, font=small)
        text_w = text_box[2] - text_box[0]
        text_h = text_box[3] - text_box[1]
        sx = min(width - text_w - 28, max(28, sx))
        sy = min(height - text_h - 20, max(124, sy))
        ink.line((tx, ty, sx, sy + text_h / 2), fill=tuple(max(48, channel // 2) for channel in DIM_COLOR[name]), width=1)
        bbox = ink.textbbox((sx, sy), name, font=small)
        ink.rectangle((bbox[0] - 6, bbox[1] - 3, bbox[2] + 6, bbox[3] + 3), fill=(12, 10, 8))
        ink.text((sx, sy), name, font=small, fill=DIM_COLOR[name])
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def write_views(summary: dict, out_dir: Path) -> list[Path]:
    stars = list(summary.get("video_stars") or [])
    out_dir = Path(out_dir)
    written = []
    for name, yaw, pitch, caption in VIEWS:
        path = out_dir / f"{name}.png"
        render_view(stars, yaw, pitch, caption, path)
        written.append(path)
    return written


def section_html(summary: dict) -> str:
    stars = summary.get("video_stars") or []
    if not stars:
        return ""
    payload = []
    for star in stars:
        x, y, z, dust = coordinates(star)
        payload.append(
            {
                "x": round(x, 4),
                "y": round(y, 4),
                "z": round(z, 4),
                "danmaku": int(star.get("danmaku") or 0),
                "coded": int(star.get("coded") or 0),
                "dominant": star.get("dominant") or "",
                "title": star.get("title") or "",
                "group": star.get("group_title") or "",
                "dust": dust,
            }
        )
    data = json.dumps({"stars": payload, "colors": {name: "#{:02x}{:02x}{:02x}".format(*rgb) for name, rgb in DIM_COLOR.items()}}, ensure_ascii=False)
    data = data.replace("<", "\\u003c")
    return f"""
<section id="starfield">
<h2>六维星图</h2>
<p class="note">每颗星是一支当前池里有字的视频。方向按这支片子的六维构成：纯知识认知靠近知识认知极，审美和知识掺在一起就落在两极之间。星的大小是弹幕量。中间的暗星有弹幕，但没有落入六维。拖动可以转。</p>
<canvas id="star" width="1100" height="640" class="chart"></canvas>
<p class="note" id="star-caption"></p>
</section>
<script>
const STAR = {data};
(function () {{
  const canvas = document.getElementById("star");
  if (!canvas || !STAR.stars) return;
  const ctx = canvas.getContext("2d");
  const caption = document.getElementById("star-caption");
  let yaw = 0.55, pitch = 0.42, drag = null;
  const axes = [
    ["作品评价", 1, 0.18, 0.05],
    ["知识认知", -0.42, 0.92, 0.08],
    ["情感认同", -0.55, -0.72, 0.28],
    ["审美鉴赏", 0.42, 0.12, 0.96],
    ["传播思辨", 0.12, -0.28, -0.95],
    ["传承意向", 0.72, -0.58, -0.28]
  ];
  function project(x, y, z) {{
    const cy = Math.cos(yaw), sy = Math.sin(yaw);
    const x1 = x * cy + z * sy;
    const z1 = -x * sy + z * cy;
    const cp = Math.cos(pitch), sp = Math.sin(pitch);
    return [x1, y * cp - z1 * sp, y * sp + z1 * cp];
  }}
  function frame() {{
    const width = canvas.width, height = canvas.height;
    ctx.fillStyle = "#070605";
    ctx.fillRect(0, 0, width, height);
    const peak = Math.max.apply(null, STAR.stars.map(function (star) {{ return star.danmaku || 1; }}));
    function screen(x, y) {{
      return [width * 0.52 + x * 340, height * 0.56 - y * 340];
    }}
    ctx.font = "14px sans-serif";
    axes.forEach(function (axis) {{
      const p = project(axis[1] * 0.92, axis[2] * 0.92, axis[3] * 0.92);
      const s = screen(p[0], p[1]);
      const o = screen(0, 0);
      ctx.strokeStyle = STAR.colors[axis[0]] || "#888";
      ctx.globalAlpha = 0.35;
      ctx.beginPath();
      ctx.moveTo(o[0], o[1]);
      ctx.lineTo(s[0], s[1]);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }});
    const drawn = STAR.stars.map(function (star) {{
      const p = project(star.x, star.y, star.z);
      return {{ star: star, p: p }};
    }}).sort(function (a, b) {{ return a.p[2] - b.p[2]; }});
    drawn.forEach(function (item) {{
      const s = screen(item.p[0], item.p[1]);
      const star = item.star;
      const radius = star.dust ? 1.6 : 1.8 + 4.2 * Math.log(1 + (star.danmaku || 1)) / Math.log(1 + peak);
      ctx.fillStyle = star.dust ? "#6e675c" : (STAR.colors[star.dominant] || "#f6efe4");
      ctx.globalAlpha = star.dust ? 0.45 : 0.9;
      ctx.beginPath();
      ctx.arc(s[0], s[1], radius, 0, Math.PI * 2);
      ctx.fill();
    }});
    ctx.globalAlpha = 1;
    ctx.font = "14px sans-serif";
    let cx = 0, cy = 0, cloud = 0;
    drawn.forEach(function (item) {{
      const s = screen(item.p[0], item.p[1]);
      cx += s[0];
      cy += s[1];
    }});
    if (drawn.length) {{
      cx /= drawn.length;
      cy /= drawn.length;
      drawn.forEach(function (item) {{
        const s = screen(item.p[0], item.p[1]);
        cloud = Math.max(cloud, Math.hypot(s[0] - cx, s[1] - cy));
      }});
    }}
    axes.forEach(function (axis) {{
      const tip = project(axis[1], axis[2], axis[3]);
      const tipS = screen(tip[0], tip[1]);
      const p = project(axis[1] * 1.34, axis[2] * 1.34, axis[3] * 1.34);
      const s = screen(p[0], p[1]);
      let x = s[0], y = s[1];
      const dx = x - cx, dy = y - cy;
      const dist = Math.hypot(dx, dy) || 1;
      const outside = cloud + 28;
      if (dist < outside) {{
        x = cx + dx / dist * outside;
        y = cy + dy / dist * outside;
      }}
      const label = axis[0];
      const w = ctx.measureText(label).width;
      x = Math.max(8, Math.min(width - w - 8, x));
      y = Math.max(16, Math.min(height - 8, y));
      ctx.strokeStyle = STAR.colors[axis[0]] || "#888";
      ctx.globalAlpha = 0.45;
      ctx.beginPath();
      ctx.moveTo(tipS[0], tipS[1]);
      ctx.lineTo(x, y);
      ctx.stroke();
      ctx.globalAlpha = 1;
      ctx.fillStyle = "rgba(7,6,5,0.88)";
      ctx.fillRect(x - 4, y - 13, w + 8, 18);
      ctx.fillStyle = STAR.colors[axis[0]] || "#eee";
      ctx.fillText(label, x, y);
    }});
    if (caption) caption.textContent = "有字的视频 " + STAR.stars.length + " 支。拖动画布可以换一个角度看六极。";
  }}
  canvas.addEventListener("pointerdown", function (event) {{
    drag = {{ x: event.clientX, y: event.clientY }};
  }});
  window.addEventListener("pointerup", function () {{ drag = null; }});
  window.addEventListener("pointermove", function (event) {{
    if (!drag) return;
    yaw += (event.clientX - drag.x) * 0.005;
    pitch = Math.max(0.15, Math.min(1.2, pitch + (event.clientY - drag.y) * 0.004));
    drag = {{ x: event.clientX, y: event.clientY }};
    frame();
  }});
  frame();
}})();
</script>
"""
