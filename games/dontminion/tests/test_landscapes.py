"""THE LANDSCAPE KERNEL (phase 6H) — the seams no shipped card consumes yet.

6H is hardening, in the 3H/5H mold: it changes no card and no game we can play
today. `cards.LANDSCAPES` is EMPTY, so there is nothing on any board to buy, no
Reserve to call, and no token to place. Every claim it makes is therefore about
behaviour that first arrives in phase 7 (Adventures: 20 Events, 9 Reserves, 6
token Events) — and "the existing suite still passes" only proves the refactor
changed nothing, which is half the job. The other half is that the thing it was
built for works.

So these drive the unconsumed seams end to end against the real kernel, using
landscapes and a Reserve invented here:

  * a LANDSCAPE is not a card and not a pile — the Knights lesson in reverse;
  * `buy_landscape` spends a Buy and money, is NOT a gain, and reads the
    PRINTED cost ("its cost cannot be changed by cards like Bridge", p32);
  * the TAVERN mat + calling, which is explicitly not playing (p28);
  * `before_play` (generalized from ph. 6's `play_attack`) and the new
    `action_resolved` continuation-emit;
  * Adventures TOKEN storage and the -$2 cost hook.

Two things are pinned elsewhere on purpose. Urchin's existing suite in
`test_cards_darkages_a.py` is the byte-identical net under the `before_play`
generalization — it must pass UNCHANGED. And `test_migrate.py` owns the v10
save shape.
"""

import copy
import json

import pytest

from games.dontminion import bot, cards, effects, engine

A, B = "alice", "bob"
K10 = ["Smithy", "Village", "Moat", "Militia", "Witch", "Throne Room",
       "Gardens", "Market", "Cellar", "Festival"]

# The synthetic landscapes. Real shapes, invented names — nothing in cards.py
# changes, and the day Adventures lands these paths are already exercised.
LS = {
    "Almsgiving": {"kind": "event", "cost": 0, "expansion": "base",
                   "once": "turn", "text": "Once per turn: +1 Buy."},
    "Bequest": {"kind": "event", "cost": 3, "expansion": "base",
                "once": "game", "text": "Once per game: +$2."},
    "Errand": {"kind": "event", "cost": 2, "expansion": "base",
               "text": "+1 Buy."},
    "Byway": {"kind": "way", "cost": 0, "expansion": "base",
              "text": "You may play an Action as if it were a Village."},
    # ph. 7H: the LANDMARK kind, framed since 6H and wired now. A landmark is
    # never bought — its ability is simply on, for everyone, all game.
    "Cairn": {"kind": "landmark", "cost": 0, "expansion": "base",
              "text": "When scoring, 2 VP per 3 Estates you have."},
    "Wellspring": {"kind": "landmark", "cost": 0, "expansion": "base",
                   "text": "Setup: put 6 VP per player here. When you gain a "
                           "Treasure, take 1 VP from here."},
}
# a stand-in for a Reserve card: a real CARD (zones hold real names) that this
# module temporarily teaches to sit on the Tavern mat and be called.
RESERVE = "Village"
WATCHED = "Market"      # a second real card, used as a synthetic trigger owner


@pytest.fixture
def reg():
    """Temporary registry entries, restored afterwards. The registries are
    module-level dicts the engine reads by reference, so tests MUTATE them in
    place rather than rebinding — a rebind would leave engine.py's own
    `from .cards import LANDSCAPES` pointing at the original object."""
    saved = (dict(cards.LANDSCAPES), dict(effects.LANDSCAPE_FX),
             {k: list(v) for k, v in effects.TRIGGERS.items()},
             dict(effects.STAGES), dict(effects.LANDSCAPE_SCORING),
             dict(effects.LANDSCAPE_SETUP))
    cards.LANDSCAPES.update(copy.deepcopy(LS))
    yield effects
    for store, old in ((cards.LANDSCAPES, saved[0]),
                       (effects.LANDSCAPE_FX, saved[1]),
                       (effects.TRIGGERS, saved[2]),
                       (effects.STAGES, saved[3]),
                       (effects.LANDSCAPE_SCORING, saved[4]),
                       (effects.LANDSCAPE_SETUP, saved[5])):
        store.clear()
        store.update(old)


def fresh(players=(A, B), seed=42, kingdom=tuple(K10), expansions=("base",),
          landscapes=None):
    return engine.new_game(list(players), list(expansions), seed=seed,
                           kingdom=list(kingdom), landscapes=landscapes)


def buy_phase(g, pid=A, coins=20, buys=1):
    g["turn"] = pid
    g["phase"] = "buy"
    g["coins"] = coins
    g["buys"] = buys
    g["pending"] = []
    engine._sync_pending(g)


def buy_ls(g, pid, name):
    return engine.apply_move(g, pid, {"type": "buy_landscape", "name": name})


def frame(g):
    return g["pending"][-1] if g["pending"] else None


def events(g, name):
    return [e for e in g["log"] if e.get("event") == name]


# ── the data model ────────────────────────────────────────────────────────────

def test_only_adventures_has_landscapes_so_far():
    """6H shipped the machinery with no content; ph. 7 filled in the 20 Events.
    This is the tripwire for the NEXT set that adds landscape data — at which
    point the no-entropy proof below needs re-reading, since a non-empty pool
    is exactly when the dealer stops being free."""
    assert {d["expansion"] for d in cards.LANDSCAPES.values()} == {"adventures"}
    for exp in cards.KINGDOM:
        g = engine.new_game([A, B], [exp], seed=5)
        if exp != "adventures":
            assert g["landscapes"] == {}, exp


def test_the_dealer_draws_no_entropy_when_there_is_nothing_to_deal():
    """THE behaviour-preservation proof for this phase. Setup is one rng call
    sequence; inserting a step into it would re-deal every existing seed's
    board. Because every pool is empty today the dealer returns before touching
    the rng at all, so the sequence is untouched — which is why the whole
    pre-6H suite (forced boards, expected kingdoms, the determinism soak) still
    reads the same."""
    rng = engine.random.Random(7)
    before = rng.getstate()
    assert engine.deal_landscapes(sorted(cards.KINGDOM["base"]), [], rng) == []
    assert rng.getstate() == before


