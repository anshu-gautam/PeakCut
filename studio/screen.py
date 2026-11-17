"""Reading the screen: for clips where little is said, the picture is what the clip is about.

PeakCut picks clips and writes their hooks from the transcript. A game played with no commentary, a trailer, a
chase with nobody talking: the words say almost nothing there, and the hook comes out empty or beside the point.

So a few frames of the clip are put side by side in one picture (a "sheet", each frame numbered) and shown to
the AI with whatever was said. It is used for two things:

  ground()  the hook, title and post text of a clip that is already chosen, written from what is on screen
  pick()    which stretch of a longer part is worth clipping, when the words give nothing to choose by

Only one picture goes out per question, so it costs one AI call, and any service that reads pictures works.
A text-only model, a service that refuses pictures or an answer that makes no sense all return None, and the
caller keeps what it had. The picture goes to the AI service that is set up, the same one the transcript goes to."""
import io
import subprocess
import time
from pathlib import Path

from . import ai, brain, usage
from .media import NO_WINDOW

QUIET_WORDS_PER_SEC = 1.0     # fewer words than this and the picture carries the clip, not the talking
GROUND_FRAMES = 4
PICK_FRAMES = 12
TILE_W = 384
TRIES, WAIT = 3, 4     # a busy AI service is asked again: after 4 seconds, then after 8


def quiet(words: list, start: float, end: float) -> bool:
    """Is so little said between start and end that the hook should come from the picture?"""
    said = sum(1 for w in words if start <= w.get("s", -1) <= end)
    return said < QUIET_WORDS_PER_SEC * max(1.0, end - start)


def frame(path, t: float, width: int = TILE_W) -> bytes:
    """One frame of a video at second t, small, as a JPEG. Empty when it cannot be read."""
    try:
        return subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.2f}", "-i", str(path), "-frames:v", "1",
             "-vf", f"scale={width}:-2", "-pix_fmt", "yuvj420p", "-q:v", "5", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
            capture_output=True, timeout=60, creationflags=NO_WINDOW).stdout or b""
    except Exception:  # noqa: BLE001
        return b""


def spread(start: float, end: float, n: int) -> list:
    """n moments spread evenly through a stretch, never right on its first or last frame."""
    step = (end - start) / n
    return [round(start + step * (i + 0.5), 2) for i in range(n)]


