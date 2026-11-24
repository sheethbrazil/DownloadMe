import colorsys
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from urllib.parse import urlparse

import flet as ft
from yt_dlp import YoutubeDL

from logo_data import LOGO_B64

# تشغيل بدون نافذة أوامر (pythonw): نتأكد إن مخارج النص موجودة
for _n in ("stdout", "stderr"):
    if getattr(sys, _n) is None:
        setattr(sys, _n, open(os.devnull, "w"))

try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG = None

try:
    from yt_dlp.utils import DownloadCancelled
except Exception:  # نسخة قديمة
    DownloadCancelled = Exception

NEON, CYAN, PINK, BG = "#3B82F6", "#2DD4BF", "#F43F5E", "#06080F"
BRAND = ["#3B82F6", "#2DD4BF"]
HERE = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get("FLET_APP_STORAGE_DATA") or HERE
HIST = os.path.join(DATA, "history.json")
ARCHIVE = os.path.join(DATA, "archive.txt")
os.environ["PATH"] = os.path.join(HERE, "bin") + os.pathsep + os.environ.get("PATH", "")

AUDIO = "bestaudio[ext=m4a]/bestaudio"
VIDEO = "b[ext=mp4]/b"

QUALITIES = {
    AUDIO: "🎵 صوت M4A - أعلى جودة (مع الغلاف)",
    VIDEO: "🎬 فيديو MP4 - أعلى جودة متاحة",
}
# يستخدم cookies.txt إذا وُجد بجانب الملف، وإلا يقرأ من المتصفح (اتركه "" لتعطيله)
COOKIES_BROWSER = ""
DIRECT_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".webm", ".mp3", ".m4a", ".pdf")


def hue(h):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, 0.85, 1.0)
    return "#%02X%02X%02X" % (int(r * 255), int(g * 255), int(b * 255))


def op(a, c):
    return ft.Colors.with_opacity(a, c)


def clean(s):
    return re.sub(r"\x1b\[[0-9;]*m", "", str(s)).strip()


def find_cookies():
    cf = os.path.join(DATA, "cookies.txt")
    if os.path.exists(cf):
        return cf
    try:
        import glob
        import shutil
        found = glob.glob(os.path.join(os.path.expanduser("~"), "Downloads", "*cookies*.txt"))
        if found:
            shutil.copy(max(found, key=os.path.getmtime), cf)
            return cf
    except Exception:
        pass
    return None


def base_opts():
    o = {"quiet": True, "noplaylist": True,
         "extractor_args": {"youtube": {"player_client": ["default", "android_vr"]}}}
    if FFMPEG:
        o["ffmpeg_location"] = FFMPEG
    cf = find_cookies()
    if cf:
        o["cookiefile"] = cf
    elif COOKIES_BROWSER:
        o["cookiesfrombrowser"] = (COOKIES_BROWSER,)
    return o


def friendly(ex):
    m = clean(ex)
    if "decrypt" in m or "DPAPI" in m:
        return "ما أقدر أفك تشفير كوكيز المتصفح. حط ملف cookies.txt بجانب main.py"
    if "Sign in" in m or "not a bot" in m:
        return "يوتيوب يطلب تسجيل دخول: حط ملف cookies.txt بجانب main.py"
    if "429" in m:
        return "يوتيوب حاظر الطلبات مؤقتاً (429)، انتظر ساعة تقريباً وجرّب"
    if "cookie" in m.lower():
        return "ما قدرت أقرأ كوكيز المتصفح: سكّره أو استخدم cookies.txt"
    if "Requested format is not available" in m:
        return "هالجودة مو متوفرة لهذا الفيديو: جرّب جودة ثانية"
    if "ffmpeg" in m.lower() or "ffprobe" in m.lower():
        return "ffmpeg غير موجود: ثبّت المكتبة بالأمر pip install imageio-ffmpeg"
    return "صار خطأ: " + m[:150]


def is_batch(link):
    return any(x in link for x in ("youtube.com/@", "/channel/", "/c/", "/user/", "/playlist?", "/browse/"))