def test_the_dealer_caps_at_two_and_at_one_way(reg):
    """"No more than two landscape cards per game, and no more than one of them
    a Way" (p11). Run over many seeds because the deal is a shuffle: a cap that
    only usually holds is not a cap."""
    pool = sorted(LS)
    kpool = sorted(cards.KINGDOM["base"])
    for seed in range(60):
        got = engine.deal_landscapes(kpool, pool, engine.random.Random(seed))
        assert len(got) <= 2
        assert sum(1 for n in got if LS[n]["kind"] == "way") <= 1
        assert len(set(got)) == len(got)          # no landscape dealt twice
        assert all(n in pool for n in got)


def test_the_deal_is_a_function_of_the_seed(reg):
    pool, kpool = sorted(LS), sorted(cards.KINGDOM["base"])
    for seed in (1, 2, 3):
        a = engine.deal_landscapes(kpool, pool, engine.random.Random(seed))
        b = engine.deal_landscapes(kpool, pool, engine.random.Random(seed))
        assert a == b
    # ...and it genuinely varies, or "deterministic" would be trivially true
    seen = {tuple(engine.deal_landscapes(kpool, pool, engine.random.Random(s)))
            for s in range(40)}
    assert len(seen) > 1


def test_a_bigger_landscape_pool_really_does_put_more_on_the_table(reg):
    """The dealer simulates the randomizer shuffle rather than approximating
    it, so pool SIZE matters: shuffling 4 landscapes in with 26 Kingdom cards
    lands one more often than shuffling 1 in. A proportion-style shortcut would
    quietly lose that, and the caps would hide it."""
    kpool = sorted(cards.KINGDOM["base"])
    def rate(pool):
        return sum(len(engine.deal_landscapes(kpool, pool, engine.random.Random(s)))
                   for s in range(300))
    assert rate(sorted(LS)) > rate(["Errand"])


def test_the_forced_landscape_seam_puts_them_on_the_table(reg):
    """`landscapes=` is to landscapes what `kingdom=` is to the ten: the test
    seam, and until ph. 7 the ONLY way one reaches a board."""
    g = fresh(landscapes=["Errand", "Bequest"])
    assert sorted(g["landscapes"]) == ["Bequest", "Errand"]
    assert g["landscapes"]["Errand"] == {"kind": "event", "bought_turn": None,
                                         "bought_by": []}
    json.dumps(g)                      # the game dict stays JSON-safe


def test_new_game_refuses_an_unknown_landscape(reg):
    with pytest.raises(ValueError):
        fresh(landscapes=["Nonesuch"])


def test_a_landscape_is_neither_a_card_nor_a_pile(reg):
    """It has no copies, is never gained and never sits in a zone, so it must
    not appear anywhere the census, the Supply or the card data look. This is
    the Knights lesson in reverse — there a pile name had to be tolerated by
    structures built for cards; here the foreign thing simply gets its own
    home."""
    g = fresh(landscapes=["Errand"])
    assert "Errand" not in cards.CARDS
    assert "Errand" not in g["piles"] and "Errand" not in g["supply"]
    assert "Errand" not in g["nonsupply"]
    assert "Errand" not in engine.pile_cards(g)
    assert "Errand" not in engine.owned_cards(g, A)
    # ...and it is not buyable as a card, by either route
    buy_phase(g, A)
    assert {"type": "buy", "card": "Errand"} not in engine.legal_moves(g, A)
    ok, err = engine.apply_move(g, A, {"type": "buy", "card": "Errand"})
    assert not ok and err == "no such pile"


# ── buy_landscape ─────────────────────────────────────────────────────────────

def test_buying_an_event_spends_a_buy_and_the_coins_and_runs_its_ability(reg):
    reg.LANDSCAPE_FX["Errand"] = lambda game, pid: engine.add_buys(game, 1)
    g = fresh(landscapes=["Errand"])
    buy_phase(g, A, coins=5, buys=1)
    assert {"type": "buy_landscape", "name": "Errand"} in engine.legal_moves(g, A)
    ok, err = buy_ls(g, A, "Errand")
    assert ok, err
    assert g["coins"] == 3                    # $5 - $2
    assert g["buys"] == 1                     # one spent, one granted back
    assert events(g, "buy_landscape")[-1]["name"] == "Errand"


def test_buying_an_event_is_not_buying_a_card(reg):
    """"Buying an Event is not buying a card" (p32) — so nothing on the gain or
    buy seam may see it. A Hoard, a Haggler or a Merchant Guild that fired here
    would be handing out cards and Coffers for a purchase that gained nothing."""
    seen = []
    reg.STAGES[(WATCHED, "spy")] = lambda game, pid, fr, ch: seen.append(fr["data"])
    g = fresh(landscapes=["Errand"])
    engine.add_watcher(g, A, WATCHED, "gain", stage="spy")
    engine.add_watcher(g, A, WATCHED, "buy", stage="spy")
    buy_phase(g, A, coins=5)
    before_gains = g["turn_ctx"]["buy_gains"]
    assert buy_ls(g, A, "Errand")[0]
    assert seen == [], "an Event purchase reached a gain/buy watcher"
    assert not events(g, "gain") and not events(g, "buy")
    assert g["turn_ctx"]["buy_gains"] == before_gains
    # nothing landed in a zone, either
    assert engine.owned_cards(g, A).count("Errand") == 0


def test_buying_an_event_still_ends_the_treasure_half_of_the_buy_phase(reg):
    """Buying ANYTHING sets turn_ctx["bought"], because the restriction is on
    the phase, not on what was bought."""
    g = fresh(landscapes=["Errand"])
    buy_phase(g, A, coins=5)
    g["seats"][A]["hand"] = ["Copper", "Copper"]
    assert buy_ls(g, A, "Errand")[0]
    assert g["turn_ctx"]["bought"] is True
    moves = engine.legal_moves(g, A)
    assert not [m for m in moves if m["type"].startswith("play_")]
    ok, err = engine.apply_move(g, A, {"type": "play_treasure", "card": "Copper"})
    assert not ok and "after buying" in err


def test_a_landscape_price_cannot_be_changed_by_bridge(reg):
    """"Its cost cannot be changed by cards like Bridge" — which is why
    landscape_cost reads the PRINTED value and never goes near engine.cost.
    Pinned against a turn where cards ARE discounted, so a wrong implementation
    is visibly wrong rather than coincidentally right."""
    g = fresh(landscapes=["Errand"])
    buy_phase(g, A, coins=2)
    g["turn_ctx"]["bridges"] = 2
    assert engine.cost(g, "Village") == 1              # cards really are cheaper
    assert engine.landscape_cost(g, "Errand") == 2     # ...the Event is not
    g["coins"] = 1
    assert {"type": "buy_landscape", "name": "Errand"} not in engine.legal_moves(g, A)
    ok, err = buy_ls(g, A, "Errand")
    assert not ok and err == "can't afford it"


