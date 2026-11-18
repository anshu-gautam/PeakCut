"""Clips that make sense on their own: whole scenes, hooks that promise something, titles true to what is shown,
credits left out, no captions on top of a game's own subtitles, and games that are not on the list.

Runs against the code directly, with its own empty data folder. No AI is asked and no video is read: the AI's
answers and the frames are stood in for."""
import io, os, sys, tempfile
os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-story-")
sys.path.insert(0, ".")
from PIL import Image
from studio import ai, brain, config, jobs, media, screen
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)

def jpeg():
    b = io.BytesIO(); Image.new("RGB", (160, 90), (40, 40, 40)).save(b, "JPEG"); return b.getvalue()

video = os.path.join(tempfile.mkdtemp(), "v.mp4")
open(video, "wb").write(b"x")
screen.frame = lambda path, t, width=screen.TILE_W: jpeg()
answer = {"text": ""}
seen_prompts = []
def fake_see(prompt, image, timeout=None):
    seen_prompts.append(prompt); return (answer["text"], 10, 5)
ai.see = fake_see

# ---- what the AI is told when it picks clips
rules = brain.RULES + brain.GAME_RULES
check("a clip is a whole beat, set-up and outcome", "set-up" in rules and "outcome" in rules, True)
check("a chase is not cut while it is still happening", "still under way" in rules, True)
check("credits, menus and tutorials are never picked", all(w in rules for w in ("credits", "menus", "tutorials")), True)
check("a hook is never a line that needs the scene", "NOTHING PERSONAL" in rules and "Never a line" in rules, True)
check("titles must be true to the clip", "Never claim a betrayal" in rules, True)
check("the old rule that a hook is what was said is gone", "The hook is what was said" in rules, False)

# ---- a game's clips are long enough for a scene
asked = []
def fake_ask(prompt, schema=None, purpose="", timeout=None):
    asked.append(prompt); return [], "m", 0
brain.ask_ai, keep_ask = fake_ask, brain.ask_ai
words = [{"w": f"w{i}.", "s": i * 2.0, "e": i * 2.0 + 1.5} for i in range(200)]
import numpy as np
brain.find_clips(words, np.zeros(400), 400, "t", "u", 3, 15, 60, game="Grand Theft Auto V")
check("a game asks for clips of 25 seconds or more", "Each clip is 25 to 60 seconds" in asked[-1], True)
brain.find_clips(words, np.zeros(400), 400, "t", "u", 3, 15, 60)
check("a talk video keeps the length it was given", "Each clip is 15 to 60 seconds" in asked[-1], True)
brain.find_clips(words, np.zeros(400), 400, "t", "u", 3, 10, 30, game="Fortnite")
check("short clips asked for stay short", "Each clip is 10 to 30 seconds" in asked[-1], True)

# ---- naming a game that is not on the list
config.ai_ready = lambda: True
brain.ask_ai = lambda prompt, schema=None, purpose="", timeout=None: ({"game": "007 First Light"}, "m", 3)
check("a game not on the list is named from the title", brain.name_game("007 FIRST LIGHT Walkthrough"), "007 First Light")
brain.ask_ai = lambda prompt, schema=None, purpose="", timeout=None: ({"game": ""}, "m", 3)
check("a video that is no game stays without one", brain.name_game("I cooked pasta"), "")
brain.ask_ai = lambda prompt, schema=None, purpose="", timeout=None: ({"game": "visit https://x.com"}, "m", 3)
check("a link is never taken as a name", brain.name_game("x"), lambda g: "http" not in g)
def down(*a, **k): raise RuntimeError("HTTP 503")
brain.ask_ai = down
check("no answer, no game", brain.name_game("007 FIRST LIGHT"), "")
brain.ask_ai = keep_ask

keep_review = screen.review