def sheet(jpegs: list, cols: int) -> bytes:
    """Frames side by side in one JPEG, each with its number in the corner, so the AI can say which is which."""
    from PIL import Image, ImageDraw, ImageFont
    tiles = []
    for j in jpegs:
        try:
            tiles.append(Image.open(io.BytesIO(j)).convert("RGB"))
        except Exception:  # noqa: BLE001 - a frame that could not be read leaves a gap, not a failure
            tiles.append(None)
    good = [t for t in tiles if t is not None]
    if not good:
        return b""
    w, h = good[0].size
    rows = -(-len(tiles) // cols)
    out = Image.new("RGB", (cols * w, rows * h), (0, 0, 0))
    draw = ImageDraw.Draw(out)
    try:
        font = ImageFont.load_default(size=max(18, h // 8))
    except TypeError:                      # an older Pillow: its one small font
        font = ImageFont.load_default()
    for i, t in enumerate(tiles):
        x, y = (i % cols) * w, (i // cols) * h
        if t is not None:
            out.paste(t.resize((w, h)), (x, y))
        label = str(i + 1)
        box = draw.textbbox((0, 0), label, font=font)
        draw.rectangle([x, y, x + box[2] + 14, y + box[3] + 12], fill=(0, 0, 0))
        draw.text((x + 7, y + 4), label, fill=(255, 255, 255), font=font)
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def _ask(prompt: str, picture: bytes, purpose: str, timeout=None):
    """The AI's answer about one picture, as parsed JSON, or None."""
    if not picture:
        return None
    text = sent = wrote = None
    for attempt in range(TRIES):
        try:
            text, sent, wrote = ai.see(prompt, picture, timeout)
            break
        except Exception as e:  # noqa: BLE001 - no answer is not a failure: the caller keeps what it had
            # A busy or rate-limited service is asked again after a short wait, like the text questions are.
            if attempt + 1 < TRIES and ("HTTP 429" in str(e) or "HTTP 5" in str(e)):
                time.sleep(WAIT * (attempt + 1))
                continue
            return None
    if sent or wrote:
        usage.record(sent, wrote, purpose)
    try:
        return ai._parse(text) if text else None
    except Exception:  # noqa: BLE001
        return None


GROUND = """These are {n} frames from one short vertical clip, in order, numbered 1 to {n}.
Video title: {title}
Channel: {uploader}{game}{note}
What is said in the clip: {said}

Write the text for this clip from what is SHOWN, with the words only as support. Describe what actually
happens on screen. Do not invent commentary, a streamer or a reaction that is not there.
- hook: 2 to 5 words, in capitals, naming what happens ("THE CHASE BEGINS", "HE JUMPED"). No sentence that
  needs explaining, no swear words.
- title: one line a person would search for, under 90 characters.
- description: one sentence about what happens.
- score: 0-100, how likely a stranger is to watch this to the end.

Answer with one JSON object and nothing else:
{{"hook": "...", "title": "...", "description": "...", "score": 0}}"""


def ground(path, start: float, end: float, said: str = "", title: str = "", uploader: str = "", game=None,
           note: str = "", timeout=None):
    """Hook, title and post text for the clip between start and end of the video at `path` (seconds in that
    file), from what is on screen. Returns {"hook", "title", "description", "score"} or None."""
    if not Path(str(path)).is_file() or end - start < 1:
        return None
    pic = sheet([frame(path, t) for t in spread(start, end, GROUND_FRAMES)], cols=2)
    prompt = GROUND.format(n=GROUND_FRAMES, title=brain._safe(title) or "unknown", uploader=brain._safe(uploader) or "unknown",
                           game=f"\nGame: {brain._safe(game)}" if game else "",
                           note=f"\nWhat happens, in the viewer's words: {brain._safe(note, 300)}" if note else "",
                           said=brain._safe(said, 1500) or "(nothing)")
    out = _ask(prompt, pic, "Screen: hook and title", timeout)
    if isinstance(out, list):
        out = out[0] if out else None
    if not isinstance(out, dict) or not str(out.get("hook") or "").strip():
        return None
    tidy = brain._tidy(out, start, end, game)
    return {k: tidy[k] for k in ("hook", "title", "description", "score")}


PICK = """These are {n} frames from one part of a video, in order, numbered 1 to {n}. Each frame is
{step:.0f} seconds after the one before it.
Video title: {title}{game}

Little or nothing is said in this part, so choose by what is SHOWN. Find the stretch a stranger would most
want to watch as a short clip: where something happens (a chase, a crash, a fight, a reveal, a funny or
surprising moment), not menus, loading screens, maps or people standing still.

Answer with one JSON object and nothing else:
{{"first": <number of the frame where the stretch begins>, "last": <number of the frame where it ends>,
"reason": "what happens there, in a few words"}}
If nothing in these frames is worth a clip, answer {{"first": 0, "last": 0, "reason": "why"}}."""


def pick(path, start: float, end: float, min_len: float, max_len: float, title: str = "", game=None, timeout=None):
    """The stretch worth clipping between start and end of the video at `path`, chosen by looking.
    Returns (start, end, reason) in that file's seconds, or None when there is nothing to go on."""
    if not Path(str(path)).is_file() or end - start < min_len:
        return None
    times = spread(start, end, PICK_FRAMES)
    step = (end - start) / PICK_FRAMES
    pic = sheet([frame(path, t) for t in times], cols=4)
    out = _ask(PICK.format(n=PICK_FRAMES, step=step, title=brain._safe(title) or "unknown",
                           game=f"\nGame: {brain._safe(game)}" if game else ""), pic, "Screen: choosing the moment", timeout)
    if isinstance(out, list):
        out = out[0] if out else None
    if not isinstance(out, dict):
        return None
    try:
        first, last = int(float(out.get("first") or 0)), int(float(out.get("last") or 0))
    except (TypeError, ValueError):
        return None
    if not (1 <= first <= PICK_FRAMES and 1 <= last <= PICK_FRAMES) or last < first:
        return None
    return fit(times[first - 1] - step / 2, times[last - 1] + step / 2, start, end, min_len, max_len) + (
        brain._text(out.get("reason"), 200),)


def fit(a: float, b: float, lo: float, hi: float, min_len: float, max_len: float) -> tuple:
    """A chosen stretch made the right length: grown around its middle to min_len, cut around it to max_len,
    and kept inside lo..hi."""
    mid = (a + b) / 2
    length = max(min_len, min(max_len, b - a))
    length = min(length, hi - lo)
    a = max(lo, min(hi - length, mid - length / 2))
    return round(a, 2), round(a + length, 2)
