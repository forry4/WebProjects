// Dontminion's how-to-play content. Chrome comes from the shared RulesModal kit
// (shared/lobby.jsx) — this file is only the words, and rides Dontminion's own chunk.
import React from "react";
import { RulesFacts, RulesSection, RulesDefs, RulesTip } from "../../shared/lobby.jsx";

export default function DontminionRules() {
	return (
		<>
			<p className="rl-lead">
				A deck-building game. Everyone starts with the same weak ten-card deck and buys cards
				from a shared <b>Supply</b> in the middle. Everything you buy goes into your own deck,
				gets shuffled in, and comes back around to be played later — so the game is about
				<b> improving the deck you keep drawing from</b>. At the end, whoever has the most
				victory points in their deck wins.
			</p>

			<RulesFacts items={[
				{ k: "Players", v: "2–4 (bots can fill seats)" },
				{ k: "Length", v: "20–40 minutes" },
				{ k: "You win by", v: "Most victory points in your deck at the end" },
			]} />

			<RulesSection title="The central twist">
				<RulesTip>
					<p>
						Victory cards are <b>dead weight</b>. They do nothing when you draw them — no
						coins, no actions — they only count at the very end. So buying points makes your
						deck worse at buying more points. Knowing <i>when</i> to stop improving and start
						hoarding points is the whole game.
					</p>
				</RulesTip>
			</RulesSection>

			<RulesSection title="Setup">
				<ul>
					<li>You begin with <b>7 Coppers and 3 Estates</b>, shuffled. Draw <b>5 cards</b> — that's
						your hand.</li>
					<li>The Supply always has money (<b>Copper $1, Silver $3, Gold $6</b>), points
						(<b>Estate 1 VP, Duchy 3 VP, Province 6 VP</b>), Curses (−1 VP), and <b>ten
						kingdom piles</b> dealt at random from the expansions the host enabled.</li>
					<li>Those ten piles change every game, and they are the game — the same rules produce
						a completely different puzzle each time.</li>
				</ul>
			</RulesSection>

			<RulesSection title="Your turn: A, B, C">
				<RulesDefs items={[
					{ t: "A — Action phase", d: "Play ONE Action card from your hand. Cards themselves can grant more actions (\"+1 Action\" lets you play another), which is how long chains happen. If you have no Action cards, skip straight to B." },
					{ t: "B — Buy phase", d: "Play Treasures from your hand for coins, then buy ONE card from the Supply costing no more than your coins. The card goes to your DISCARD pile, not your hand — you'll draw it a few turns from now. You can't play more Treasures after you've bought." },
					{ t: "C — Clean-up", d: "Everything you played and everything still in your hand goes to the discard pile. Draw a fresh 5 cards. Next player." },
				]} />
				<p>
					You get <b>1 action and 1 buy</b> per turn by default. Cards that say "+1 Buy" or
					"+2 Actions" raise those for the turn only.
				</p>
			</RulesSection>

			<RulesSection title="How your deck cycles">
				<p>
					When your draw pile runs out, your <b>discard pile is shuffled to become the new
					draw pile</b>. That's why a card you buy actually shows up: it enters the discard,
					and comes back on the next shuffle. It also means every card you add dilutes the
					rest — a deck of 10 sees each card often; a deck of 40 rarely.
				</p>
			</RulesSection>

			<RulesSection title="Card types">
				<RulesDefs items={[
					{ t: "Treasure", d: "Played in the buy phase for coins. Copper $1, Silver $3, Gold $6." },
					{ t: "Action", d: "Played in the action phase. Draws cards, gives coins, gives extra actions and buys, attacks — read the card." },
					{ t: "Victory", d: "Estate 1, Duchy 3, Province 6. Worth nothing during play." },
					{ t: "Curse", d: "−1 VP, given to you by attacks. Pure junk." },
					{ t: "Attack", d: "An Action that hits the other players — discarding down, handing out Curses, and worse." },
					{ t: "Reaction", d: "Revealed from your hand when something happens to you. A Moat revealed from hand blocks an attack against you." },
				]} />
			</RulesSection>

			<RulesSection title="How the game ends">
				<p>
					The game ends immediately at the end of a turn when either the <b>Province pile is
					empty</b>, or <b>any three Supply piles are empty</b> (with Colonies in the game,
					emptying the Colony pile ends it too). Then everyone counts the victory points in
					their <b>entire</b> deck — draw pile, discard, hand, everything. Ties go to whoever
					took fewer turns.
				</p>
			</RulesSection>

			<RulesSection title="Reading the board">
				<ul>
					<li><b>Right-click any card</b> — or press and hold it on a touch screen — to read its
						full text, any time, anywhere on the board. With 300+ cards in the pool you will
						use this constantly, and it is never a move.</li>
					<li>A plain click does whatever the card is for right now: play it, buy it, or pick
						it for whatever the current card is asking.</li>
					<li>The button under the Supply moves you on — <b>"To buy phase →"</b> and then
						<b> "End turn"</b>. There's also <b>Play all treasures</b> so you don't have to
						click seven Coppers.</li>
				</ul>
			</RulesSection>

			<RulesSection title="How to actually be good at this">
				<ul>
					<li><b>Buy money early.</b> A Silver on turn 1 or 2 does more than almost any cheap
						action. You cannot buy Provinces at $8 with a deck averaging $1 a card.</li>
					<li><b>One card per turn — respect it.</b> Actions that don't say "+1 Action" end
						your action phase. Two of them in a hand means one sits there uselessly. Cards
						that draw <i>and</i> give an action are the ones worth stacking.</li>
					<li><b>Trashing is a superpower.</b> Anything that removes Coppers and Estates from
						your deck makes every later draw better. This is the most under-rated effect for
						new players.</li>
					<li><b>Don't buy a card just because it's clever.</b> Ask whether it's better than
						the Silver or Gold you could buy instead.</li>
					<li><b>Green at the right moment.</b> A rough rule: start buying Provinces once you
						can reliably hit $8, and grab Duchies when the Province pile is nearly gone.</li>
					<li><b>Watch the piles.</b> Three empty piles ends the game — sometimes you can end
						it deliberately while you're ahead, and sometimes your opponent will.</li>
				</ul>
			</RulesSection>

			<p className="rl-note">
				2–4 seats, any mix of friends and bots. The host picks which expansions the ten kingdom
				piles are dealt from — 11 sets are available, and the box you choose changes the game
				far more than the player count does.
			</p>
		</>
	);
}