def test_once_per_turn_binds_to_the_turn_not_the_game(reg):
    g = fresh(landscapes=["Almsgiving"])
    buy_phase(g, A, coins=5, buys=3)
    assert buy_ls(g, A, "Almsgiving")[0]
    assert engine.landscape_gate(g, A, "Almsgiving") == "you already bought that this turn"
    assert {"type": "buy_landscape", "name": "Almsgiving"} not in engine.legal_moves(g, A)
    ok, err = buy_ls(g, A, "Almsgiving")
    assert not ok and err == "you already bought that this turn"
    g["turn_number"] += 1                       # ...and it comes back next turn
    assert engine.landscape_gate(g, A, "Almsgiving") is None


def test_once_per_game_binds_to_the_player_not_the_game(reg):
    """Each player gets their one purchase — the restriction is per player, the
    way every once-per-game Event's is."""
    g = fresh(landscapes=["Bequest"])
    buy_phase(g, A, coins=9, buys=3)
    assert buy_ls(g, A, "Bequest")[0]
    assert engine.landscape_gate(g, A, "Bequest") == "you already bought that this game"
    assert engine.landscape_gate(g, B, "Bequest") is None
    g["turn_number"] += 5
    assert engine.landscape_gate(g, A, "Bequest") == "you already bought that this game"


def test_a_way_is_never_offered_for_buying(reg):
    """Only Events and Projects are BOUGHT; a Way / Landmark / Trait / Prophecy
    is consulted. The kinds are framed now so ph. 8-14 add data, not a gate."""
    g = fresh(landscapes=["Byway"])
    buy_phase(g, A, coins=20)
    assert engine.landscape_gate(g, A, "Byway") == "a way is not something you buy"
    assert not [m for m in engine.legal_moves(g, A) if m["type"] == "buy_landscape"]
    ok, err = buy_ls(g, A, "Byway")
    assert not ok


def test_the_enumerator_and_the_handler_never_disagree(reg):
    """ONE gate reader, consulted by both — the play_all_treasures livelock
    lesson. An enumerator that offers what the handler refuses hands a bot a
    move that changes nothing, and the scheduler burns its whole iteration cap
    on no-op broadcasts and DB saves."""
    reg.LANDSCAPE_FX["Errand"] = lambda game, pid: engine.add_buys(game, 1)
    for coins in range(0, 5):
        for buys in (0, 1):
            for pre_bought in (False, True):
                g = fresh(landscapes=["Almsgiving", "Bequest", "Errand", "Byway"])
                buy_phase(g, A, coins=coins, buys=buys)
                if pre_bought:
                    g["landscapes"]["Almsgiving"]["bought_turn"] = g["turn_number"]
                    g["landscapes"]["Bequest"]["bought_by"] = [A]
                offered = {m["name"] for m in engine.legal_moves(g, A)
                           if m["type"] == "buy_landscape"}
                for name in g["landscapes"]:
                    probe = copy.deepcopy(g)
                    ok, _ = buy_ls(probe, A, name)
                    assert ok == (name in offered), (
                        f"{name}: offered={name in offered} accepted={ok} "
                        f"(coins={coins} buys={buys} bought={pre_bought})")


def test_a_landscape_ability_may_push_a_decision_and_it_shows_its_own_name(reg):
    """A landscape's ability is an ability like any other — it can push frames,
    and they display under the LANDSCAPE's name, so the six generic renderers
    need no new case."""
    def _errand(game, pid):
        engine.push_choose_option(game, pid, "Errand", "pick", options=[
            {"id": "buy", "label": "+1 Buy"}, {"id": "coin", "label": "+$1"}])
    reg.LANDSCAPE_FX["Errand"] = _errand
    reg.STAGES[("Errand", "pick")] = lambda game, pid, fr, ch: (
        engine.add_buys(game, 1) if ch["ids"][0] == "buy" else engine.add_coins(game, 1))
    g = fresh(landscapes=["Errand"])
    buy_phase(g, A, coins=5, buys=1)
    assert buy_ls(g, A, "Errand")[0]
    assert frame(g)["card"] == "Errand" and frame(g)["kind"] == "choose_option"
    assert engine.player_view(g, A)["pending_view"]["card"] == "Errand"
    assert engine.apply_move(g, A, {"type": "decision", "ids": ["coin"]})[0]
    assert g["coins"] == 4                     # $5 - $2 + $1


def test_buying_a_landscape_is_undoable(reg):
    """An ordinary turn-player move that reveals nothing, so it snapshots and
    rewinds like any other."""
    reg.LANDSCAPE_FX["Errand"] = lambda game, pid: engine.add_buys(game, 1)
    # the LOG is excluded on purpose: it is append-only and an undo TRUNCATES it
    # and records itself, so it is the one thing an undo is meant to change.
    def snap(game):
        return json.dumps({k: v for k, v in game.items()
                           if k not in ("undo_stack", "log")}, sort_keys=True)
    g = fresh(landscapes=["Errand"])
    buy_phase(g, A, coins=5, buys=1)
    engine._arm_undo(g)
    before = snap(g)
    assert buy_ls(g, A, "Errand")[0]
    assert g["landscapes"]["Errand"]["bought_turn"] is not None
    assert g["turn_ctx"]["bought"] is True
    assert engine.apply_move(g, A, {"type": "undo_turn"})[0]
    assert snap(g) == before
    assert g["landscapes"]["Errand"]["bought_turn"] is None
    assert g["turn_ctx"]["bought"] is False


def test_landscapes_are_public_on_the_wire(reg):
    """Landscapes sit face up on the table — they are open information, and the
    per-field decision is made here rather than left to whatever deepcopy did."""
    g = fresh(landscapes=["Errand", "Bequest"])
    buy_phase(g, A, coins=9)
    assert buy_ls(g, A, "Bequest")[0]
    for viewer in (A, B, None):
        view = engine.player_view(g, viewer)
        assert sorted(view["landscapes"]) == ["Bequest", "Errand"]
        assert view["landscapes"]["Bequest"]["bought_by"] == [A]
        json.dumps(view)


# ── the Tavern mat and calling ────────────────────────────────────────────────

