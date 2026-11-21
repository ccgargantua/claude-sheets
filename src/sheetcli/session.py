from .common import SheetError, fmt_of
from .document import backup_file, check_input_file, open_doc
from .uno_daemon import connection


def execute(args, handler):
    if handler.fn is None:
        raise SheetError(f"not implemented: {args.action}")
    if handler.free:
        return handler.fn(args)
    results, extra = run_ops(args.file, [(args, handler)],
                             getattr(args, "dry_run", False), getattr(args, "backup", False))
    return {**results[0], **extra}


def run_ops(path, ops, dry_run=False, backup=False, indexed=False):
    """Apply (args, handler) pairs to one open document and save once.
    Any failure aborts before saving, so nothing is written."""
    fmt = fmt_of(path)
    check_input_file(path)
    for i, (args, handler) in enumerate(ops):
        if handler.fn is None:
            raise _op_error(i, args, f"not implemented: {args.action}", indexed)
        if handler.rich and fmt == "csv":
            raise _op_error(i, args, "unsupported for csv", indexed)
    mutates = any(h.mutates for _, h in ops)
    extra = {"dry_run": True} if dry_run else {}
    with connection() as desktop, open_doc(desktop, path) as doc:
        results = []
        for i, (args, handler) in enumerate(ops):
            try:
                results.append(handler.fn(doc, args))
            except SheetError as e:
                raise _op_error(i, args, str(e), indexed) from e
            except Exception as e:
                raise _op_error(i, args, f"{type(e).__name__}: {e}", indexed) from e
        if mutates and not dry_run:
            if backup:
                extra["backup"] = backup_file(path)
            doc.save()
    return results, extra


def _op_error(index, args, message, indexed):
    if not indexed:
        return SheetError(message)
    return SheetError(f"op {index} ({args.action}): {message}", op=index, action=args.action)
