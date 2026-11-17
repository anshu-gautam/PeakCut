"""Reading the screen: hooks written from what is shown, and moments chosen by eye, where little is said.

Runs against the code directly, with its own empty data folder. No AI is asked and no video is read: the AI's
answers and the frames are stood in for."""
import io, os, sys, tempfile
os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-screen-")
sys.path.insert(0, ".")
import numpy as np
from PIL import Image
from studio import ai, brain, jobs, screen
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)

def jpeg(colour):
    b = io.BytesIO(); Image.new("RGB", (160, 90), colour).save(b, "JPEG"); return b.getvalue()

video = os.path.join(tempfile.mkdtemp(), "v.mp4")
open(video, "wb").write(b"x")                       # only has to exist: the frames are stood in for
screen.frame = lambda path, t, width=screen.TILE_W: jpeg((int(t) % 255, 80, 120))
answer = {"text": ""}
ai.see = lambda prompt, image, timeout=None: (answer["text"], 10, 5)

# ---- is so little said that the picture should speak?
talk = [{"w": "word", "s": i * 0.3, "e": i * 0.3 + 0.2} for i in range(100)]
check("a talky clip is not quiet", screen.quiet(talk, 0, 30), False)
check("a few words in a minute is quiet", screen.quiet(talk[:8], 0, 60), True)
check("no words at all is quiet", screen.quiet([], 0, 30), True)

# ---- the moments looked at, and the picture made of them
check("frames are spread inside the stretch", screen.spread(0, 40, 4), [5.0, 15.0, 25.0, 35.0])
pic = screen.sheet([jpeg((200, 0, 0)), jpeg((0, 200, 0)), jpeg((0, 0, 200))], cols=2)
check("the sheet is one JPEG", pic[:2], b"\xff\xd8")
check("two columns, two rows", Image.open(io.BytesIO(pic)).size, (320, 180))
check("a frame that could not be read leaves a gap", bool(screen.sheet([jpeg((9, 9, 9)), b"junk"], cols=2)), True)
check("no frames, no sheet", screen.sheet([b"", b""], cols=2), b"")

# ---- a stretch made the right length
check("a short pick grows around its middle", screen.fit(100, 110, 0, 240, 30, 60), (90.0, 120.0))
check("a long pick is cut around its middle", screen.fit(0, 200, 0, 240, 15, 60), (70.0, 130.0))
check("it stays inside the part", screen.fit(230, 240, 0, 240, 30, 60), (210.0, 240.0))

# ---- hook and title from the screen
answer["text"] = 'Here you go: {"hook": "the chase begins", "title": "A chase through the docks", "description": "A car is chased.", "score": 72}'
g = screen.ground(video, 3, 62, said="", title="Some game", game="gta 6")
check("the hook comes back in capitals", g["hook"], "THE CHASE BEGINS")
check("with a title, a description and a score", (g["title"], g["description"], g["score"]),
      ("A chase through the docks", "A car is chased.", 72))
answer["text"] = "I cannot see images."
check("a text-only model changes nothing", screen.ground(video, 3, 62), None)
answer["text"] = '{"hook": "", "title": "x"}'
check("an answer with no hook changes nothing", screen.ground(video, 3, 62), None)
check("a video that is not there changes nothing", screen.ground(video + ".gone", 3, 62), None)
def boom(*a, **k): raise RuntimeError("HTTP 503")
ai.see, keep = boom, ai.see
check("a failed call changes nothing", screen.ground(video, 3, 62), None)
calls = []
def busy_once(prompt, image, timeout=None):
    calls.append(1)
    if len(calls) == 1:
        raise RuntimeError("The AI did not answer: HTTP 503 high demand")
    return ('{"hook": "second try", "title": "t", "description": "d", "score": 50}', 10, 5)
ai.see, screen.WAIT = busy_once, 0
check("a busy service is asked again", (screen.ground(video, 3, 62) or {}).get("hook"), "SECOND TRY")
calls.clear()
def refused(prompt, image, timeout=None):
    calls.append(1); raise RuntimeError("HTTP 400 this model cannot read pictures")
ai.see = refused
check("a refusal is not asked again", (screen.ground(video, 3, 62), len(calls)), (None, 1))
ai.see = keep

# ---- the moment chosen by eye
answer["text"] = '{"first": 7, "last": 9, "reason": "a car leaves the garage"}'
p = screen.pick(video, 0, 240, 15, 60, title="Some game")
check("frames 7 to 9 of a 4 minute part", p[:2], (120.0, 180.0))
check("with the reason", p[2], "a car leaves the garage")
answer["text"] = '{"first": 5, "last": 5, "reason": "one moment"}'
check("one frame grows to the shortest clip", (lambda r: r[1] - r[0])(screen.pick(video, 0, 240, 30, 60)), 30.0)
answer["text"] = '{"first": 0, "last": 0, "reason": "menus only"}'
check("nothing worth a clip is believed", screen.pick(video, 0, 240, 15, 60), None)
answer["text"] = '{"first": 9, "last": 40}'
check("a frame that does not exist is refused", screen.pick(video, 0, 240, 15, 60), None)
answer["text"] = '{"first": 9, "last": 3}'
check("an end before the start is refused", screen.pick(video, 0, 240, 15, 60), None)
check("a part shorter than a clip is not looked at", screen.pick(video, 0, 10, 15, 60), None)