def norm_channel(link):
    if "music.youtube.com/channel/" in link:
        link = link.replace("music.youtube.com", "www.youtube.com")
    if "/browse/" in link:
        return link.split("?")[0]
    if "/playlist?" not in link:
        link = link.split("?")[0].rstrip("/")
    if "/playlist?" in link or any(t in link for t in ("/videos", "/shorts", "/streams", "/releases", "/playlists")):
        return link
    return link + "/videos"


def safe_name(s):
    return re.sub(r'[\\/:*?"<>|]', "", s).strip()[:60] or "downloadme"


def save_dir():
    for base in ("/storage/emulated/0/Download", os.path.expanduser("~/Downloads")):
        if os.path.isdir(base):
            d = os.path.join(base, "DownloadMe")
            try:
                os.makedirs(d, exist_ok=True)
                t = os.path.join(d, ".w")
                open(t, "w").close()
                os.remove(t)
                return d
            except Exception:
                pass
    d = os.path.join(DATA, "downloads")
    os.makedirs(d, exist_ok=True)
    return d


def embed_cover(path, info):
    """يكتب الاسم والفنان وصورة الغلاف داخل ملف m4a (بدون ffmpeg)."""
    try:
        from mutagen.mp4 import MP4, MP4Cover
        jpgs = [t for t in (info.get("thumbnails") or []) if str(t.get("url", "")).split("?")[0].endswith(".jpg")]
        jpgs.sort(key=lambda t: (t.get("height") or 0) * (t.get("width") or 0))
        data = None
        for t in reversed(jpgs[-3:]):
            try:
                data = urllib.request.urlopen(t["url"], timeout=15).read()
                break
            except Exception:
                continue
        f = MP4(path)
        if f.tags is None:
            f.add_tags()
        f.tags["\xa9nam"] = [str(info.get("track") or info.get("title") or "")]
        f.tags["\xa9ART"] = [str(info.get("artist") or info.get("uploader") or "")]
        if data:
            f.tags["covr"] = [MP4Cover(data, imageformat=MP4Cover.FORMAT_JPEG)]
        f.save()
    except Exception:
        pass


def fmt_dur(s):
    s = int(s)
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def glass(content, padding=20):
    return ft.Container(
        content=content, padding=padding, border_radius=28,
        bgcolor=op(0.05, "white"), border=ft.border.all(1, op(0.10, "white")),
    )


def chip(icon, text, c):
    return ft.Container(
        ft.Row([ft.Icon(icon, size=15, color=c), ft.Text(text, size=12)], spacing=5, tight=True),
        padding=ft.padding.symmetric(8, 12), border_radius=20,
        bgcolor=op(0.15, c), border=ft.border.all(1, op(0.5, c)),
    )


def stat_card(icon, c, val, label):
    return ft.Container(
        expand=True, padding=14, border_radius=20, bgcolor=op(0.09, c),
        border=ft.border.all(1, op(0.35, c)),
        content=ft.Column(
            [ft.Icon(icon, color=c), val, ft.Text(label, size=11, color="#B9A6D9")],
            horizontal_alignment="center", spacing=2),
    )


