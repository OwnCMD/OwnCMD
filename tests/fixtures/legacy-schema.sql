-- Exact legacy schema extracted from the supplied installer for migration tests only.
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL,created REAL NOT NULL);
  CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,owner TEXT NOT NULL REFERENCES users(id),csrf TEXT NOT NULL,expires REAL NOT NULL);
  CREATE TABLE IF NOT EXISTS limits(bucket TEXT PRIMARY KEY,n INTEGER NOT NULL,until REAL NOT NULL);
  CREATE TABLE IF NOT EXISTS memory(id TEXT PRIMARY KEY,owner TEXT NOT NULL REFERENCES users(id),body TEXT NOT NULL,created REAL NOT NULL);
  CREATE INDEX IF NOT EXISTS memory_owner ON memory(owner);
  CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,owner TEXT NOT NULL REFERENCES users(id),title TEXT NOT NULL,state TEXT NOT NULL,status TEXT NOT NULL,mode TEXT NOT NULL DEFAULT 'work',control TEXT NOT NULL DEFAULT 'ai',lease REAL NOT NULL DEFAULT 0,version INTEGER NOT NULL DEFAULT 0,busy REAL NOT NULL DEFAULT 0,control_epoch INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL,updated REAL NOT NULL);
  CREATE INDEX IF NOT EXISTS tasks_owner ON tasks(owner,created);
  CREATE INDEX IF NOT EXISTS tasks_queue ON tasks(status,lease,created);
  CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,task TEXT NOT NULL REFERENCES tasks(id),kind TEXT NOT NULL,body TEXT NOT NULL,created REAL NOT NULL);
  CREATE INDEX IF NOT EXISTS events_task ON events(task,id);
  CREATE TABLE IF NOT EXISTS schedules(id TEXT PRIMARY KEY,owner TEXT NOT NULL REFERENCES users(id),prompt TEXT NOT NULL,next REAL NOT NULL,interval INTEGER NOT NULL,enabled INTEGER NOT NULL DEFAULT 1);
  CREATE TABLE IF NOT EXISTS previews(token TEXT PRIMARY KEY,task TEXT NOT NULL REFERENCES tasks(id),owner TEXT NOT NULL,expires REAL NOT NULL);
  CREATE TABLE IF NOT EXISTS ledger(id TEXT PRIMARY KEY,owner TEXT NOT NULL,task TEXT NOT NULL,amount REAL NOT NULL,status TEXT NOT NULL,created REAL NOT NULL);
  CREATE INDEX IF NOT EXISTS ledger_owner ON ledger(owner,created);
  CREATE TABLE IF NOT EXISTS connector(id TEXT PRIMARY KEY,owner TEXT NOT NULL,name TEXT NOT NULL,url TEXT NOT NULL,secret TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS preferences(owner TEXT PRIMARY KEY REFERENCES users(id),body TEXT NOT NULL,updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS credit_transactions(
  id TEXT PRIMARY KEY,owner TEXT NOT NULL,operation TEXT UNIQUE,kind TEXT NOT NULL,
  delta_nano INTEGER NOT NULL,created REAL NOT NULL);
 CREATE INDEX IF NOT EXISTS credit_owner ON credit_transactions(owner,created);
 CREATE TABLE IF NOT EXISTS usage_operations(
  id TEXT PRIMARY KEY,owner TEXT NOT NULL,task TEXT NOT NULL,service TEXT NOT NULL,
  model TEXT NOT NULL DEFAULT '',status TEXT NOT NULL,hold_nano INTEGER NOT NULL,
  cost_nano INTEGER,charge_nano INTEGER,provider_id TEXT,metadata TEXT NOT NULL DEFAULT '{}',
  created REAL NOT NULL,updated REAL NOT NULL);
 CREATE INDEX IF NOT EXISTS usage_owner ON usage_operations(owner,created);
 CREATE UNIQUE INDEX IF NOT EXISTS usage_provider ON usage_operations(service,provider_id)
  WHERE provider_id IS NOT NULL AND provider_id<>'';
 CREATE TRIGGER IF NOT EXISTS welcome_credit AFTER INSERT ON users BEGIN
  INSERT OR IGNORE INTO credit_transactions VALUES('welcome:'||NEW.id,NEW.id,NULL,'welcome_credit',10000000000,CAST(strftime('%s','now') AS REAL));
 END;
 CREATE TABLE IF NOT EXISTS usage_adjustments(id TEXT PRIMARY KEY,operation TEXT NOT NULL,old_cost_nano INTEGER,new_cost_nano INTEGER NOT NULL,reference TEXT NOT NULL,created REAL NOT NULL);
 CREATE TABLE IF NOT EXISTS runtime_meters(
  name TEXT PRIMARY KEY,task TEXT NOT NULL,kind TEXT NOT NULL,operation TEXT NOT NULL,
  started REAL NOT NULL,expires REAL NOT NULL,rate TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS personal_details(owner TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,body TEXT NOT NULL,version INTEGER NOT NULL,updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS schedule_settings(id TEXT PRIMARY KEY REFERENCES schedules(id) ON DELETE CASCADE,body TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,updated REAL NOT NULL,blocked TEXT NOT NULL DEFAULT '');
 CREATE TABLE IF NOT EXISTS scheduled_runs(id TEXT PRIMARY KEY,schedule TEXT NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,owner TEXT NOT NULL,task TEXT UNIQUE,due REAL NOT NULL,created REAL NOT NULL,status TEXT NOT NULL,reason TEXT NOT NULL DEFAULT '',UNIQUE(schedule,due));
 CREATE INDEX IF NOT EXISTS scheduled_runs_schedule ON scheduled_runs(schedule,created);
CREATE TABLE IF NOT EXISTS browser_profiles(owner TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, body TEXT NOT NULL, updated REAL NOT NULL);
