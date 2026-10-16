"""Hook formulas, a hook scorer and a title linter for Shorts. No AI calls.

Ported from https://github.com/Jakeschincariol/youtube-agent-skill (yt-script/hooks.json,
yt-script/hookscore.py, yt-package/title.py):

    MIT License. Copyright (c) 2026 Jake Schincariol. Permission is hereby granted, free of charge,
    to any person obtaining a copy of this software and associated documentation files, to deal in
    the Software without restriction, subject to including this notice.

The scorer is a heuristic, not a predictor: a low score is a reason to look again, a high score is
not a promise.
"""

from __future__ import annotations

import re

# 21 hook formulas: (name, shape).
FORMULAS = [
    ("The Statistic", "A number the viewer did not know, stated flat, then the consequence."),
    ("Someone Else's Result", "A named person's outcome, then the mechanism."),
    ("The Mistake", "Name the error the viewer is probably making right now."),
    ("Contrarian Flip", "State the accepted advice, then reject it."),
    ("The Reveal", "Promise a specific thing will be shown, then show it."),
    ("The Superlative", "The single best/worst/fastest of a category."),
    ("The Clock", "Bound the payoff in time."),
    ("I Tried It", "First-person experiment with a stated cost."),
    ("The Question", "Ask the exact question the viewer typed into search."),
    ("Before and After", "Two states, one cut between them."),
    ("The Teardown", "Take a real thing apart in public."),
    ("The Stack", "Two named tools combined into one outcome."),
    ("The Warning", "A cost the viewer is about to pay."),
    ("The List", "A counted set, with the count in the first line."),
    ("The Receipt", "Show the artifact first, explain second."),
    ("The Insider", "Information from inside a system."),
    ("The Impossible Claim", "State something that sounds untrue, then prove it."),
    ("The Comparison", "Two named options, one winner."),
    ("The Origin", "Where a result actually came from."),
    ("The Deadline", "Something is changing on a date."),
    ("The Direct Address", "Name the exact viewer in the first six words."),
]
FORMULA_NAMES = {name for name, _ in FORMULAS}

FILLER = {"basically", "actually", "literally", "just", "really", "very", "so", "kind", "sort", "like",
          "guys", "hey", "welcome", "today", "video", "subscribe", "channel"}
VAGUE = {"amazing", "incredible", "insane", "crazy", "huge", "massive", "game", "changer", "secret",
         "powerful", "ultimate", "best", "revolutionary", "mind", "blowing", "unbelievable"}
CONCRETE = re.compile(r"\b(\d[\d,.]*\s?(%|k|m|x|s|m|h)?|\$\d|\d+\s?(second|minute|hour|day|week|month|year)s?)\b", re.I)
YOU = re.compile(r"\b(you|your|you're|youre|yourself)\b", re.I)
STAKE = re.compile(r"\b(lose|lost|wasting|waste|quit|fail|broke|cost|risk|before|stop|never|die|dying|dead)\b", re.I)
CURIOSITY = re.compile(r"\b(why|how|what|which|until|before|but|nobody|almost|except|reason|actually)\b", re.I)
FIX = {
    "specificity": "Swap one vague word for a number, a name or a date.",
    "address": "Say \"you\" in the first six words.",
    "stakes": "Say what it costs the viewer to keep doing it the current way.",
    "curiosity": "Cut the half of the sentence that answers itself.",
    "brevity": "Keep it to 9-24 words.",
}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9'%$.]+", text.lower())


def _specificity(t: str) -> int:
    w = _words(t)
    if not w:
        return 0
    s = 34 + len(CONCRETE.findall(t)) * 22 - sum(x in VAGUE for x in w) * 16 - sum(x in FILLER for x in w) * 5
    s += min(18, 6 * sum(1 for x in t.split()[1:] if x[:1].isupper()))  # named things
    return max(0, min(100, s))


def _address(t: str) -> int:
    first = 30 if YOU.search(" ".join(t.split()[:6])) else 0
    return max(0, min(100, 26 + len(YOU.findall(t)) * 20 + first))