def main(page: ft.Page):
    page.title = "DownloadMe"
    try:
        page.window.icon = "icon.ico"
    except Exception:
        pass
    page.rtl = True
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG
    page.padding = 0
    try:
        page.window.min_width = 380
        page.window.width = 1100
        page.window.height = 760
    except Exception:
        pass

    state = {"direct": False, "count": 0}
    try:
        with open(HIST, encoding="utf-8") as f:
            hist = json.load(f)
    except Exception:
        hist = []

    # ---------- الشعار ----------
    badge = ft.Container(
        content=ft.Image(src_base64=LOGO_B64, width=112, height=112, fit=ft.ImageFit.CONTAIN),
        border_radius=28, shadow=ft.BoxShadow(blur_radius=40, color=op(0.35, NEON)),
        animate=ft.Animation(2000, ft.AnimationCurve.EASE_IN_OUT),
        animate_scale=ft.Animation(2000, ft.AnimationCurve.EASE_IN_OUT),
    )
    name = ft.Text(
        spans=[ft.TextSpan("Download", ft.TextStyle(color="white")),
               ft.TextSpan("Me", ft.TextStyle(color=CYAN))],
        size=50, weight=ft.FontWeight.W_800)
    tagline = ft.Text("الصق الرابط.. وخلّه علينا", size=15, color="#B9A6D9")
    wordmark = ft.Text("M E D I A   D O W N L O A D E R", size=11, weight="bold", color=CYAN)
    logo = ft.Column([badge, name, wordmark, tagline], horizontal_alignment="center", spacing=6)
    chips = ft.Row(
        [chip(ft.Icons.PLAY_CIRCLE, "يوتيوب", "#F43F5E"), chip(ft.Icons.MOVIE, "فيديو", "#FBBF24"),
         chip(ft.Icons.IMAGE, "صور", "#34D399"), chip(ft.Icons.MUSIC_NOTE, "صوت", "#A78BFA")],
        alignment="center", wrap=True, spacing=8,
    )

    # ---------- الإدخال ----------
    url = ft.TextField(
        hint_text="الصق الرابط هنا ثم اضغط Enter", prefix_icon=ft.Icons.LINK, border_radius=20,
        filled=True, bgcolor=op(0.07, "white"), border_color=op(0.2, NEON),
        focused_border_color=CYAN, text_size=15, content_padding=18,
    )
    url.suffix = ft.IconButton(
        ft.Icons.CLOSE_ROUNDED, icon_size=18,
        on_click=lambda e: (setattr(url, "value", ""), page.update()))
    analyze_btn = ft.Container(
        height=58, border_radius=20, alignment=ft.alignment.center, ink=True,
        gradient=ft.LinearGradient(colors=BRAND),
        shadow=ft.BoxShadow(blur_radius=24, color=op(0.5, NEON), offset=ft.Offset(0, 6)),
        content=ft.Row([ft.Icon(ft.Icons.BOLT, color="white"),
                        ft.Text("ابدأ", size=18, weight="bold")], alignment="center", tight=True),
        animate_scale=ft.Animation(150, ft.AnimationCurve.EASE_OUT),
    )
    analyze_btn.on_hover = lambda e: (
        setattr(analyze_btn, "scale", 1.03 if e.data == "true" else 1), analyze_btn.update())
    err = ft.Text("", color="#FF5252", size=13, text_align="center")

    # ---------- الإحصائيات والسجل ----------
    s_sess = ft.Text("0", size=24, weight="bold")
    s_hist = ft.Text(str(len(hist)), size=24, weight="bold")
    stats = ft.Row([
        stat_card(ft.Icons.BOLT, "#FBBF24", s_sess, "هذي الجلسة"),
        stat_card(ft.Icons.HISTORY, "#34D399", s_hist, "إجمالي المحفوظ"),
        stat_card(ft.Icons.PUBLIC, "#00E5FF", ft.Text("+1000", size=24, weight="bold"), "موقع مدعوم"),
    ], spacing=10)

    def hist_row(t):
        return ft.Row([ft.Icon(ft.Icons.CHECK_CIRCLE, color=CYAN, size=18),
                       ft.Text(t, size=13, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True)])

    recent = ft.Column([hist_row(t) for t in hist[:6]], spacing=8)
    recent_box = glass(ft.Column([ft.Text("آخر التنزيلات", size=14, color="#B9A6D9"), recent], spacing=10))
    recent_box.visible = bool(hist)

    def add_hist(t):
        hist.insert(0, t)
        del hist[50:]
        try:
            with open(HIST, "w", encoding="utf-8") as f:
                json.dump(hist, f, ensure_ascii=False)
        except Exception:
            pass
        recent.controls.insert(0, hist_row(t))
        del recent.controls[6:]
        s_hist.value = str(len(hist))
        recent_box.visible = True

    # ---------- النتيجة ----------
    thumb = ft.Image(src="", height=210, border_radius=20, fit=ft.ImageFit.COVER, visible=False)
    title = ft.Text("", size=17, weight="bold", max_lines=2)
    meta = ft.Row(wrap=True, spacing=8)
    quality = ft.Dropdown(
        options=[ft.dropdown.Option(k, v) for k, v in QUALITIES.items()],
        value=AUDIO, border_radius=16, filled=True,
        bgcolor=op(0.07, "white"), border_color=op(0.2, CYAN),
    )
    bar = ft.ProgressBar(value=0, color=CYAN, bgcolor=op(0.12, "white"), height=10, border_radius=10)
    status = ft.Text("", color=CYAN, size=13)
    dl_label = ft.Text("تنزيل", size=18, weight="bold", color="white")
    limit = ft.TextField(
        label="كم مقطع تنزّل؟ (اتركه فاضي = الكل)", visible=False, border_radius=16, filled=True,
        bgcolor=op(0.07, "white"), border_color=op(0.2, CYAN), input_filter=ft.NumbersOnlyInputFilter())
    stop_btn = ft.OutlinedButton("إيقاف التنزيل", icon=ft.Icons.STOP_CIRCLE_OUTLINED, visible=False)
    dl_btn = ft.Container(
        height=56, border_radius=20, alignment=ft.alignment.center, ink=True,
        gradient=ft.LinearGradient(colors=BRAND[::-1]),
        shadow=ft.BoxShadow(blur_radius=24, color=op(0.45, CYAN), offset=ft.Offset(0, 6)),
        content=ft.Row([ft.Icon(ft.Icons.DOWNLOAD_ROUNDED, color="white"),
                        dl_label],
                       alignment="center", tight=True),
    )

    def open_folder(_):
        try:
            f = save_dir()
            if sys.platform.startswith("win"):
                os.startfile(f)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", f])
            else:
                subprocess.Popen(["xdg-open", f])
        except Exception:
            pass

    open_btn = ft.OutlinedButton("فتح مجلد التنزيلات", icon=ft.Icons.FOLDER_OPEN,
                                 visible=False, on_click=open_folder)
    result = glass(ft.Column([thumb, title, meta, quality, limit, dl_btn, stop_btn, bar, status, open_btn], spacing=16))
    result.visible = False

    tips = [(ft.Icons.CONTENT_PASTE, "الصق الرابط في الحقل واضغط Enter"),
            (ft.Icons.LIBRARY_MUSIC, "الصق رابط قناة أو قائمة تشغيل لتنزيل كل المقاطع"),
            (ft.Icons.TUNE, "اختر الجودة، أو «صوت» للأغاني"),
            (ft.Icons.FOLDER, "الملفات تنحفظ في مجلد التنزيلات"),
            (ft.Icons.IMAGE, "روابط الصور والملفات المباشرة تنزل بنفس الطريقة")]
    empty = glass(ft.Column(
        [ft.Icon(ft.Icons.CLOUD_DOWNLOAD_OUTLINED, size=70, color=op(0.35, "white")),
         ft.Text("نتيجتك بتظهر هنا", size=16, color=op(0.5, "white")),
         ft.Container(height=8)] +
        [ft.Row([ft.Icon(i, size=18, color=CYAN), ft.Text(t, size=13, color="#B9A6D9")], spacing=10)
         for k, (i, t) in enumerate(tips)],
        horizontal_alignment="center", spacing=10), padding=40)

    def analyze(_):
        link = url.value.strip()
        if not link:
            return
        result.visible, empty.visible, open_btn.visible = False, False, False
        err.value = "جاري التحليل..."
        page.update()

        def work():
            try:
                batch = is_batch(link)
                state["batch"] = batch
                if batch:
                    lk = norm_channel(link)
                    with YoutubeDL({**base_opts(), "noplaylist": False, "extract_flat": "in_playlist"}) as y:
                        info = y.extract_info(lk, download=False)
                    ents = [e for e in (info.get("entries") or []) if e]
                    if not ents:
                        raise Exception("ما لقيت مقاطع في هذا الرابط")
                    state.update(url=lk, n=len(ents), folder=safe_name(info.get("title") or "قناة"))
                    th = (info.get("thumbnail")
                          or next((t.get("url") for t in reversed(info.get("thumbnails") or []) if t.get("url")), None)
                          or next((t.get("url") for t in (ents[0].get("thumbnails") or []) if t.get("url")), None))
                    quality.value = AUDIO
                    dl_label.value = f"تنزيل الكل ({len(ents)})"
                else:
                    with YoutubeDL(base_opts()) as y:
                        info = y.extract_info(link, download=False)
                    th = info.get("thumbnail")
                    dl_label.value = "تنزيل"
                state["direct"] = False
                limit.visible = batch
                title.value = info.get("title", "بدون عنوان")
                thumb.src, thumb.visible = th or "", bool(th)
                quality.visible = True
                m = []
                if batch:
                    m.append(chip(ft.Icons.LIBRARY_MUSIC, f"{len(ents)} مقطع", "#FB923C"))
                if info.get("duration"):
                    m.append(chip(ft.Icons.TIMER, fmt_dur(info["duration"]), "#FBBF24"))
                if info.get("uploader"):
                    m.append(chip(ft.Icons.PERSON, str(info["uploader"])[:24], "#34D399"))
                if info.get("view_count"):
                    m.append(chip(ft.Icons.VISIBILITY, f"{info['view_count']:,}", "#F43F5E"))
                meta.controls = m
            except Exception as ex:
                if os.path.splitext(urlparse(link).path)[1].lower() in DIRECT_EXT:
                    state["direct"] = True
                    title.value = os.path.basename(urlparse(link).path) or "ملف"
                    thumb.src, thumb.visible = link, True
                    quality.visible = False
                    meta.controls = []
                    limit.visible = False
                    state["batch"] = False
                    dl_label.value = "تنزيل"
                else:
                    err.value = friendly(ex)
                    empty.visible = True
                    page.update()
                    return
            err.value = ""
            bar.value = 0
            status.value = "جاهز للتنزيل ✔"
            result.visible = True
            page.update()

        threading.Thread(target=work, daemon=True).start()

    def stop(_):
        state["cancel"] = True
        status.value = "جاري الإيقاف..."
        page.update()

    def download(_):
        if state.get("busy"):
            return
        batch = bool(state.get("batch"))
        link = state["url"] if batch else url.value.strip()
        state.update(busy=True, cancel=False, done=0, ids=set())
        status.value = "بدأ التنزيل..."
        open_btn.visible = False
        stop_btn.visible = batch
        page.update()

        def hook(d):
            if state["cancel"]:
                raise DownloadCancelled()
            if d["status"] == "finished":
                state["ids"].add((d.get("info_dict") or {}).get("id") or d.get("filename"))
                state["done"] = len(state["ids"])
                if str(d.get("filename", "")).endswith(".m4a"):
                    embed_cover(d["filename"], d.get("info_dict") or {})
            elif d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                if not total:
                    return
                frac = d["downloaded_bytes"] / total
                inf = d.get("info_dict") or {}
                idx, n = inf.get("playlist_index"), inf.get("n_entries") or state.get("n")
                if batch and idx and n:
                    bar.value = ((idx - 1) + frac) / n
                    head = f"({idx}/{n}) {str(inf.get('title', ''))[:35]}  •  "
                else:
                    bar.value, head = frac, ""
                status.value = (f"{head}{int(frac * 100)}%  •  {clean(d.get('_speed_str', ''))}"
                                f"  •  باقي {clean(d.get('_eta_str', ''))}")
                page.update()

        def work():
            failed = False
            folder = save_dir()
            try:
                if state["direct"]:
                    fn = os.path.basename(urlparse(link).path) or "downloadme.bin"
                    urllib.request.urlretrieve(link, os.path.join(folder, fn))
                    state["done"] = 1
                else:
                    opts = {**base_opts(), "format": quality.value, "merge_output_format": "mp4", "progress_hooks": [hook],
                            "outtmpl": os.path.join(folder, "%(title).80s.%(ext)s")}
                    if batch:
                        folder = os.path.join(folder, state["folder"])
                        opts.update(noplaylist=False, ignoreerrors=True, download_archive=ARCHIVE,
                                    sleep_interval=1, max_sleep_interval=4,
                                    outtmpl=os.path.join(folder, "%(title).80s.%(ext)s"))
                        if limit.value.strip().isdigit() and int(limit.value) > 0:
                            opts["playlistend"] = int(limit.value)
                    with YoutubeDL(opts) as y:
                        y.download([link])
            except Exception as ex:
                if not state["cancel"]:
                    status.value, failed = friendly(ex), True
            if not failed:
                if state["cancel"]:
                    status.value = f"تم الإيقاف. نزل {state['done']} مقطع"
                elif batch and not state["done"]:
                    status.value = "ما نزل شي: يمكن نزّلتها من قبل، أو تحقق من cookies.txt أو انتظر (429)"
                else:
                    bar.value = 1
                    status.value = (f"تم تنزيل {state['done']} مقطع في: {folder} 🎉" if batch
                                    else f"تم الحفظ في: {folder} 🎉")
            if state["done"]:
                state["count"] += state["done"]
                s_sess.value = str(state["count"])
                add_hist(f"{title.value} ({state['done']} مقطع)" if batch else title.value)
                open_btn.visible = page.platform not in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS)
            state["busy"] = False
            stop_btn.visible = False
            page.update()

        threading.Thread(target=work, daemon=True).start()

    analyze_btn.on_click = analyze
    url.on_submit = analyze
    dl_btn.on_click = download
    stop_btn.on_click = stop

    # ---------- التخطيط (يتكيف تلقائياً: لابتوب / جوال) ----------
    left = ft.Column([logo, chips, ft.Container(height=4), url, analyze_btn, err, stats, recent_box],
                     spacing=18, horizontal_alignment="stretch")
    right = ft.Column([result, empty], spacing=18)
    body = ft.Container(
        padding=ft.padding.symmetric(30, 24),
        content=ft.ResponsiveRow(
            [ft.Container(left, col={"xs": 12, "lg": 5}, padding=10),
             ft.Container(right, col={"xs": 12, "lg": 7}, padding=10)],
            vertical_alignment="start", run_spacing=20),
    )

    def orb(size, color, **pos):
        return ft.Container(
            width=size, height=size,
            gradient=ft.RadialGradient(colors=[op(0.22, color), op(0.0, color)]), **pos)

    page.add(ft.SafeArea(expand=True, content=ft.Stack(
        [orb(660, "#3B82F6", left=-230, top=-250), orb(580, "#2DD4BF", right=-250, bottom=-230),
         ft.Column([body], scroll=ft.ScrollMode.AUTO, expand=True, horizontal_alignment="stretch")],
        expand=True,
    )))

    def pulse():
        on = False
        while True:
            on = not on
            try:
                badge.scale = 1.04 if on else 1.0
                badge.shadow = ft.BoxShadow(blur_radius=60 if on else 30, color=op(0.5 if on else 0.3, NEON))
                badge.update()
            except Exception:
                return
            time.sleep(2)

    threading.Thread(target=pulse, daemon=True).start()

    if page.platform == ft.PagePlatform.ANDROID:
        ph = ft.PermissionHandler()
        page.overlay.append(ph)
        page.update()

        def ask():
            try:
                if ph.check_permission(ft.PermissionType.MANAGE_EXTERNAL_STORAGE) != ft.PermissionStatus.GRANTED:
                    ph.request_permission(ft.PermissionType.MANAGE_EXTERNAL_STORAGE)
            except Exception:
                pass

        threading.Thread(target=ask, daemon=True).start()


ft.app(target=main)
