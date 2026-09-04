// Spender Duel's how-to-play content. Chrome comes from the shared RulesModal kit
// (shared/lobby.jsx) — this file is only the words, and rides Duel's own chunk.
import React from "react";
import { RulesFacts, RulesSection, RulesDefs, RulesTip } from "../../shared/lobby.jsx";

export default function DuelRules() {
	return (
		<>
			<p className="rl-lead">
				A two-player duel built on the same idea as Spender — buy cards, each of which
				discounts every future purchase — but tightened into a knife fight. Tokens are taken
				off a <b>5×5 grid</b> in straight lines, so what you take also decides what you leave
				behind for your opponent. And there are <b>three different ways to win</b>, which means
				you have to watch all three of theirs.
			</p>

			<RulesFacts items={[
				{ k: "Players", v: "2 (friend or bot)" },
				{ k: "Length", v: "15–30 minutes" },
				{ k: "You win by", v: "20 points, or 10 crowns, or 10 points in one color" },
			]} />

			<RulesSection title="The three ways to win">
				<p>The game ends the instant either player reaches <b>any one</b> of these:</p>
				<ul>
					<li><b>20 prestige points</b> in total.</li>
					<li><b>10 crowns</b> — the little crown symbols on cards and royals.</li>
					<li><b>10 points of a single color</b> — counting only the points printed on cards
						that share one bonus color.</li>
				</ul>
				<p>
					There is no "final round". Reaching a threshold ends the game immediately, so the
					color and crown routes are real ambushes: a player at 9 points can be one card from
					winning if those points are all green.
				</p>
			</RulesSection>

			<RulesSection title="The board">
				<ul>
					<li><b>The token grid</b> — 25 cells filled from a bag of 4 tokens in each of the 5
						colors, 2 pearls and 3 gold. Tokens are laid out from the center outward in a
						spiral, and cells stay <b>empty</b> as they're taken.</li>
					<li><b>The card pyramid</b> — 5 face-up level-1 cards (cheap), 4 level-2, 3 level-3
						(expensive, high points and crowns). Each is replaced from its deck when taken.</li>
					<li><b>4 royal cards</b>, claimed by crowns rather than bought.</li>
					<li><b>3 privilege scrolls</b>, starting in the middle between you.</li>
				</ul>
			</RulesSection>

			<RulesSection title="Your turn, in order">
				<p>First, optionally, in this exact order:</p>
				<ol>
					<li><b>Spend privileges</b> ⚜ — each one takes any single gem or pearl off the grid,
						free, and returns the scroll to the middle.</li>
					<li><b>Replenish</b> — refill the empty grid cells from the bag, center-out. This is
						optional and hands your opponent a privilege, so it's a real cost.</li>
				</ol>
				<p>Then you <b>must</b> do exactly one of these three:</p>
				<RulesDefs items={[
					{ t: "Take tokens", d: "1–3 tokens from a single unbroken straight line — horizontal, vertical or diagonal. Empty cells and gold break the line. You can't take gold this way." },
					{ t: "Take gold + reserve", d: "Take a gold token from the grid and reserve any face-up card or the unseen top card of a deck. Reserves are secret from your opponent; you may hold 3." },
					{ t: "Buy a card", d: "From the pyramid or from your reserve, paying its cost. Spent tokens go back into the bag." },
				]} />
				<p>
					Taking <b>3 tokens of the same color</b>, or <b>2 pearls</b>, gives your opponent a
					privilege. That's the price of a greedy line.
				</p>
			</RulesSection>

			<RulesSection title="Cards">
				<p>
					A card's cost is paid in the colors shown; each card you already own gives a
					permanent <b>bonus</b> that discounts that color, and gold is a wild that covers any
					one gem. A few cards give two bonuses at once. Cards can also carry:
				</p>
				{/* The glyphs are the ones painted on the real cards — a legend is worth more
				    here than prose, since a new player's first question is what ↻ means. */}
				<RulesDefs items={[
					{ t: "Points", d: "Prestige, counting toward the 20-point win — and toward the one-color win if the card has a bonus color." },
					{ t: "Crowns", d: "Count toward the 10-crown win and unlock royal cards." },
					{ t: "↻  Take again", d: "Immediately take another turn." },
					{ t: "+● Matching token", d: "Take one token from the grid of that card's own color (the dot is painted in that color)." },
					{ t: "⚜  Take a privilege", d: "Gain a scroll — from the middle, or off your opponent if the middle is empty." },
					{ t: "✋  Steal", d: "Take one token (not gold) straight out of your opponent's hand." },
					{ t: "Grey (wild) cards", d: "Have no color of their own — when bought, they attach to a color you already own and count as that color from then on, points included." },
				]} />
			</RulesSection>

			<RulesSection title="Crowns and royals">
				<p>
					When you reach <b>3 crowns</b>, and again at <b>6</b>, you immediately claim one of
					the four royal cards. They're worth 2–3 points and most carry an ability — another
					turn, a steal, a privilege. Crowns therefore pay twice: toward the royals and toward
					the 10-crown win.
				</p>
			</RulesSection>

			<RulesSection title="Limits">
				<ul>
					<li><b>10 tokens</b> maximum at the end of your turn (gold and pearls included);
						discard the excess back to the bag.</li>
					<li><b>3 reserved cards</b> maximum.</li>
					<li><b>3 privilege scrolls</b> exist in total. If you're owed one and the middle is
						empty, it comes off your opponent instead.</li>
				</ul>
			</RulesSection>

			<p className="rl-note">
				Head-to-head against a friend (share the room code) or against the bot. Expert runs a
				learned neural-network evaluation in your browser and does not make loose trades.
			</p>
		</>
	);
}
