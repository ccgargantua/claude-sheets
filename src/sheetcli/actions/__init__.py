from . import charts, core, data, formatting, query, structure

MODULES = (core, structure, formatting, data, query, charts)

HANDLERS = {}
for _m in MODULES:
    _dupes = HANDLERS.keys() & _m.HANDLERS.keys()
    if _dupes:
        raise RuntimeError(f"duplicate handlers: {sorted(_dupes)}")
    HANDLERS.update(_m.HANDLERS)