def test_a_card_on_the_tavern_mat_is_still_yours(reg):
    """It is owned, it scores, and the bots' deck reads see it — Distant Lands
    scores ON the mat, so `owned_cards` reaching the zone is load-bearing."""
    g = fresh()
    g["seats"][A]["hand"] = [RESERVE]
    assert engine.to_tavern(g, A, RESERVE, zone="hand") is True
    assert g["seats"][A]["tavern"] == [RESERVE]
    assert RESERVE not in g["seats"][A]["hand"]
    assert engine.owned_cards(g, A).count(RESERVE) == 1
    assert engine.on_tavern(g, A, RESERVE) is True
    assert events(g, "to_tavern")[-1]["card"] == RESERVE


def test_to_tavern_refuses_a_card_that_is_not_there(reg):
    g = fresh()
    assert engine.to_tavern(g, A, RESERVE, zone="hand") is False
    assert g["seats"][A]["tavern"] == []


def test_calling_is_not_playing(reg):
    """"This is NOT playing it, so you don't resolve the play ability, it
    doesn't cost an Action, and it doesn't trigger before-play or after-play
    abilities" (p28). Every clause of that is a separate assertion, because
    routing a call through play_action_card would satisfy none of them."""
    fired = []
    reg.TRIGGERS[WATCHED] = [
        {"on": "before_play", "from": "in_play",
         "push": lambda game, pid, ctx: fired.append(("before", ctx["subject"]))},
        {"on": "action_resolved", "from": "in_play",
         "push": lambda game, pid, ctx: fired.append(("after", ctx["subject"]))},
    ]
    g = fresh()
    g["seats"][A]["in_play"] = [WATCHED]
    g["seats"][A]["tavern"] = [RESERVE]
    g["actions"] = 1
    before_actions, before_played = g["actions"], g["turn_ctx"]["actions_played"]
    draws = len(events(g, "draw"))          # the setup deal already logged some

    assert engine.call_card(g, A, RESERVE) is True
    engine._drive(g)
    assert g["seats"][A]["tavern"] == []
    assert RESERVE in g["seats"][A]["in_play"]      # it IS in play
    assert g["actions"] == before_actions           # ...but cost no Action
    assert g["turn_ctx"]["actions_played"] == before_played
    assert fired == []                              # ...and no play triggers
    # Village's own play ability (+1 Card, +2 Actions) did NOT run
    assert len(events(g, "draw")) == draws
    assert not events(g, "plus")
    assert events(g, "call")[-1]["card"] == RESERVE


def test_calling_refuses_a_card_that_is_not_on_the_mat(reg):
    g = fresh()
    assert engine.call_card(g, A, RESERVE) is False


def test_a_called_card_is_discarded_in_that_turns_cleanup(reg):
    """"It's discarded from play in Clean-up THAT turn" — the caller's own turn
    if they called on it, and otherwise the turn player's, which is what the
    all-seats clean-up sweep already does for a reaction that plays itself."""
    g = fresh()
    g["turn"] = A                                   # ...but B does the calling
    g["seats"][B]["tavern"] = [RESERVE]
    assert engine.call_card(g, B, RESERVE) is True
    g["phase"] = "buy"
    g["seats"][A]["hand"] = []
    assert engine.apply_move(g, A, {"type": "end_phase"})[0]
    assert g["seats"][B]["in_play"] == []
    assert RESERVE in g["seats"][B]["discard"]


def test_a_tavern_window_is_offered_like_a_hand_reaction(reg):
    """Every call in the game is a timed WINDOW — at the start of your turn, on
    a gain, after resolving an Action, at the end of your Buy phase. So calling
    rides the existing offer machinery (and the ability POOL, so it is ordered
    against everything else the same occurrence triggered) rather than being a
    free move of its own."""
    def _call_stage(game, pid, fr, ch):
        if ch["ids"][0] == "play":
            engine.call_card(game, pid, RESERVE)
            engine.add_coins(game, 2, pid)
    reg.STAGES[(RESERVE, "called")] = _call_stage
    reg.TRIGGERS[RESERVE] = [{"on": "gain", "from": "tavern", "who": "actor",
                              "stage": "called"}]
    g = fresh()
    g["seats"][A]["tavern"] = [RESERVE]
    buy_phase(g, A, coins=3)
    engine.gain(g, A, "Silver")
    engine._drive(g)
    f = frame(g)
    assert f is not None and f["card"] == RESERVE
    labels = [o["label"] for o in f["constraint"]["options"]]
    assert labels[0] == f"Call {RESERVE} from your Tavern mat"
    assert engine.apply_move(g, A, {"type": "decision", "ids": ["play"]})[0]
    assert g["seats"][A]["tavern"] == [] and RESERVE in g["seats"][A]["in_play"]
    assert g["coins"] == 5


def test_a_tavern_offer_loses_track_if_the_card_left_the_mat(reg):
    """The window's condition was true at the OCCURRENCE; by the time this
    player picks the ability an earlier pick may have moved the card. A skipped
    ability must never be silent — that is the whole `lost_track` rule."""
    reg.STAGES[(RESERVE, "called")] = lambda game, pid, fr, ch: None
    reg.TRIGGERS[RESERVE] = [{"on": "gain", "from": "tavern", "who": "actor",
                              "stage": "called"}]
    g = fresh()
    g["seats"][A]["tavern"] = [RESERVE]
    buy_phase(g, A, coins=3)
    engine.gain(g, A, "Silver")
    g["seats"][A]["tavern"] = []          # something else moved it first
    engine._drive(g)
    assert frame(g) is None
    assert events(g, "lost_track")[-1]["card"] == RESERVE


def test_the_tavern_mat_is_public_on_the_wire(reg):
    """Mat contents lie FACE UP (p28), so unlike the Native Village mat they
    ship to everybody. Asserted against the serialized payload of a real game,
    per the nested-snapshot lesson."""
    g = fresh()
    g["seats"][A]["tavern"] = [RESERVE]
    for viewer in (A, B, None):
        blob = json.dumps(engine.player_view(g, viewer))
        assert json.loads(blob)["seats"][A]["tavern"] == [RESERVE]


# ── before_play and action_resolved ───────────────────────────────────────────

