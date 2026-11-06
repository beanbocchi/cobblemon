#!/usr/bin/env python3
"""Two AI companions that chat with players in the COBBLEVERSE server's global chat.

Runs on the host next to the `cobbleverse` container. It follows `docker logs`, keeps the recent chat, and asks
the model behind the local CLIProxyAPI (127.0.0.1:8317) what a companion would say. Messages go out with
`/tellraw` through rcon-cli, so the companions can only talk: they have no body in the world and run no other
command. A companion answers when someone says its name, sometimes joins a conversation, greets people who join
and starts a topic when chat has been quiet for a while. Personas and tuning live in personas.json; notes the
companions keep about players, and the recent chat, live in state.json.
"""
import json
import os
import random
import re
import subprocess
import threading
import time
import unicodedata
import urllib.request
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = json.load(open(os.path.join(HERE, "personas.json"), encoding="utf-8"))
STATE_FILE = os.path.join(HERE, "state.json")
KEY = open(os.path.expanduser("~/.config/cliproxyapi-remote.key"), encoding="utf-8").read().strip()
API = CONFIG.get("api", "http://127.0.0.1:8317/v1/chat/completions")
MODEL = CONFIG.get("model", "claude-sonnet-5-5")
CONTAINER = CONFIG.get("container", "cobbleverse")
PERSONAS = CONFIG["personas"]
TUNE = CONFIG["tuning"]

CHAT = re.compile(r"^\[([\d:]+)\] \[Server thread/INFO\]: (?:\[Not Secure\] )?<([A-Za-z0-9_]{1,16})> (.*)$")
JOIN = re.compile(r"^\[([\d:]+)\] \[Server thread/INFO\]: ([A-Za-z0-9_]{1,16}) (joined|left) the game$")
# Our own tellraw lines don't reach the log, so the companions' messages are added to history when sent.

lock = threading.Lock()
history = deque(maxlen=TUNE["history_lines"])
notes = {p["name"]: [] for p in PERSONAS}
online = set()
last_chat = time.time()
last_bot = {"time": 0.0, "name": None, "to": None}
sent_times = deque()


def log(*args):
    print(time.strftime("%H:%M:%S"), *args, flush=True)


def fold(text):
    """Lowercase without Vietnamese diacritics, for matching names."""
    text = unicodedata.normalize("NFD", text.lower()).replace("đ", "d")
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def load_state():
    try:
        state = json.load(open(STATE_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        return
    history.extend(state.get("history", []))
    for name, items in state.get("notes", {}).items():
        if name in notes:
            notes[name] = items[-TUNE["max_notes"]:]


def save_state():
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"history": list(history), "notes": notes}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_FILE)


def rcon(command):
    out = subprocess.run(["docker", "exec", CONTAINER, "rcon-cli", command],
                         capture_output=True, text=True, timeout=20)
    return re.sub(r"\x1b\[[0-9;]*m", "", out.stdout).strip()


def clean(text):
    """One short line of plain text: the Minecraft font has no emoji, and long lines wrap badly."""
    text = "".join(c for c in text if ord(c) < 0x10000 and unicodedata.category(c) not in ("So", "Cs", "Co"))
    text = re.sub(r"\s+", " ", text).strip().strip('"')
    limit = TUNE["max_chars"]
    if len(text) > limit:
        cut = text[:limit]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        text = cut[:end + 1] if end > limit // 2 else cut.rstrip() + "..."
    return text


def say(persona, text, to=None):
    message = [{"text": "<"}, {"text": persona["name"], "color": persona["color"]}, {"text": "> " + text}]
    rcon("tellraw @a " + json.dumps(message, ensure_ascii=False))
    now = time.time()
    with lock:
        history.append(f"[{time.strftime('%H:%M')}] <{persona['name']}> {text}")
        last_bot.update(time=now, name=persona["name"], to=to)
        sent_times.append(now)
        save_state()
    log("said", persona["name"], text)