# ---- where the sound jumps, when nothing is said
db = np.full(300, -40.0); db[100] = -10.0; db[220] = -12.0
lm = brain.loud_moments(db, 2, 15, 60, 300)
check("two jumps, two moments, in time order", [round(m["start"]) for m in lm], [88, 208])
check("each holds its jump", all(m["start"] <= t <= m["end"] for m, t in zip(lm, (100, 220))), True)
check("the hook is left for the screen", [m["hook"] for m in lm], ["", ""])
check("an even stretch has no jump", brain.loud_moments(np.full(300, -30.0), 2, 15, 60, 300), [])
check("moments never overlap", len(brain.loud_moments(db, 5, 15, 60, 300)), 2)
gaps = np.full(300, -33.0); gaps[::7] = -97.0; gaps[150] = -15.0
check("dead silence does not hide a real jump", [round(m["start"]) for m in brain.loud_moments(gaps, 1, 15, 60, 300)], [138])

# ---- a quiet part of a video that is at hand is looked through, a few minutes at a time
looked = []
def fake_pick(path, s, e, min_len, max_len, title="", game=None, timeout=None):
    looked.append((s, e)); return (s + 30.0, s + 60.0, "something happens") if s < 480 else None
keep_pick, screen.pick = screen.pick, fake_pick
ej = {"title": "A game", "options": {**jobs.DEFAULTS, "screen": True}}
eye = jobs._by_eye(ej, video, 0.0, 720.0, 5, "gta 6")
check("twelve minutes is looked at in three pictures", looked, [(0.0, 240.0), (240.0, 480.0), (480.0, 720.0)])
check("a part with nothing in it gives no clip", [(c["start"], c["end"]) for c in eye], [(30.0, 60.0), (270.0, 300.0)])
check("the reason says it was chosen by looking", eye[0]["reason"], "Chosen by looking at the video: something happens")
looked.clear()
check("it stops when it has enough", (len(jobs._by_eye(ej, video, 0.0, 720.0, 1, None)), len(looked)), (1, 1))
screen.pick = keep_pick

# ---- the option, and which clips are read from the screen
check("Read the screen is a switch", jobs.clean_options({"screen": True})["screen"], True)
try:
    jobs.clean_options({"screen": "yes"}); refused = False
except ValueError:
    refused = True
check("it must be on or off", refused, True)
check("it is off unless asked for", jobs.DEFAULTS["screen"], False)
asked = []
def fake_ground(src, s, e, said="", title="", uploader="", game=None, note="", timeout=None):
    asked.append((s, e)); return {"hook": "SEEN", "title": "Seen title", "description": "Seen.", "score": 64}
screen.ground = fake_ground
job = {"title": "A game", "uploader": "someone", "creator": None, "game": "gta 6", "options": {"screen": True}}
quiet_clip = {"start": 110.0, "end": 140.0, "hook": "", "score": 0}
jobs._from_screen(job, quiet_clip, [], video, 100.0)
check("a clip with no hook is read from the screen", (quiet_clip["hook"], quiet_clip["title"], quiet_clip["score"]), ("SEEN", "Seen title", 64))
check("times are given in the file's own seconds", asked[-1], (10.0, 40.0))
check("it carries the game's tags", "GTA6" in quiet_clip["hashtags"], True)
talky = {"start": 0.0, "end": 30.0, "hook": "HE SAID IT", "score": 88}
jobs._from_screen(job, talky, talk, video, 0.0)
check("a talky clip keeps the hook from its words", talky["hook"], "HE SAID IT")
quiet_hooked = {"start": 0.0, "end": 60.0, "hook": "SOMETHING VAGUE", "score": 88}
jobs._from_screen(job, quiet_hooked, talk[:5], video, 0.0)
check("a quiet clip's hook is rewritten", quiet_hooked["hook"], "SEEN")
check("but a score the AI gave is kept", quiet_hooked["score"], 88)
mine = {"start": 0.0, "end": 30.0, "hook": "MY OWN WORDS", "chosen": True}
jobs._from_screen(job, mine, [], video, 0.0)
check("a moment the person described keeps their words", mine["hook"], "MY OWN WORDS")
placeholder = {"start": 0.0, "end": 30.0, "hook": "MOST REPLAYED", "chosen": False}
jobs._from_screen(job, placeholder, [], video, 0.0)
check("a stand-in hook is replaced", placeholder["hook"], "SEEN")
screen.ground = lambda *a, **k: None
kept = {"start": 0.0, "end": 30.0, "hook": "", "title": "Old"}
jobs._from_screen(job, kept, [], video, 0.0)
check("no answer leaves the clip as it was", (kept["hook"], kept["title"]), ("", "Old"))

print("ALL PASSED" if not fails else f"{len(fails)} FAILED")
sys.exit(1 if fails else 0)
