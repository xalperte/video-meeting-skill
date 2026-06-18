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
    """float seconds -> 'mm:ss', or 'hh:mm:ss' when >= 1 hour.

    Fractional seconds are dropped to whole seconds for display.
    """
    if seconds < 0:
        raise ValueError("negative seconds")
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%02d:%02d:%02d" % (h, m, s)
    return "%02d:%02d" % (m, s)