def test_before_play_fires_for_every_action_play_and_resolves_first(reg):
    """ph. 6's `play_attack` is now `before_play`, emitted for EVERY Action
    play, because an Adventures "+" token is the same timing class as Urchin
    ("after before-play abilities like Adventures tokens, Kiln, Urchin", p33).
    ONE event, not two — and it must genuinely resolve BEFORE the played card's
    own ability, which for a non-Attack means the ability gets parked under it."""
    seen = []
    reg.TRIGGERS[WATCHED] = [{"on": "before_play", "from": "in_play",
                              "push": lambda game, pid, ctx: seen.append(
                                  (ctx["subject"], len(game["seats"][pid]["hand"]),
                                   ctx["attack"], ctx["replay"]))}]
    g = fresh()
    g["seats"][A]["in_play"] = [WATCHED]
    g["seats"][A]["hand"] = ["Smithy"]
    g["seats"][A]["deck"] = ["Copper"] * 5
    assert engine.apply_move(g, A, {"type": "play_action", "card": "Smithy"})[0]
    # the hand was EMPTY when the window ran (Smithy had left it and had not
    # yet drawn) — the ability really was parked underneath
    assert seen == [("Smithy", 0, False, False)]
    assert len(g["seats"][A]["hand"]) == 3          # ...and then it drew


def test_before_play_carries_whether_the_play_was_an_attack(reg):
    """Urchin reads this: its ability is attack-only, and the attack-ness that
    used to be implicit in the event's NAME is now explicit in the ctx."""
    seen = []
    reg.TRIGGERS[WATCHED] = [{"on": "before_play", "from": "in_play",
                              "push": lambda game, pid, ctx: seen.append(
                                  (ctx["subject"], ctx["attack"]))}]
    g = fresh()
    g["seats"][A]["in_play"] = [WATCHED]
    g["seats"][A]["hand"] = ["Militia", "Village"]
    g["actions"] = 2
    assert engine.apply_move(g, A, {"type": "play_action", "card": "Militia"})[0]
    while g["pending_pid"] is not None:              # answer B's discard
        pid = g["pending_pid"]
        engine.apply_move(g, pid, {"type": "decision",
                                   **engine.sample_decision(g, pid, engine.random.Random(1))})
    assert engine.apply_move(g, A, {"type": "play_action", "card": "Village"})[0]
    assert seen == [("Militia", True), ("Village", False)]


def test_action_resolved_fires_only_once_the_plays_frames_have_drained(reg):
    """"Directly after resolving an Action card" cannot be an emit inside
    play_action_card: that returns while the play's frames are still pending,
    and "completely resolve the play ability before playing it again" (p17)
    defines resolution as those frames having drained. So it is a parked
    continuation, and the proof is that an OPEN decision holds it back."""
    seen = []
    reg.TRIGGERS[WATCHED] = [{"on": "action_resolved", "from": "in_play",
                              "push": lambda game, pid, ctx: seen.append(
                                  (ctx["subject"], ctx["replay"]))}]
    g = fresh()
    g["seats"][A]["in_play"] = [WATCHED]
    g["seats"][A]["hand"] = ["Cellar", "Estate", "Estate"]
    g["seats"][A]["deck"] = ["Copper"] * 5
    assert engine.apply_move(g, A, {"type": "play_action", "card": "Cellar"})[0]
    assert frame(g)["card"] == "Cellar"
    assert seen == [], "it fired while the play was still resolving"
    assert engine.apply_move(g, A, {"type": "decision", "cards": ["Estate"]})[0]
    assert seen == [("Cellar", False)]


def test_a_throne_roomed_action_resolves_twice(reg):
    """Two resolutions, two emits — a Royal Carriage may be called after each.
    The replay flag is how a consumer that cares can tell them apart."""
    seen = []
    reg.TRIGGERS[WATCHED] = [{"on": "action_resolved", "from": "in_play",
                              "push": lambda game, pid, ctx: seen.append(
                                  (ctx["subject"], ctx["replay"]))}]
    g = fresh()
    g["seats"][A]["in_play"] = [WATCHED]
    g["seats"][A]["hand"] = ["Throne Room", "Village"]
    g["seats"][A]["deck"] = ["Copper"] * 5
    assert engine.apply_move(g, A, {"type": "play_action", "card": "Throne Room"})[0]
    assert engine.apply_move(g, A, {"type": "decision", "cards": ["Village"]})[0]
    assert seen == [("Village", False), ("Village", True),
                    ("Throne Room", False)]


def test_a_play_with_no_before_play_consumer_runs_its_effect_inline(reg):
    """The generalization is byte-identical when nothing consumes it, which is
    every board today: with no consumer the emit collects nothing, no frame is
    parked, and the effect runs inline exactly as it did before 6H."""
    g = fresh()
    g["seats"][A]["hand"] = ["Smithy"]
    g["seats"][A]["deck"] = ["Copper"] * 5
    engine.play_action_card(g, A, "Smithy", from_zone="hand")
    # drawn ALREADY, with no _drive in between — the effect was not parked
    assert len(g["seats"][A]["hand"]) == 3


# ── Adventures tokens ─────────────────────────────────────────────────────────

def test_moving_a_token_takes_it_off_the_pile_it_was_on(reg):
    """"If you move a token that is already on a pile, it is moved FROM that
    pile" — which is why move_token is the only writer and pile_attach is not
    used directly for these."""
    g = fresh()
    assert engine.move_token(g, A, "+card", "Village") is True
    assert engine.pile_tokens(g, "Village", A) == ["+card"]
    assert engine.token_pile(g, A, "+card") == "Village"
    assert engine.move_token(g, A, "+card", "Smithy") is True
    assert engine.pile_tokens(g, "Village", A) == []
    assert engine.pile_tokens(g, "Smithy", A) == ["+card"]
    assert engine.token_pile(g, A, "+card") == "Smithy"
    # ...and the vacated pile is left CLEAN, not holding an empty husk
    assert g["piles"]["Village"]["attach"] == {}


def test_two_players_tokens_are_kept_apart(reg):
    g = fresh()
    engine.move_token(g, A, "+card", "Village")
    engine.move_token(g, B, "+card", "Village")
    assert engine.pile_tokens(g, "Village") == {A: ["+card"], B: ["+card"]}
    engine.move_token(g, A, "+card", "Smithy")
    assert engine.pile_tokens(g, "Village") == {B: ["+card"]}


def test_a_token_may_sit_on_an_empty_pile(reg):
    """"Tokens may be put on an empty pile" — so the check is that the pile
    EXISTS, not that it has cards left."""
    g = fresh()
    g["supply"]["Village"] = 0
    assert engine.move_token(g, A, "+buy", "Village") is True
    assert engine.pile_tokens(g, "Village", A) == ["+buy"]
    # ...but a pile this board never dealt is refused rather than conjured
    assert engine.move_token(g, A, "+buy", "Nonesuch") is False


