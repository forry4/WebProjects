use orbit_core::{Chance, State};
use serde_json::json;

#[test]
fn all_boards_play_complete_and_conserve_inventory() {
    for seed in 0..128 {
        let sides = std::array::from_fn(|i| 1 + ((seed >> i) & 1) as i32);
        let (mut state, mut c) = State::new(seed, sides);
        let mut chooser = Chance::seeded(seed + 3181);
        for _ in 0..2000 {
            state.validate().unwrap();
            let Some(pid) = state.actor() else {
                break;
            };
            let moves = state.legal_moves(pid);
            assert!(!moves.is_empty());
            state
                .apply(pid, &moves[chooser.index(moves.len())], &mut c)
                .unwrap();
        }
        assert_eq!(state.phase, "over", "seed {seed}");
        state.validate().unwrap();
    }
}

#[test]
fn invalid_actions_are_atomic_and_state_roundtrips() {
    let (mut state, mut c) = State::new(19, [1, 2, 1]);
    let before = state.clone();
    assert!(state
        .apply(0, &json!({"action":"recruit","card_id":999}), &mut c)
        .is_err());
    assert!(state
        .apply(7, &json!({"action":"mulligan","card_ids":[]}), &mut c)
        .is_err());
    assert_eq!(state, before);
    let wire = serde_json::to_string(&state).unwrap();
    assert_eq!(state, serde_json::from_str::<State>(&wire).unwrap());
}

#[test]
fn mulligans_are_independent_and_keep_starting_seat() {
    let (mut state, mut c) = State::new(99, [1, 1, 1]);
    let mv = json!({"action":"mulligan","card_ids":[]});
    state.apply(1, &mv, &mut c).unwrap();
    assert!(state.legal_moves(1).is_empty());
    assert_eq!(state.legal_moves(0).len(), 16);
    state.apply(0, &mv, &mut c).unwrap();
    assert_eq!(state.turn_pid, Some(0));
    assert_eq!(state.turn_number, 1);
}

#[test]
fn observations_do_not_depend_on_unseen_hands_or_deck_order() {
    let (state, _) = State::new(15, [2, 1, 2]);
    let before = state.observation(0);
    let mut other = state.clone();
    std::mem::swap(&mut other.players[1].hand[0], &mut other.agent_deck[0]);
    other.agent_deck.reverse();
    other.bonus_deck.reverse();
    assert_eq!(before, other.observation(0));
    assert_ne!(state.observation(1), other.observation(1));
    other.phase = "over".into();
    assert!(other.observation(0)["players"][1].get("hand").is_none());
}