# ---- the check against the frames
answer["text"] = '{"keep": false, "why": "opening credits", "subtitles": false, "hook": "", "title": "", "description": "", "score": 0}'
r = screen.review(video, 0, 60, "", "", "", "")
check("credits are not kept", (r["keep"], r["why"]), (False, "opening credits"))
answer["text"] = ('{"keep": true, "why": "training", "subtitles": true, "hook": "testing a new gadget", '
                  '"title": "Bond tests a gadget on his partner", "description": "A training drill.", "score": 75}')
r = screen.review(video, 0, 30, "Sorry, Ronson. Nothing personal.", "NOTHING PERSONAL", "Bond betrays his teammate!", "x")
check("an untrue title is replaced", (r["hook"], r["title"]), ("TESTING A NEW GADGET", "Bond tests a gadget on his partner"))
check("the text it had is shown to the AI", "Bond betrays his teammate!" in seen_prompts[-1], True)
check("subtitles are read", r["subtitles"], True)
answer["text"] = '{"keep": "no", "hook": "x"}'
check("keep written as a word is read", screen.review(video, 0, 30)["keep"], False)
answer["text"] = "I can't see pictures."
check("no usable answer leaves the clip alone", screen.review(video, 0, 30), None)
check("a missing file is not looked at", screen.review(video + ".gone", 0, 30), None)

# ---- subtitles, looked for on one full-size frame of someone speaking
said = [{"w": "hello", "s": 2.0, "e": 2.4}, {"w": "there", "s": 2.5, "e": 2.9}, {"w": "friend", "s": 3.0, "e": 3.5}]
answer["text"] = '{"subtitles": true}'
check("burned-in subtitles are found", screen.has_subtitles(video, said, 0, 10), True)
answer["text"] = '{"subtitles": false}'
check("none is none", screen.has_subtitles(video, said, 0, 10), False)
check("nobody speaking, nothing to look at", screen.has_subtitles(video, said[:1], 0, 10), None)
answer["text"] = '{"subtitles": "maybe"}'
check("an unclear answer is no answer", screen.has_subtitles(video, said, 0, 10), None)

# ---- what happens to a clip
def make_job(game="Grand Theft Auto V", **opts):
    return {"title": "A game video", "uploader": "u", "creator": None, "game": game, "clips": [],
            "options": {**jobs.DEFAULTS, **opts}}
reply = {"r": None, "subs": False}
screen.review = lambda *a, **k: reply["r"]
screen.has_subtitles = lambda *a, **k: reply["subs"]
reply["r"] = {"keep": False, "why": "opening credits", "subtitles": False, "hook": "", "title": "", "description": "", "score": 0}
job = make_job(); clip = {"id": "clip01", "start": 0.0, "end": 60.0, "hook": "", "score": 0}
check("a credits clip is left out", jobs._review(job, clip, [], video, 0.0), True)
check("with the reason", clip["reason"], "Left out after looking at it: opening credits.")
mine = {"id": "clip02", "start": 0.0, "end": 60.0, "hook": "MY WORDS", "chosen": True}
check("a moment the person chose is never left out", jobs._review(job, mine, [], video, 0.0), False)
reply["r"] = {"keep": True, "why": "", "subtitles": False, "hook": "TESTING A NEW GADGET",
              "title": "Bond tests a gadget", "description": "A drill.", "score": 70}
