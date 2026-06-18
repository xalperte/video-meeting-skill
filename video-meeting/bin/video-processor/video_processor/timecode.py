"""Parse and format video timecodes.

Mirrors ``extract_frames.parse_timestamp`` rules so output feeds that pipeline:
one ':' is mm:ss, two is hh:mm:ss, a bare value is seconds. A leading 'sec'
prefix (UI convenience) is stripped to a bare number.
"""


def parse_timecode(value):
    """'mm:ss' | 'hh:mm:ss' | bare seconds | 'sec N' -> float seconds.

    Raises ValueError on empty, malformed, or negative input.
    """
    s = str(value).strip()
    if not s:
        raise ValueError("empty timecode")
    if s.lower().startswith("sec"):
        s = s[3:].strip()
        if not s:
            raise ValueError("empty timecode after 'sec'")
    parts = s.split(":")
    if len(parts) > 3:
        raise ValueError("too many ':' in timecode: %r" % value)
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        raise ValueError("non-numeric timecode: %r" % value)
    if any(n < 0 for n in nums):
        raise ValueError("negative timecode: %r" % value)
    if len(parts) == 1:
        secs = nums[0]
    elif len(parts) == 2:
        secs = nums[0] * 60 + nums[1]
    else:
        secs = nums[0] * 3600 + nums[1] * 60 + nums[2]
    return float(secs)


def format_timecode(seconds):
    """float seconds -> 'mm:ss.mmm', or 'hh:mm:ss.mmm' when >= 1 hour.

    Seconds are rounded to the nearest millisecond, so the full sub-second
    precision of ``seconds`` is shown (e.g. 130.5 -> '02:10.500'). Rounding
    carries correctly across second/minute/hour boundaries.
    """
    if seconds < 0:
        raise ValueError("negative seconds")
    ms_total = round(seconds * 1000)
    h, rem = divmod(ms_total, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    if h:
        return "%02d:%02d:%02d.%03d" % (h, m, s, ms)
    return "%02d:%02d.%03d" % (m, s, ms)