def ask_model(persona, reason):
    others = ", ".join(p["name"] for p in PERSONAS if p is not persona)
    system = "\n".join([
        CONFIG["shared_rules"].replace("{name}", persona["name"]).replace("{others}", others),
        "",
        "Nhân vật của bạn:",
        persona["bio"],
        "",
        "Những điều bạn đã ghi nhớ:",
        "\n".join("- " + n for n in notes[persona["name"]]) or "- (chưa có)",
    ])
    with lock:
        transcript = "\n".join(history) or "(chưa ai nói gì)"
        players = ", ".join(sorted(online)) or "không ai"
    user = (f"Giờ thật: {time.strftime('%H:%M %d/%m')}. Đang online: {players}.\n\n"
            f"Chat gần đây (cũ trước, mới sau):\n{transcript}\n\n"
            f"Tình huống: {reason}\n\n"
            "Trả về đúng một object JSON, không thêm gì khác: "
            '{"say": "<tin nhắn tiếp theo của ' + persona["name"] + ', hoặc chuỗi rỗng nếu không nên nói>", '
            '"remember": "<một điều đáng nhớ lâu dài về người chơi hoặc nhóm, hoặc chuỗi rỗng>"}')
    body = json.dumps({"model": MODEL, "max_tokens": 2000,
                       "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    req = urllib.request.Request(API, data=body.encode(), headers={
        "Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        content = json.load(resp)["choices"][0]["message"]["content"] or ""
    match = re.search(r"\{.*\}", content, re.S)
    if not match:
        return "", ""
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return "", ""
    return clean(str(data.get("say") or "")), clean(str(data.get("remember") or ""))


def can_send():
    now = time.time()
    while sent_times and now - sent_times[0] > 600:
        sent_times.popleft()
    return now - last_bot["time"] >= TUNE["min_gap_s"] and len(sent_times) < TUNE["max_per_10min"]


def speak(persona, reason, to=None, chain=0):
    if not online:
        return
    try:
        text, memo = ask_model(persona, reason)
    except Exception as e:  # network or proxy hiccup: stay quiet this time
        log("model error", persona["name"], repr(e))
        return
    if memo:
        with lock:
            items = notes[persona["name"]]
            if memo not in items:
                items.append(memo)
                del items[:-TUNE["max_notes"]]
            save_state()
    if not text or not can_send():
        return
    # Typing takes a moment; a reply that lands instantly reads like a bot.
    time.sleep(min(2 + len(text) / 25, 8))
    say(persona, text, to)
    if chain < 1 and random.random() < TUNE["banter_chance"]:
        other = random.choice([p for p in PERSONAS if p is not persona])
        time.sleep(random.uniform(4, 10))
        speak(other, f"{persona['name']} vừa nói câu cuối trong chat. Bạn có thể đáp lại {persona['name']}, "
                     "trêu nhẹ hoặc thêm ý, hoặc để trống nếu không có gì hay để nói.", chain=chain + 1)


busy = threading.Lock()


def run(fn, *args, **kwargs):
    """One companion action at a time; drop the trigger if one is already running."""
    def job():
        if not busy.acquire(blocking=False):
            return
        try:
            fn(*args, **kwargs)
        finally:
            busy.release()
    threading.Thread(target=job, daemon=True).start()


def mentioned(text):
    folded = fold(text)
    return [p for p in PERSONAS if any(re.search(r"\b" + re.escape(a) + r"\b", folded) for a in p["aliases"])]


def on_chat(player, text):
    global last_chat
    now = time.time()
    with lock:
        history.append(f"[{time.strftime('%H:%M')}] <{player}> {text}")
        last_chat = now
        save_state()
    if text.startswith("!q"):
        return  # questions for Claude, answered elsewhere
    names = mentioned(text)
    if names:
        run(speak, names[0], f"{player} vừa nhắc tới bạn hoặc nói với bạn. Hãy trả lời {player}.", to=player)
    elif last_bot["to"] == player and now - last_bot["time"] < 90:
        persona = next(p for p in PERSONAS if p["name"] == last_bot["name"])
        run(speak, persona, f"{player} vừa nói tiếp sau khi bạn nói với họ. Trả lời nếu họ đang nói với bạn, "
                            "để trống nếu họ đang nói với người khác.", to=player)
    elif random.random() < TUNE["chime_in_chance"]:
        run(speak, random.choice(PERSONAS), f"{player} vừa chat. Chỉ chen vào nếu bạn có câu thật sự hợp, "
                                            "còn không thì để trống.")


def on_join(player, joined):
    with lock:
        history.append(f"[{time.strftime('%H:%M')}] ({player} {'vào' if joined else 'rời'} server)")
        (online.add if joined else online.discard)(player)
    if joined and random.random() < TUNE["greet_chance"]:
        def greet():
            time.sleep(random.uniform(15, 40))
            speak(random.choice(PERSONAS), f"{player} vừa vào server. Chào {player} theo kiểu của bạn.", to=player)
        run(greet)


def follow_logs():
    while True:
        proc = subprocess.Popen(["docker", "logs", "-f", "--since", "1s", CONTAINER],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        for line in proc.stdout:
            line = line.rstrip("\n")
            if m := CHAT.match(line):
                on_chat(m.group(2), m.group(3))
            elif m := JOIN.match(line):
                on_join(m.group(2), m.group(3) == "joined")
        proc.wait()
        log("log stream ended, reconnecting")
        time.sleep(10)


def refresh_online():
    try:
        out = rcon("list")
    except Exception:
        return
    names = out.split(":", 1)[1] if ":" in out else ""
    with lock:
        online.clear()
        online.update(n.strip() for n in names.split(",") if n.strip())


def idle_loop():
    next_idle = random.uniform(*TUNE["idle_minutes"]) * 60
    while True:
        time.sleep(60)
        refresh_online()
        if online and time.time() - max(last_chat, last_bot["time"]) > next_idle:
            run(speak, random.choice(PERSONAS),
                "Chat im lặng một lúc rồi. Bắt chuyện tự nhiên: hỏi han ai đó, kể một ý về Pokémon, "
                "nhắc lại chuyện cũ bạn nhớ, hoặc rủ làm gì đó.")
            next_idle = random.uniform(*TUNE["idle_minutes"]) * 60


def main():
    load_state()
    refresh_online()
    log("started; online:", sorted(online))
    threading.Thread(target=idle_loop, daemon=True).start()
    follow_logs()


if __name__ == "__main__":
    main()