c = {"id": "clip03", "start": 0.0, "end": 30.0, "hook": "NOTHING PERSONAL", "title": "Bond betrays his teammate!", "score": 90}
jobs._review(job, c, [], video, 0.0)
check("the hook and title are made true", (c["hook"], c["title"]), ("TESTING A NEW GADGET", "Bond tests a gadget"))
check("the two scores meet in the middle", c["score"], 80)
check("the game's tags are added", "GTA5" in c["hashtags"], True)
mine = {"id": "clip04", "start": 0.0, "end": 30.0, "hook": "MY WORDS", "title": "My title", "chosen": True, "score": 0}
jobs._review(job, mine, [], video, 0.0)
check("a person's own words are kept", (mine["hook"], mine["title"]), ("MY WORDS", "My title"))
reply["subs"] = True
job = make_job(); c = {"id": "clip05", "start": 0.0, "end": 30.0, "hook": "X", "captions": True}
jobs._review(job, c, said, video, 0.0)
check("captions are turned off when the game has its own", (c["captions"], job["burned_subs"]), (False, True))
check("and the card says why", "own subtitles" in job["notice"], True)
reply["subs"] = None
c2 = {"id": "clip06", "start": 30.0, "end": 60.0, "hook": "Y", "captions": True}
jobs._review(job, c2, said, video, 0.0)
check("the answer is kept for the whole video", c2["captions"], False)
reply["subs"] = False
job = make_job(); c = {"id": "clip07", "start": 0.0, "end": 30.0, "hook": "X", "captions": True}
jobs._review(job, c, said, video, 0.0)
check("no subtitles, captions stay on", c["captions"], True)
reply["r"] = None
c = {"id": "clip08", "start": 0.0, "end": 30.0, "hook": "OLD", "title": "Old"}
check("no answer, the clip is made as it was", (jobs._review(make_job(), c, [], video, 0.0), c["hook"]), (False, "OLD"))
config.ai_ready = lambda: False
reply["r"] = {"keep": False, "why": "x", "subtitles": False, "hook": "", "title": "", "description": "", "score": 0}
check("with no AI set up nothing is asked", jobs._review(make_job(), {"start": 0.0, "end": 30.0}, [], video, 0.0), False)
config.ai_ready = lambda: True

# ---- a clip that stops before its outcome, and where the crop points
from studio import render
screen.review = keep_review
answer["text"] = ('{"keep": true, "why": "", "subtitles": false, "hook": "rushing to save her", "title": "t", '
                  '"description": "d", "score": 80, "more": 14, "subject": [50, 40, 45, 50]}')
after = [{"w": "there.", "s": 33.0, "e": 33.4}, {"w": "Oh,", "s": 41.0, "e": 41.3}, {"w": "fine.", "s": 44.5, "e": 45.0}]
r = screen.review(video, 0, 31, "she is in trouble", after=after, room=29)
check("it says how much longer the clip needs", r["more"], 14.0)
check("the words after the clip are shown to the AI", "[+2.0] there." in seen_prompts[-1], True)
check("with how much room there is", " ".join(seen_prompts[-1].split()).count("at most 29."), 1)
check("the subject is read frame by frame", [x for _, x in r["focus"]], [0.5, 0.4, 0.45, 0.5])
check("at the frames' own times in the clip", [t for t, _ in r["focus"]], [3.88, 11.62, 19.38, 27.12])
answer["text"] = '{"keep": true, "hook": "x", "more": 500, "subject": [30, 680, 500, 690]}'
r = screen.review(video, 0, 31, room=10)
check("it never asks for more than there is room for", r["more"], 10.0)
check("positions that aren't 0 to 100 are not used", r["focus"], None)
answer["text"] = '{"keep": true, "hook": "x", "subject": [20, 30]}'
check("too few positions are not used", screen.review(video, 0, 31)["focus"], None)

screen.review = lambda *a, **k: reply["r"]
reply["subs"] = False
words_long = [{"w": w, "s": s, "e": s + 0.4} for w, s in
              [("trouble.", 28.0), ("faster.", 30.5), ("there.", 33.0), ("Oh,", 41.0), ("fine.", 44.5), ("Next", 52.0)]]
reply["r"] = {"keep": True, "why": "", "subtitles": False, "hook": "RUSHING TO SAVE HER", "title": "t", "description": "d",
              "score": 80, "more": 14.0, "focus": [[3.88, 0.5], [11.62, 0.4], [19.38, 0.45], [27.12, 0.5]]}
