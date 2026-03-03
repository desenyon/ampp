use crate::state::StrategyFamily;
use crate::store::ProofStore;
use anyhow::Result;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// A single beam state representing one active proof exploration branch.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BeamState {
    pub branch_id: String,
    /// Primary strategy family used in this branch.
    pub strategy_family: StrategyFamily,
    /// Number of verified claims on this branch (monotone increasing).
    pub verified_count: usize,
    /// How many subgoals have been resolved.
    pub subgoals_resolved: usize,
    /// Iterations without progress before forcing strategy switch.
    pub stale_iterations: usize,
    /// Whether this branch has been pruned.
    pub pruned: bool,
}

impl BeamState {
    pub fn new(strategy_family: StrategyFamily) -> Self {
        Self {
            branch_id: Uuid::new_v4().to_string(),
            strategy_family,
            verified_count: 0,
            subgoals_resolved: 0,
            stale_iterations: 0,
            pruned: false,
        }
    }

    /// Composite ranking score (higher = more promising).
    pub fn score(&self) -> f64 {
        let progress = (self.verified_count as f64) * 2.0 + (self.subgoals_resolved as f64);
        let staleness_penalty = (self.stale_iterations as f64) * 0.5;
        progress - staleness_penalty
    }
}

/// Manages 3–6 active beam states.
/// Prevents beam collapse into near-duplicate strategies (diversity enforcement).
pub struct BeamSearchManager {
    pub states: Vec<BeamState>,
    /// Maximum beam width.
    max_width: usize,
    /// Minimum beam width (never drop below this).
    min_width: usize,
}

impl BeamSearchManager {
    /// Initialise the beam with one state per initial strategy family.
    pub fn new(initial_strategies: Vec<StrategyFamily>) -> Self {
        let states: Vec<BeamState> = initial_strategies
            .into_iter()
            .map(BeamState::new)
            .collect();
        let _width = states.len().clamp(3, 6);
        Self {
            states,
            max_width: 6,
            min_width: 3,
        }
    }

    /// Return the top-K beam states by score, excluding pruned ones.
    pub fn top_states(&self, k: usize) -> Vec<&BeamState> {
        let mut active: Vec<&BeamState> = self.states.iter().filter(|s| !s.pruned).collect();
        active.sort_by(|a, b| b.score().partial_cmp(&a.score()).unwrap());
        active.truncate(k);
        active
    }

    /// Mark progress on a branch (resets staleness).
    pub fn record_progress(&mut self, branch_id: &str, new_verified: usize, new_resolved: usize) {
        if let Some(s) = self.states.iter_mut().find(|s| s.branch_id == branch_id) {
            s.verified_count += new_verified;
            s.subgoals_resolved += new_resolved;
            s.stale_iterations = 0;
        }
    }

    /// Increment stale counter for a branch; if it exceeds threshold, prune.
    pub fn record_stale(&mut self, branch_id: &str, threshold: usize) -> bool {
        let active = self.states.iter().filter(|s| !s.pruned).count();
        if let Some(s) = self.states.iter_mut().find(|s| s.branch_id == branch_id) {
            s.stale_iterations += 1;
            if s.stale_iterations >= threshold && active > self.min_width {
                s.pruned = true;
                tracing::info!(branch_id = %branch_id, "Beam state pruned due to staleness");
                return true;
            }
        }
        false
    }

    pub fn active_count(&self) -> usize {
        self.states.iter().filter(|s| !s.pruned).count()
    }

    /// Expand the beam with a new strategy, enforcing diversity and max width.
    pub fn expand(&mut self, strategy: StrategyFamily) -> Option<String> {
        if self.active_count() >= self.max_width {
            return None;
        }
        // Diversity: don't add if same strategy already active
        let already_present = self
            .states
            .iter()
            .filter(|s| !s.pruned)
            .any(|s| s.strategy_family == strategy);
        if already_present {
            return None;
        }
        let state = BeamState::new(strategy);
        let id = state.branch_id.clone();
        self.states.push(state);
        Some(id)
    }

    /// Synchronise verified/subgoal counts from the store.
    pub fn sync_from_store(&mut self, store: &ProofStore) -> Result<()> {
        for state in &mut self.states {
            if state.pruned {
                continue;
            }
            let verified = store.get_verified_claims(&state.branch_id)?;
            let pending = store.count_pending_subgoals(&state.branch_id)?;
            state.verified_count = verified.len();
            // resolved = total inserted - still pending (approx)
            state.subgoals_resolved = state
                .subgoals_resolved
                .max(state.verified_count.saturating_sub(pending as usize));
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_initial_beam_width() {
        let manager = BeamSearchManager::new(vec![
            StrategyFamily::Induction,
            StrategyFamily::ExtremalPrinciple,
            StrategyFamily::DoubleCounting,
        ]);
        assert_eq!(manager.active_count(), 3);
    }

    #[test]
    fn test_diversity_enforcement() {
        let mut manager = BeamSearchManager::new(vec![
            StrategyFamily::Induction,
            StrategyFamily::ExtremalPrinciple,
            StrategyFamily::DoubleCounting,
        ]);
        // Should not add duplicate
        let id = manager.expand(StrategyFamily::Induction);
        assert!(id.is_none());
        // Should add novel strategy
        let id = manager.expand(StrategyFamily::Constructive);
        assert!(id.is_some());
        assert_eq!(manager.active_count(), 4);
    }

    #[test]
    fn test_staleness_pruning() {
        let mut manager = BeamSearchManager::new(vec![
            StrategyFamily::Induction,
            StrategyFamily::ExtremalPrinciple,
            StrategyFamily::DoubleCounting,
            StrategyFamily::Constructive,
        ]);
        let branch = manager.states[0].branch_id.clone();
        for _ in 0..5 {
            manager.record_stale(&branch, 5);
        }
        assert!(manager.states[0].pruned);
        assert_eq!(manager.active_count(), 3); // still at min
    }

    #[test]
    fn test_score_ordering() {
        let mut manager = BeamSearchManager::new(vec![
            StrategyFamily::Induction,
            StrategyFamily::ExtremalPrinciple,
            StrategyFamily::DoubleCounting,
        ]);
        manager.record_progress(&manager.states[1].branch_id.clone(), 5, 3);
        let top = manager.top_states(1);
        assert_eq!(top[0].branch_id, manager.states[1].branch_id);
    }
}
