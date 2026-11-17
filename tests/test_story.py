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