job = make_job(max_len=60); job["duration"] = 3600
c = {"id": "clip09", "start": 0.0, "end": 31.0, "hook": "OLD", "layout": "crop", "src_end": 120.0}
jobs._review(job, c, words_long, video, 0.0)
check("a clip that stopped early runs on to where its outcome is said", c["end"], 45.2)
check("and is marked as carried on", c.get("extended"), True)
check("the crop is told where to point", c["focus"][1], [11.62, 0.4])
c = {"id": "clip10", "start": 0.0, "end": 31.0, "hook": "OLD", "layout": "crop", "src_end": 36.0}
jobs._review(job, c, words_long, video, 0.0)
check("never past the piece of video it is cut from, ending on a whole sentence", c["end"], 33.7)
job2 = make_job(max_len=40); job2["duration"] = 3600
c = {"id": "clip13", "start": 0.0, "end": 31.0, "hook": "OLD", "layout": "crop", "src_end": 120.0}
jobs._review(job2, c, words_long, video, 0.0)
check("at the longest length it ends on the last whole sentence that fits", c["end"], 33.7)
c = {"id": "clip14", "start": 0.0, "end": 31.0, "hook": "OLD", "layout": "crop", "src_end": 120.0}
nonstop = [{"w": "on", "s": 29.0 + i * 0.4, "e": 29.0 + i * 0.4 + 0.35} for i in range(45)]   # 29s to 47s, no pause
jobs._review(job2, c, nonstop, video, 0.0)
check("with no sentence ending in reach it keeps its length", (c["end"], c.get("extended")), (31.0, None))
c = {"id": "clip11", "start": 0.0, "end": 31.0, "hook": "OLD", "layout": "blur"}
jobs._review(job, c, words_long, video, 0.0)
check("a blurred-fill clip shows the whole picture: no crop point", "focus" in c, False)
mine = {"id": "clip12", "start": 0.0, "end": 31.0, "hook": "MY WORDS", "chosen": True, "layout": "crop"}
jobs._review(job, mine, words_long, video, 0.0)
check("a moment the person chose keeps its length", mine["end"], 31.0)
check("but still gets the crop pointed", bool(mine.get("focus")), True)

check("no crop point is the middle", render.focus_x(None), "0.5")
check("one place held the whole clip is one number", render.focus_x([[1, 0.3], [5, 0.32], [9, 0.31]]), "0.310")
moving = render.focus_x([[2, 0.25], [10, 0.75]])
check("a move glides between the two frames", moving.startswith("0.250+(0.500)*clip((t-6.00)/0.6+0.5"), True)
check("the crop follows it", "x='clip(in_w*(" in render._crop([[2, 0.25], [10, 0.75]]), True)
check("no crop point keeps the plain centred crop", render._crop(None), f"crop={render.W}:{render.H}")
pic = screen.sheet([jpeg(), jpeg()], cols=2, ruler=True)
check("frames can carry the 25 / 50 / 75 marks", pic[:2], b"\xff\xd8")

# ---- a webcam place found once is passed on to the other parts of the stream
check("a webcam place is kept as whole pixels", jobs.clean_options({"facecam": [0, 306.4, 258, 161]})["facecam"], [0, 306, 258, 161])
check("no webcam place is fine", "facecam" in jobs.clean_options({"facecam": None}), False)
for bad in ([1, 2, 3], ["a", 1, 2, 3], [0, 0, 2, 2], [0, 0, True, 50], "0,0,10,10"):
    try:
        jobs.clean_options({"facecam": bad}); refused = False
    except ValueError:
        refused = True
    check(f"a webcam place like {bad!r} is refused", refused, True)
check("it is not set unless given", jobs.DEFAULTS["facecam"], None)

# ---- the stream's own webcam is kept out of the crop, so the face isn't shown twice
cam = [0, 306, 258, 161]                       # on the left edge of a 1280x720 picture
kept = render.keep_out([[7, 0.25], [21, 0.5], [36, 0.3], [50, 0.68]], cam, 1280, 720)
check("a crop pointed at the webcam is moved clear of it", kept[0][1], 0.36)
check("one already clear stays where it was", (kept[1][1], kept[3][1]), (0.5, 0.68))
check("the times are kept", [t for t, _ in kept], [7.0, 21.0, 36.0, 50.0])
check("no crop point still keeps the webcam out", render.keep_out(None, cam, 1280, 720), [[0.0, 0.5]])
right = render.keep_out([[1, 0.9]], [1022, 20, 258, 161], 1280, 720)
check("a webcam on the right edge pushes the crop left", right[0][1], 0.64)
check("a webcam in the middle can't be avoided: left alone", render.keep_out([[1, 0.2]], [500, 20, 280, 161], 1280, 720), [[1, 0.2]])
check("no webcam, nothing changes", render.keep_out([[1, 0.2]], None, 1280, 720), [[1, 0.2]])

