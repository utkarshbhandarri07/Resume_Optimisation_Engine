"""Apply the Oracle application schema once: python migrate.py"""
from pathlib import Path
import oracledb
from app.config import get_settings

def main():
    s=get_settings()
    if not all((s.oracle_user,s.oracle_password,s.oracle_dsn)): raise SystemExit("Set ORACLE_USER, ORACLE_PASSWORD, and ORACLE_DSN in backend/.env")
    kwargs={"user":s.oracle_user,"password":s.oracle_password,"dsn":s.oracle_dsn}
    if s.oracle_wallet_dir: kwargs.update(wallet_location=s.oracle_wallet_dir,wallet_password=s.oracle_wallet_password or None)
    with oracledb.connect(**kwargs) as con:
        with con.cursor() as cur:
            cur.execute("BEGIN EXECUTE IMMEDIATE 'CREATE TABLE ro_migrations (version VARCHAR2(40) PRIMARY KEY, applied_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL)'; EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF; END;")
            sql=Path(__file__).with_name("oracle_schema.sql").read_text(encoding="utf-8")
            sql="\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))
            for statement in (x.strip() for x in sql.split(";") if x.strip()):
                try: cur.execute(statement)
                except oracledb.DatabaseError as exc:
                    if "ORA-00955" not in str(exc) and "ORA-01408" not in str(exc): raise
            cur.execute("MERGE INTO ro_migrations m USING (SELECT '001_resume_optimizer' version FROM dual) x ON (m.version=x.version) WHEN NOT MATCHED THEN INSERT (version) VALUES (x.version)")
        con.commit()
if __name__=="__main__": main()
