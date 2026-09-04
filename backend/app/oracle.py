import atexit
import os
import oracledb
from .config import get_settings
from langgraph.checkpoint.memory import MemorySaver

def create_pool():
    s = get_settings()
    if not all((s.oracle_user, s.oracle_password, s.oracle_dsn)):
        return None
    kwargs = {"user": s.oracle_user, "password": s.oracle_password, "dsn": s.oracle_dsn, "min": 1, "max": 4}
    if s.oracle_wallet_dir:
        # Autonomous Database aliases such as ``project1_medium`` live in the
        # wallet's tnsnames.ora, so the driver needs this as its config_dir too.
        kwargs.update(config_dir=s.oracle_wallet_dir, wallet_location=s.oracle_wallet_dir, wallet_password=s.oracle_wallet_password or None)
    return oracledb.create_pool(**kwargs)

_pool = None
_checkpointer = None
def get_pool():
    global _pool
    if _pool is None: _pool = create_pool()
    return _pool
def get_checkpointer():
    global _checkpointer
    if _checkpointer is not None: return _checkpointer
    s = get_settings()
    if not all((s.oracle_user, s.oracle_password, s.oracle_dsn)):
        _checkpointer = MemorySaver(); return _checkpointer
    try:
        from langgraph_oracledb.checkpoint.oracle import OracleSaver
        os.environ.setdefault("TNS_ADMIN", s.oracle_wallet_dir)
        _checkpointer = OracleSaver(get_pool())
        _checkpointer.setup()
        return _checkpointer
    except Exception as exc:
        raise RuntimeError(f"Oracle LangGraph checkpointer initialization failed: {exc}") from exc