# ---- the big hook text can be left off the video
check("the hook is drawn unless asked otherwise", jobs.DEFAULTS["show_hook"], True)
check("it can be turned off for a video", jobs.clean_options({"show_hook": False})["show_hook"], False)
try:
    jobs.clean_options({"show_hook": "no"}); refused = False
except ValueError:
    refused = True
check("and must be on or off", refused, True)
drawn = []
jobs.render.render_clip = lambda src, out, name, local, words, w, h: (drawn.append(local["hook"]), {"file": "x.mp4", "cover": "x.jpg", "layout": "crop"})[1]
jobs.save = lambda job: None
src_file = os.path.join(tempfile.mkdtemp(), "s.mp4"); open(src_file, "wb").write(b"x")
def render_job(**opts):
    return {"id": "j", "dir": tempfile.mkdtemp(), "title": "t", "uploader": "u", "creator": None, "game": None,
            "source_path": src_file, "duration": 100, "width": 1280, "height": 720,
            "options": {**jobs.DEFAULTS, **opts}, "clips": []}
j = render_job(show_hook=False); c = {"id": "clip01", "start": 0.0, "end": 20.0, "hook": "BIG TEXT", "captions": False, "version": 1}
j["clips"].append(c); jobs.render_one(j, c, [])
check("with it off, no hook is drawn", drawn[-1], "")
check("but the hook is kept for the post", c["hook"], "BIG TEXT")
j = render_job(); c = {"id": "clip01", "start": 0.0, "end": 20.0, "hook": "BIG TEXT", "captions": False, "version": 1}
j["clips"].append(c); jobs.render_one(j, c, [])
check("with it on, the hook is drawn", drawn[-1], "BIG TEXT")
c["show_hook"] = False; jobs.render_one(j, c, [])
check("one clip can have it off on its own", drawn[-1], "")

# ---- a left-out clip's id is never reused
j = make_job(); j["clips"] = [{"id": "clip01"}, {"id": "clip03"}]
check("the next id is new", jobs._next_id(j), "clip04")
j["clips"] = [{"id": "clip01"}]
check("even after a clip is gone", jobs._next_id(j), "clip05")
check("ids keep counting", jobs._next_id(j), "clip06")
j = make_job(); j["dropped"] = [{"start": 2296.0, "end": 2356.0, "reason": "Left out after looking at it: opening credits."}]
jobs._note_dropped(j)
check("the card says which clip was left out and why", j["notice"], "1 clip was left out after looking at it: 38:16 (opening credits).")
jobs._note_dropped(j)
check("and says it once", j["notice"].count("left out"), 1)

# ---- Most replayed looks at the whole peak
heat = [{"start": i * 423.0, "end": (i + 1) * 423.0, "value": v} for i, v in enumerate([1.0, 0.2, 0.9] + [0.1] * 97)]
w = jobs._moment_windows({"options": {**jobs.DEFAULTS, "replayed": True, "max_clips": 1}}, {"duration": 42300, "heatmap": heat}, [])
check("a peak several minutes wide is looked at whole", round(w[0]["end"] - w[0]["start"]), 423)
big = [{"start": i * 900.0, "end": (i + 1) * 900.0, "value": v} for i, v in enumerate([1.0, 0.2, 0.9] + [0.1] * 97)]
w = jobs._moment_windows({"options": {**jobs.DEFAULTS, "replayed": True, "max_clips": 1}}, {"duration": 90000, "heatmap": big}, [])
check("but never more than 8 minutes of it", round(w[0]["end"] - w[0]["start"]), 480)

print("ALL PASSED" if not fails else f"{len(fails)} FAILED")
sys.exit(1 if fails else 0)