def test_the_cost_token_discounts_only_on_its_owners_turns(reg):
    """"Cards from that pile cost $2 less ON YOUR TURNS" — it keys on whose
    turn it is, not on who is asking, which is exactly what lets cost(game,
    card) keep its two-argument signature and its ~60 call sites."""
    g = fresh()
    engine.move_token(g, A, "-cost", "Market")
    g["turn"] = A
    assert engine.cost(g, "Market") == cards.CARDS["Market"]["cost"] - 2
    assert engine.cost(g, "Village") == cards.CARDS["Village"]["cost"]
    g["turn"] = B
    assert engine.cost(g, "Market") == cards.CARDS["Market"]["cost"]


def test_the_cost_token_stacks_with_bridge_and_floors_at_zero(reg):
    g = fresh()
    engine.move_token(g, A, "-cost", "Market")
    g["turn"] = A
    g["turn_ctx"]["bridges"] = 1
    assert engine.cost(g, "Market") == 2               # $5 - $2 - $1
    g["turn_ctx"]["bridges"] = 9
    assert engine.cost(g, "Market") == 0


def test_the_cost_token_prices_an_ordered_pile_through_the_pile_not_the_card(reg):
    """The token is on a PILE, so it has to be read before the pile name
    collapses into its face card — and it must discount the pile whichever way
    the price is asked for."""
    g = fresh(kingdom=list(K10), expansions=("base",))
    engine.add_pile(g, "Knights", contents=["Bandit", "Cellar"], supply=True)
    engine.move_token(g, A, "-cost", "Knights")
    g["turn"] = A
    assert engine.cost(g, "Knights") == cards.CARDS["Bandit"]["cost"] - 2
    assert engine.cost(g, "Bandit") == cards.CARDS["Bandit"]["cost"] - 2


def test_pile_tokens_ship_as_public_table_state(reg):
    g = fresh()
    engine.move_token(g, A, "-cost", "Market")
    for viewer in (A, B, None):
        view = json.loads(json.dumps(engine.player_view(g, viewer)))
        assert view["piles"]["Market"]["attach"]["tokens"] == {A: ["-cost"]}
        # the discount reaches the SERVER-computed price the client renders
        assert view["costs"]["Market"] == engine.cost(g, "Market")


def test_seat_tokens_are_stored_and_public(reg):
    """The -1 Card / -$1 / Journey tokens sit in front of a PLAYER, not on a
    pile. 6H lands the storage only — ph. 7 wires them to the draw and the +$
    — so that migrate is done once rather than twice."""
    g = fresh()
    assert engine.seat_token(g, A, "-card") is None
    engine.set_seat_token(g, A, "-card", True)
    assert engine.seat_token(g, A, "-card") is True
    assert json.loads(json.dumps(engine.player_view(g, B)))["seats"][A]["tokens"] \
        == {"-card": True}
    engine.set_seat_token(g, A, "-card", None)
    assert g["seats"][A]["tokens"] == {}


# ── the SCORING PIPELINE hook (ph. 7H) ────────────────────────────────────────