def _stakes(t: str) -> int:
    return max(0, min(100, 22 + len(STAKE.findall(t)) * 26 + (14 if CONCRETE.search(t) else 0)))


def _curiosity(t: str) -> int:
    q = 18 if t.strip().endswith("?") else 0
    closed = -18 if re.search(r"\b(because|so that|which means)\b", t, re.I) else 0  # answers itself
    return max(0, min(100, 24 + len(CURIOSITY.findall(t)) * 17 + q + closed))


def _brevity(t: str) -> int:
    n = len(_words(t))
    if n == 0:
        return 0
    if 9 <= n <= 24:
        return 100
    return max(30, 100 - (9 - n) * 11) if n < 9 else max(10, 100 - (n - 24) * 7)


def score_hook(hook: str) -> dict:
    """{"score": 0-100, "band": STRONG|WORKABLE|WEAK, "weakest", "fix"}: 60% mean + 40% weakest."""
    parts = {"specificity": _specificity(hook), "address": _address(hook), "stakes": _stakes(hook),
             "curiosity": _curiosity(hook), "brevity": _brevity(hook)}
    score = round(0.6 * sum(parts.values()) / len(parts) + 0.4 * min(parts.values()))
    weakest = min(parts, key=parts.get)
    # Calibrated on real hooks: good ones score about 42-55, generic openers 20-36.
    band = "STRONG" if score >= 50 else "WORKABLE" if score >= 40 else "WEAK"
    return {"score": score, "band": band, "weakest": weakest, "fix": FIX[weakest]}


TITLE_STOP = {"the", "a", "an", "of", "for", "to", "in", "on", "and", "or", "is", "are", "with", "your", "you",
              "my", "i", "this", "that", "it", "how", "what", "why"}
TITLE_VAGUE = {"amazing", "incredible", "insane", "crazy", "huge", "massive", "ultimate", "best", "powerful",
               "secret", "revolutionary", "mindblowing", "epic", "perfect", "complete", "everything"}


def lint_title(title: str, thumb: str = "") -> list[str]:
    """Plain-language problems with a title + thumbnail-text pairing (empty list = looks good)."""
    t = title.strip()
    issues = []
    if len(t) > 60:
        issues.append(f"{len(t)} characters: search results cut titles near 60.")
    elif len(t) > 40:
        issues.append(f"Phones show about the first 40 characters: \"{t[:40].rsplit(' ', 1)[0]}…\". Check the subject is in there.")
    if len([w for w in t.split() if len(w) > 2 and w.isupper()]) > 2:
        issues.append("More than two ALL-CAPS words reads as spam.")
    vague = sorted({w for w in re.findall(r"[a-z0-9']+", t.lower()) if w in TITLE_VAGUE})
    if vague:
        issues.append(f"Vague word ({', '.join(vague)}): swap it for a number, a name or a date.")
    if not [w for w in re.findall(r"[a-z0-9']+", t.lower())[:3] if w not in TITLE_STOP]:
        issues.append("The first three words are filler: move the subject forward.")
    if thumb:
        shared = (set(re.findall(r"[a-z0-9']+", t.lower())) & set(re.findall(r"[a-z0-9']+", thumb.lower()))) - TITLE_STOP
        if shared:
            issues.append(f"The thumbnail repeats the title ({', '.join(sorted(shared))}): it should say what the title doesn't.")
        if len(thumb.split()) > 4:
            issues.append("Thumbnail text over 4 words is hard to read in the feed.")
    return issues


if __name__ == "__main__":  # quick self-check
    weak, strong = score_hook("Today we talk about coffee."), score_hook("Your espresso is lying to you: crema can hide a stale bean in 25 seconds.")
    assert weak["score"] < strong["score"], (weak, strong)
    assert (weak["band"], strong["band"]) == ("WEAK", "WORKABLE"), (weak, strong)
    assert len(FORMULAS) == 21
    assert lint_title("Why crema forms", "BUBBLE MAGIC") == []
    assert any("repeats" in i for i in lint_title("Why crema forms", "CREMA"))
    print("ok", weak, strong)
