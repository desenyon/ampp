use anyhow::Result;
use rusqlite::{params, Connection};
use std::path::Path;

use crate::state::{Attempt, Claim, Counterexample, Definition, Subgoal};

/// Append-only, versioned SQLite store for the proof state.
pub struct ProofStore {
    conn: Connection,
}

impl ProofStore {
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let conn = Connection::open(path)?;
        let store = Self { conn };
        store.init_schema()?;
        Ok(store)
    }

    pub fn in_memory() -> Result<Self> {
        let conn = Connection::open_in_memory()?;
        let store = Self { conn };
        store.init_schema()?;
        Ok(store)
    }

    fn init_schema(&self) -> Result<()> {
        self.conn.execute_batch(
            r#"
            PRAGMA journal_mode = WAL;
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS definitions (
                id          TEXT PRIMARY KEY,
                data        TEXT NOT NULL,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS claims (
                id          TEXT PRIMARY KEY,
                branch_id   TEXT NOT NULL,
                status      TEXT NOT NULL,
                proof_hash  TEXT NOT NULL,
                data        TEXT NOT NULL,
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_claims_status   ON claims(status);
            CREATE INDEX IF NOT EXISTS idx_claims_branch   ON claims(branch_id);
            CREATE INDEX IF NOT EXISTS idx_claims_hash     ON claims(proof_hash);

            CREATE TABLE IF NOT EXISTS subgoals (
                id          TEXT PRIMARY KEY,
                branch_id   TEXT NOT NULL,
                resolved    INTEGER NOT NULL DEFAULT 0,
                rank        REAL NOT NULL,
                data        TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_subgoals_branch ON subgoals(branch_id);

            CREATE TABLE IF NOT EXISTS counterexamples (
                id          TEXT PRIMARY KEY,
                claim_id    TEXT NOT NULL,
                data        TEXT NOT NULL,
                FOREIGN KEY(claim_id) REFERENCES claims(id)
            );

            CREATE TABLE IF NOT EXISTS attempts (
                id              TEXT PRIMARY KEY,
                branch_id       TEXT NOT NULL,
                failed_claim_id TEXT NOT NULL,
                verifier_stage  TEXT NOT NULL,
                data            TEXT NOT NULL,
                timestamp       TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_attempts_branch ON attempts(branch_id);
            CREATE INDEX IF NOT EXISTS idx_attempts_stage  ON attempts(verifier_stage);

            CREATE TABLE IF NOT EXISTS rejected_hashes (
                hash    TEXT PRIMARY KEY
            );
            "#,
        )?;
        Ok(())
    }

    // ── Definitions ──────────────────────────────────────────────────────────

    pub fn insert_definition(&self, def: &Definition) -> Result<()> {
        let data = serde_json::to_string(def)?;
        self.conn.execute(
            "INSERT OR IGNORE INTO definitions (id, data) VALUES (?1, ?2)",
            params![def.id, data],
        )?;
        Ok(())
    }

    pub fn get_all_definitions(&self) -> Result<Vec<Definition>> {
        let mut stmt = self.conn.prepare("SELECT data FROM definitions")?;
        let rows = stmt.query_map([], |row| row.get::<_, String>(0))?;
        rows.map(|r| Ok(serde_json::from_str(&r?)?))
            .collect::<Result<_>>()
    }

    // ── Claims ───────────────────────────────────────────────────────────────

    pub fn insert_claim(&self, claim: &Claim) -> Result<()> {
        let data = serde_json::to_string(claim)?;
        self.conn.execute(
            "INSERT INTO claims (id, branch_id, status, proof_hash, data) VALUES (?1,?2,?3,?4,?5)",
            params![
                claim.id,
                claim.branch_id,
                serde_json::to_string(&claim.status)?,
                claim.proof_hash,
                data
            ],
        )?;
        Ok(())
    }

    pub fn update_claim(&self, claim: &Claim) -> Result<()> {
        let data = serde_json::to_string(claim)?;
        self.conn.execute(
            "UPDATE claims SET status=?1, data=?2, updated_at=datetime('now') WHERE id=?3",
            params![serde_json::to_string(&claim.status)?, data, claim.id],
        )?;
        Ok(())
    }

    pub fn get_claim(&self, id: &str) -> Result<Option<Claim>> {
        let mut stmt = self.conn.prepare("SELECT data FROM claims WHERE id = ?1")?;
        let mut rows = stmt.query(params![id])?;
        if let Some(row) = rows.next()? {
            let data: String = row.get(0)?;
            Ok(Some(serde_json::from_str(&data)?))
        } else {
            Ok(None)
        }
    }

    pub fn get_verified_claims(&self, branch_id: &str) -> Result<Vec<Claim>> {
        let mut stmt = self
            .conn
            .prepare(r#"SELECT data FROM claims WHERE branch_id=?1 AND status='"verified"'"#)?;
        let rows = stmt.query_map(params![branch_id], |row| row.get::<_, String>(0))?;
        rows.map(|r| Ok(serde_json::from_str(&r?)?))
            .collect::<Result<_>>()
    }

    pub fn get_all_claims_for_branch(&self, branch_id: &str) -> Result<Vec<Claim>> {
        let mut stmt = self
            .conn
            .prepare("SELECT data FROM claims WHERE branch_id=?1")?;
        let rows = stmt.query_map(params![branch_id], |row| row.get::<_, String>(0))?;
        rows.map(|r| Ok(serde_json::from_str(&r?)?))
            .collect::<Result<_>>()
    }

    pub fn claim_hash_rejected(&self, hash: &str) -> Result<bool> {
        let count: i64 = self.conn.query_row(
            "SELECT COUNT(*) FROM rejected_hashes WHERE hash=?1",
            params![hash],
            |row| row.get(0),
        )?;
        Ok(count > 0)
    }

    pub fn register_rejected_hash(&self, hash: &str) -> Result<()> {
        self.conn.execute(
            "INSERT OR IGNORE INTO rejected_hashes (hash) VALUES (?1)",
            params![hash],
        )?;
        Ok(())
    }

    // ── Subgoals ─────────────────────────────────────────────────────────────

    pub fn insert_subgoal(&self, sg: &Subgoal) -> Result<()> {
        let data = serde_json::to_string(sg)?;
        self.conn.execute(
            "INSERT INTO subgoals (id, branch_id, resolved, rank, data) VALUES (?1,?2,?3,?4,?5)",
            params![sg.id, sg.branch_id, sg.resolved as i32, sg.rank(), data],
        )?;
        Ok(())
    }

    pub fn resolve_subgoal(&self, id: &str) -> Result<()> {
        self.conn
            .execute("UPDATE subgoals SET resolved=1 WHERE id=?1", params![id])?;
        Ok(())
    }

    /// Returns unresolved subgoals for a branch, ordered by rank DESC.
    pub fn get_pending_subgoals(&self, branch_id: &str) -> Result<Vec<Subgoal>> {
        let mut stmt = self.conn.prepare(
            "SELECT data FROM subgoals WHERE branch_id=?1 AND resolved=0 ORDER BY rank DESC",
        )?;
        let rows = stmt.query_map(params![branch_id], |row| row.get::<_, String>(0))?;
        rows.map(|r| Ok(serde_json::from_str(&r?)?))
            .collect::<Result<_>>()
    }

    pub fn count_pending_subgoals(&self, branch_id: &str) -> Result<i64> {
        Ok(self.conn.query_row(
            "SELECT COUNT(*) FROM subgoals WHERE branch_id=?1 AND resolved=0",
            params![branch_id],
            |row| row.get(0),
        )?)
    }

    // ── Counterexamples ───────────────────────────────────────────────────────

    pub fn insert_counterexample(&self, cx: &Counterexample) -> Result<()> {
        let data = serde_json::to_string(cx)?;
        self.conn.execute(
            "INSERT INTO counterexamples (id, claim_id, data) VALUES (?1,?2,?3)",
            params![cx.id, cx.claim_id, data],
        )?;
        Ok(())
    }

    pub fn get_counterexamples_for_claim(&self, claim_id: &str) -> Result<Vec<Counterexample>> {
        let mut stmt = self
            .conn
            .prepare("SELECT data FROM counterexamples WHERE claim_id=?1")?;
        let rows = stmt.query_map(params![claim_id], |row| row.get::<_, String>(0))?;
        rows.map(|r| Ok(serde_json::from_str(&r?)?))
            .collect::<Result<_>>()
    }

    // ── Attempts ─────────────────────────────────────────────────────────────

    pub fn insert_attempt(&self, attempt: &Attempt) -> Result<()> {
        let data = serde_json::to_string(attempt)?;
        self.conn.execute(
            "INSERT INTO attempts (id, branch_id, failed_claim_id, verifier_stage, data, timestamp) VALUES (?1,?2,?3,?4,?5,?6)",
            params![
                attempt.id,
                attempt.branch_id,
                attempt.failed_claim_id,
                attempt.verifier_stage.to_string(),
                data,
                attempt.timestamp.to_rfc3339()
            ],
        )?;
        Ok(())
    }

    pub fn get_attempts_for_branch(&self, branch_id: &str) -> Result<Vec<Attempt>> {
        let mut stmt = self
            .conn
            .prepare("SELECT data FROM attempts WHERE branch_id=?1 ORDER BY timestamp ASC")?;
        let rows = stmt.query_map(params![branch_id], |row| row.get::<_, String>(0))?;
        rows.map(|r| Ok(serde_json::from_str(&r?)?))
            .collect::<Result<_>>()
    }

    /// Failure count per verifier stage for a branch (used by RubricAgent).
    pub fn failure_counts_by_stage(
        &self,
        branch_id: &str,
    ) -> Result<std::collections::HashMap<String, i64>> {
        let mut stmt = self.conn.prepare(
            "SELECT verifier_stage, COUNT(*) FROM attempts WHERE branch_id=?1 GROUP BY verifier_stage",
        )?;
        let rows = stmt.query_map(params![branch_id], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, i64>(1)?))
        })?;
        let mut map = std::collections::HashMap::new();
        for r in rows {
            let (stage, count) = r?;
            map.insert(stage, count);
        }
        Ok(map)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::state::{Claim, ClaimStatus, ClaimType};

    #[test]
    fn test_claim_roundtrip() {
        let store = ProofStore::in_memory().unwrap();
        let claim = Claim::new(
            "For all n > 1, n has a prime divisor.",
            ClaimType::Lemma,
            vec![],
            "branch-1",
        );
        store.insert_claim(&claim).unwrap();
        let retrieved = store.get_claim(&claim.id).unwrap().unwrap();
        assert_eq!(retrieved.statement, claim.statement);
        assert_eq!(retrieved.status, ClaimStatus::Proposed);
    }

    #[test]
    fn test_rejected_hash_tracking() {
        let store = ProofStore::in_memory().unwrap();
        let hash = "aabbcc";
        assert!(!store.claim_hash_rejected(hash).unwrap());
        store.register_rejected_hash(hash).unwrap();
        assert!(store.claim_hash_rejected(hash).unwrap());
    }

    #[test]
    fn test_subgoal_ordering_by_rank() {
        let store = ProofStore::in_memory().unwrap();
        let sg_low = Subgoal::new(
            "claim-1",
            1.0,
            0.9,
            vec![],
            "induction",
            "check V1",
            "branch-1",
        );
        let sg_high = Subgoal::new(
            "claim-2",
            10.0,
            0.5,
            vec![],
            "extremal",
            "check V2",
            "branch-1",
        );
        store.insert_subgoal(&sg_low).unwrap();
        store.insert_subgoal(&sg_high).unwrap();
        let pending = store.get_pending_subgoals("branch-1").unwrap();
        // sg_high has rank 20, sg_low has rank ~1.11
        assert_eq!(pending[0].id, sg_high.id);
    }
}