def test_a_landmarks_scoring_fn_reaches_both_seats_live_and_at_the_end(reg):
    """`effects.LANDSCAPE_SCORING` is summed into _total_vp, which _post_move
    recomputes after every move — so a landmark's VP shows DURING the game for
    free, and `score_game` reads the same number at the end. "A Landmark's
    ability is always active for all players", so there is no ownership test."""
    reg.LANDSCAPE_SCORING["Cairn"] = \
        lambda game, pid: 2 * (engine.owned_cards(game, pid).count("Estate") // 3)
    g = fresh(landscapes=["Cairn"])
    # a fresh deck holds 3 Estates: 3 VP of card VP + 2 VP of landmark, per seat
    assert g["vp"] == {A: 3 + 2, B: 3 + 2}
    engine.gain(g, A, "Estate")
    engine.gain(g, A, "Estate")
    engine.gain(g, A, "Estate")
    engine._post_move(g)
    assert g["vp"][A] == 6 + 4, "the landmark must re-score as the deck changes"
    assert g["vp"][B] == 3 + 2
    scores = engine.score_game(g)
    assert scores[A]["vp"] == 10 and scores[B]["vp"] == 5


def test_a_landmark_that_is_not_dealt_scores_nothing(reg):
    """Being ON THE TABLE is the whole condition — the same shape as
    from:"game" reading the Supply. A registered fn for a landscape this game
    was not dealt must never be summed."""
    reg.LANDSCAPE_SCORING["Cairn"] = lambda game, pid: 100
    g = fresh(landscapes=[])                      # no landscapes dealt
    assert g["landscapes"] == {}
    assert g["vp"] == {A: 3, B: 3}
    assert engine.landscape_scoring(g, A) == 0


def test_a_scoring_fn_does_not_change_value_at_game_over(reg):
    """The ph.-7 Inheritance lesson: `types_of` stops injecting once the game is
    over, so a landmark that counts by TYPE must read the same before and after.
    Anything else means the final score differs from the one the players were
    watching all game."""
    reg.LANDSCAPE_SCORING["Cairn"] = \
        lambda game, pid: sum(1 for c in engine.owned_cards(game, pid)
                              if engine.has_type(game, c, "victory"))
    g = fresh(landscapes=["Cairn"])
    before = engine.landscape_scoring(g, A)
    g["over"] = True
    assert engine.landscape_scoring(g, A) == before


def test_a_landscape_setup_fn_runs_after_the_piles_exist(reg):
    """`effects.LANDSCAPE_SETUP` — Obelisk needs the rng and an Action-pile
    query, Tax and Aqueduct write pile attachments. Ordered after every pile is
    built and before the opening deal, so all three can see the board."""
    seen = {}

    def _setup(game, rng):
        seen["piles"] = set(game["piles"])
        seen["pick"] = rng.choice(sorted(p for p in game["supply"]
                                         if engine.has_type(game, p, "action")))
        engine.add_pile_vp(game, "Gold", 8)
        game["landscapes"]["Wellspring"]["pile"] = seen["pick"]

    reg.LANDSCAPE_SETUP["Wellspring"] = _setup
    g = fresh(landscapes=["Wellspring"])
    assert "Gold" in seen["piles"] and "Village" in seen["piles"]
    assert engine.pile_vp(g, "Gold") == 8
    assert g["landscapes"]["Wellspring"]["pile"] == seen["pick"]
    # ...and the choice is a function of the seed, like the rest of setup
    g2 = fresh(landscapes=["Wellspring"])
    assert g2["landscapes"]["Wellspring"]["pile"] == seen["pick"]


def test_a_board_with_no_setup_landscape_draws_no_extra_entropy(reg):
    """The behaviour-preservation proof for the setup pass. It re-saves the rng
    only when a setup actually RAN, so a board with no setup landscape — which
    is every board that exists today — deals exactly the hands it always did.

    Proved two ways per seed: a registered setup for an UNDEALT landscape must
    not run at all (the fn raises if it does), and a DEALT landscape with no
    setup entry must leave every seat byte-identical to a board with none."""
    def _must_not_run(game, rng):
        raise AssertionError("a setup ran for a landscape that was not dealt")

    for seed in (1, 7, 99):
        plain = engine.new_game([A, B], ["base"], seed=seed, kingdom=list(K10),
                                landscapes=[])
        reg.LANDSCAPE_SETUP["Wellspring"] = _must_not_run
        same = engine.new_game([A, B], ["base"], seed=seed, kingdom=list(K10),
                               landscapes=[])
        assert json.dumps(same["seats"], sort_keys=True) == \
            json.dumps(plain["seats"], sort_keys=True)
        del reg.LANDSCAPE_SETUP["Wellspring"]
        dealt = engine.new_game([A, B], ["base"], seed=seed, kingdom=list(K10),
                                landscapes=["Errand"])
        assert json.dumps(dealt["seats"], sort_keys=True) == \
            json.dumps(plain["seats"], sort_keys=True), \
            "putting a landscape on the table moved the opening deal"


# ── landscape VP stores + pile-attached VP and Debt ───────────────────────────

def test_a_landscape_vp_store_fills_drains_and_gives_nothing_when_empty(reg):
    """The Arena/Battlefield class: "put 6 VP per player on this", taken one at
    a time until it runs out. Taking moves them to the PLAYER, as real VP
    tokens — which is why an empty store simply gives nothing."""
    g = fresh(landscapes=["Wellspring"])
    assert engine.landscape_vp(g, "Wellspring") == 0
    assert engine.add_landscape_vp(g, "Wellspring", 12) is True
    assert engine.landscape_vp(g, "Wellspring") == 12
    assert engine.take_landscape_vp(g, "Wellspring", A, 2) == 2
    assert g["vp_tokens"][A] == 2 and engine.landscape_vp(g, "Wellspring") == 10
    assert engine.take_landscape_vp(g, "Wellspring", B) == 10, "n=None takes all"
    assert engine.landscape_vp(g, "Wellspring") == 0
    assert "vp" not in g["landscapes"]["Wellspring"], "an empty store keeps no key"
    assert engine.take_landscape_vp(g, "Wellspring", A, 3) == 0
    assert g["vp_tokens"][A] == 2
    # ...and a landscape this game was not dealt is a no-op, never a KeyError
    assert engine.add_landscape_vp(g, "Errand", 4) is False
    assert engine.take_landscape_vp(g, "Errand", A) == 0


def test_a_landscape_vp_store_is_capped_by_what_is_there(reg):
    g = fresh(landscapes=["Wellspring"])
    engine.add_landscape_vp(g, "Wellspring", 3)
    assert engine.take_landscape_vp(g, "Wellspring", A, 10) == 3
    assert g["vp_tokens"][A] == 3


def test_pile_vp_and_pile_debt_round_trip_and_ride_the_wire(reg):
    """Aqueduct/Defiled Shrine put VP on Supply piles and Tax puts Debt on
    every pile; both ride 3H's `attach`, which already ships. Asserted through
    the SERIALIZED view of a real game rather than a synthetic dict."""
    g = fresh(landscapes=["Errand"])
    assert engine.add_pile_vp(g, "Gold", 8) is True
    assert engine.add_pile_debt(g, "Village", 2) is True
    assert engine.pile_vp(g, "Gold") == 8 and engine.pile_debt(g, "Village") == 2
    for viewer in (A, B, None):
        view = json.loads(json.dumps(engine.player_view(g, viewer)))
        assert view["piles"]["Gold"]["attach"]["vp"] == 8
        assert view["piles"]["Village"]["attach"]["debt"] == 2
    # save/load: a plain JSON round trip plus migrate must not move any of it
    blob = json.loads(json.dumps(g))
    engine.migrate(blob)
    assert blob == json.loads(json.dumps(g))
    # taking moves them onto the player, through the public counters
    assert engine.take_pile_vp(g, A, "Gold", 3) == 3
    assert g["vp_tokens"][A] == 3 and engine.pile_vp(g, "Gold") == 5
    assert engine.take_pile_debt(g, B, "Village") == 2
    assert g["debt"][B] == 2 and engine.pile_debt(g, "Village") == 0
    assert "debt" not in g["piles"]["Village"]["attach"], "an empty count keeps no key"
    # an unknown pile is a no-op both ways (a landmark naming an undealt pile)
    assert engine.add_pile_vp(g, "Nonesuch", 1) is False
    assert engine.take_pile_vp(g, A, "Nonesuch") == 0
    assert engine.take_pile_debt(g, A, "Nonesuch") == 0


def test_pile_attachments_coexist_with_the_adventures_tokens(reg):
    """`attach` is one dict per pile, so the VP a gathering pile holds and the
    tokens Adventures puts on it have to share it without either clobbering the
    other — and `move_token`'s empty-key cleanup must not take the VP with it."""
    g = fresh()
    engine.add_pile_vp(g, "Village", 4)
    engine.move_token(g, A, "-cost", "Village")
    assert engine.pile_vp(g, "Village") == 4
    assert engine.pile_tokens(g, "Village", A) == ["-cost"]
    engine.move_token(g, A, "-cost", "Smithy")            # moved off Village
    assert engine.pile_tokens(g, "Village", A) == []
    assert engine.pile_vp(g, "Village") == 4, "the token cleanup ate the VP"


# ── from:"landscape" — a landmark on the trigger bus ──────────────────────────

def test_a_landmark_trigger_fires_for_the_gaining_player_only(reg):
    """The from:"game" shape keyed on the landscape being DEALT. The ability
    goes to the event's ACTOR (Aqueduct: "when YOU gain a Treasure...") and
    lands in that player's pool like any other consumer."""
    reg.STAGES[("Wellspring", "gained")] = \
        lambda game, pid, fr, ch: engine.take_landscape_vp(game, "Wellspring", pid, 1)
    reg.TRIGGERS["Wellspring"] = [
        {"on": "gain", "from": "landscape", "stage": "gained", "commutes": True,
         "when": lambda game, pid, ctx: engine.has_type(game, ctx["subject"], "treasure")}]
    g = fresh(landscapes=["Wellspring"])
    engine.add_landscape_vp(g, "Wellspring", 12)
    engine.gain(g, A, "Silver")
    engine._drive(g)
    assert g["vp_tokens"][A] == 1 and g["vp_tokens"][B] == 0
    engine.gain(g, B, "Gold")
    engine._drive(g)
    assert g["vp_tokens"][B] == 1
    # ...and its `when` is honoured: a Victory card is not a Treasure
    engine.gain(g, A, "Estate")
    engine._drive(g)
    assert g["vp_tokens"][A] == 1


def test_a_landmark_trigger_does_nothing_when_it_was_not_dealt(reg):
    reg.STAGES[("Wellspring", "gained")] = \
        lambda game, pid, fr, ch: engine.add_vp_tokens(game, pid, 5)
    reg.TRIGGERS["Wellspring"] = [{"on": "gain", "from": "landscape",
                                   "stage": "gained", "commutes": True}]
    g = fresh()                                   # Wellspring is NOT on the table
    engine.gain(g, A, "Silver")
    engine._drive(g)
    assert g["vp_tokens"][A] == 0


def test_a_landmark_trigger_pools_with_a_hand_reaction_on_the_same_gain(reg):
    """One occurrence, two of the player's abilities: p23 §2 says THEY choose
    the order, so both must arrive through the ability pool — a landmark that
    resolved inline would silently take the first slot."""
    reg.STAGES[("Wellspring", "gained")] = \
        lambda game, pid, fr, ch: engine.add_vp_tokens(game, pid, 1)
    reg.TRIGGERS["Wellspring"] = [{"on": "gain", "from": "landscape",
                                   "stage": "gained"}]
    reg.STAGES[(WATCHED, "react")] = \
        lambda game, pid, fr, ch: engine.add_coins(game, 2, pid)
    reg.TRIGGERS[WATCHED] = [{"on": "gain", "from": "hand", "who": "actor",
                              "stage": "react"}]
    g = fresh(landscapes=["Wellspring"])
    g["seats"][A]["hand"] = [WATCHED]
    buy_phase(g, A, coins=0)
    engine.gain(g, A, "Silver")
    engine._drive(g)
    f = frame(g)
    assert f is not None and f["card"] == "__abilities", \
        "two abilities from one gain must be the player's ordering choice"
    ids = [o["id"] for o in f["constraint"]["options"]]
    assert len(ids) == 2


# ── a split pile prices itself through its FACE (the paid-row pin) ────────────

def test_an_ordered_piles_cost_follows_its_current_face(reg):
    """Empires' five 5/5 split piles and the 8-Castle pile are ph.-8 SETUP DATA,
    not new code: 3H already prices a pile through the card on top, and retains
    that face when the pile empties. This is the verification the ph.-8 spec
    leans on — a passing contract test, not a new mechanism."""
    g = fresh()
    engine.add_pile(g, "Split", contents=["Cellar", "Cellar", "Market", "Market"],
                    supply=True, members=["Cellar", "Market"])
    assert engine.pile_top(g, "Split") == "Cellar"
    assert engine.cost(g, "Split") == 2               # Cellar's price
    engine._pile_take(g, "Split")
    engine._pile_take(g, "Split")
    assert engine.pile_top(g, "Split") == "Market"
    assert engine.cost(g, "Split") == 5               # the uncovered half
    engine._pile_take(g, "Split")
    engine._pile_take(g, "Split")
    assert engine.pile_count(g, "Split") == 0
    assert engine.cost(g, "Split") == 5, "an empty pile keeps its last face's price"
    assert engine.player_view(g, A)["costs"]["Split"] == 5


# ── the bots ──────────────────────────────────────────────────────────────────

def test_the_random_bot_buys_landscapes_and_the_money_tier_never_does(reg):
    """The random tiers exercise the new move for free, because they pick from
    legal_moves. bmplus must NOT, and it doesn't by construction — it builds
    `{"type": "buy", ...}` itself and only checks membership — which is what
    keeps every measured number in BM_TERMINALS / TERMINAL_CAPS comparable
    across this phase. Landscape-aware buying is ph. 7 bot work, measured then."""
    reg.LANDSCAPE_FX["Errand"] = lambda game, pid: engine.add_buys(game, 1)
    picks = set()
    for seed in range(40):
        g = fresh(landscapes=["Errand", "Almsgiving"])
        buy_phase(g, A, coins=8, buys=1)
        g["seats"][A]["hand"] = []        # else every tier plays treasures first
        picks.add(bot.choose(g, A, engine.random.Random(seed), "easy")["type"])
        assert bot.choose(g, A, engine.random.Random(seed), "bmplus")["type"] \
            != "buy_landscape"
    assert "buy_landscape" in picks


def test_a_full_random_game_with_landscapes_terminates_and_conserves_cards(reg):
    """The soak's guarantees, on a board carrying the new move: every accepted
    move changes the game, the card census holds (a landscape is not a card, so
    buying one must not move the count), and the game ends."""
    reg.LANDSCAPE_FX["Errand"] = lambda game, pid: engine.add_buys(game, 1)
    reg.LANDSCAPE_FX["Bequest"] = lambda game, pid: engine.add_coins(game, 2)
    from collections import Counter

    def census(game):
        """Every card in the game, by name. Buying a landscape gains nothing,
        so this must not move at all when one is bought."""
        total = Counter(engine.pile_cards(game))
        total.update(game["trash"])
        for p in game["players"]:
            total.update(engine.owned_cards(game, p))
        return total

    rng = engine.random.Random(9)
    g = fresh(seed=9, landscapes=["Errand", "Bequest", "Almsgiving"])
    baseline = census(g)
    for _ in range(4000):
        if g["over"]:
            break
        pid = g["pending_pid"] or g["turn"]
        mv = ({"type": "decision", **engine.sample_decision(g, pid, rng)}
              if g["pending_pid"] else rng.choice(engine.legal_moves(g, pid)))
        ok, err = engine.apply_move(g, pid, mv)
        assert ok, err
        assert census(g) == baseline, "card conservation broken"
    assert g["over"], "the game never ended"
    assert any(e["event"] == "buy_landscape" for e in g["log"])
