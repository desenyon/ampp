use crate::pipeline::normalizer::FormalSpec;
use crate::state::Subgoal;
use crate::store::ProofStore;
use anyhow::Result;

/// Builds and maintains a dependency DAG of subgoals.
pub struct Planner<'a> {
    store: &'a ProofStore,
}

impl<'a> Planner<'a> {
    pub fn new(store: &'a ProofStore) -> Self {
        Self { store }
    }

    /// Generate initial subgoals from a formal specification.
    /// Returns the IDs of inserted subgoals, ordered by priority.
    pub fn generate_initial_subgoals(
        &self,
        spec: &FormalSpec,
        target_claim_id: &str,
        branch_id: &str,
    ) -> Result<Vec<String>> {
        // The top-level subgoal always corresponds to the target claim.
        let top_sg = Subgoal::new(
            target_claim_id,
            100.0, // maximum impact
            0.8,
            vec![],
            "direct_proof",
            format!("Prove: {}", spec.target),
            branch_id,
        );

        // Add edge-case subgoals as auxiliary blockers.
        let mut ids = Vec::new();

        for (i, edge) in spec.edge_cases.iter().enumerate() {
            let edge_sg = Subgoal::new(
                target_claim_id,
                10.0 / (i + 1) as f64,
                0.2,
                vec![],
                "direct_proof",
                format!("Verify edge case: {edge}"),
                branch_id,
            );
            let edge_id = edge_sg.id.clone();
            self.store.insert_subgoal(&edge_sg)?;
            ids.push(edge_id);
        }

        let top_id = top_sg.id.clone();
        self.store.insert_subgoal(&top_sg)?;
        ids.push(top_id);

        Ok(ids)
    }

    /// Insert a single derived subgoal (e.g., from a proposer).
    pub fn add_subgoal(&self, subgoal: Subgoal) -> Result<String> {
        let id = subgoal.id.clone();
        self.store.insert_subgoal(&subgoal)?;
        Ok(id)
    }

    /// Return the highest-priority unresolved subgoal for a branch.
    pub fn next_subgoal(&self, branch_id: &str) -> Result<Option<Subgoal>> {
        let pending = self.store.get_pending_subgoals(branch_id)?;
        Ok(pending.into_iter().next())
    }

    /// Mark a subgoal as resolved.
    pub fn resolve(&self, subgoal_id: &str) -> Result<()> {
        self.store.resolve_subgoal(subgoal_id)
    }
}
