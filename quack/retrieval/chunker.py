from quack import config


def _hard_split(piece: str, max_chars: int, overlap: int) -> list[str]:
    step = max_chars - overlap
    return [piece[start : start + max_chars] for start in range(0, len(piece), step)]


def chunk_text(text: str, max_chars: int | None = None, overlap: int | None = None) -> list[str]:
    max_chars = max_chars or config.CHUNK_MAX_CHARS
    overlap = config.CHUNK_OVERLAP_CHARS if overlap is None else overlap
    if overlap >= max_chars:
        raise ValueError("overlap must be smaller than max_chars")

    chunks: list[str] = []
    current = ""

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        if len(line) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_hard_split(line, max_chars, overlap))
            continue

        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > max_chars:
            chunks.append(current)
            current = line
        else:
            current = candidate

    if current:
        chunks.append(current)
    return chunks
