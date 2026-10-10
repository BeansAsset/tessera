"""Just enough CBOR to read what a passkey hands over when it's created
(the attestation object and the public key inside it)."""


class CBORError(ValueError):
    pass


def decode(data):
    """Decode one CBOR item; returns (value, bytes used)."""
    value, end = _item(bytes(data), 0)
    return value, end


def loads(data):
    value, end = decode(data)
    if end != len(data):
        raise CBORError("trailing bytes")
    return value


def _length(data, pos, info):
    if info < 24:
        return info, pos
    size = {24: 1, 25: 2, 26: 4, 27: 8}.get(info)
    if size is None or pos + size > len(data):
        raise CBORError("bad length")
    return int.from_bytes(data[pos:pos + size], "big"), pos + size


def _item(data, pos, depth=0):
    if depth > 16:
        raise CBORError("nested too deeply")
    if pos >= len(data):
        raise CBORError("truncated")
    major, info = data[pos] >> 5, data[pos] & 0x1F
    pos += 1
    if major == 7:
        simple = {20: False, 21: True, 22: None}
        if info in simple:
            return simple[info], pos
        raise CBORError("unsupported simple value")
    n, pos = _length(data, pos, info)
    if major == 0:
        return n, pos
    if major == 1:
        return -1 - n, pos
    if major in (2, 3):
        if pos + n > len(data):
            raise CBORError("truncated")
        raw = data[pos:pos + n]
        return (raw if major == 2 else raw.decode("utf-8")), pos + n
    if major == 4:
        out = []
        for _ in range(n):
            v, pos = _item(data, pos, depth + 1)
            out.append(v)
        return out, pos
    if major == 5:
        out = {}
        for _ in range(n):
            k, pos = _item(data, pos, depth + 1)
            v, pos = _item(data, pos, depth + 1)
            out[k] = v
        return out, pos
    raise CBORError("unsupported type")
